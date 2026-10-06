import contextlib
import datetime as dt
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('weather', pathlib.Path(__file__).parents[1] / 'weather.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

def fixture():
    return {'timezone': 'America/New_York', 'current': {'temperature_2m': 20}, 'daily': {'time': ['2026-10-%02d' % n for n in range(6, 13)], **{key: [22 if key == 'temperature_2m_max' else 10 if key == 'temperature_2m_min' else 0] * 7 for key in w.FIELDS.split(',')}}}

class WeatherTests(unittest.TestCase):
    def test_full_day_high_survives_evening(self):
        cache = w.normalize(fixture())
        cache['fetchedAt'] = dt.datetime(2026, 10, 6, 20, tzinfo=dt.timezone.utc).timestamp()
        result = w.present(cache, now=dt.datetime(2026, 10, 7, 1, tzinfo=dt.timezone.utc))
        self.assertEqual(result['today']['date'], '2026-10-06')
        self.assertEqual(result['today']['temperature_2m_max'], 22)
        self.assertEqual(len(result['days']), 6)

    def test_location_midnight_rollover(self):
        cache = w.normalize(fixture()); cache['fetchedAt'] = 0
        result = w.present(cache, now=dt.datetime(2026, 10, 7, 4, 1, tzinfo=dt.timezone.utc))
        self.assertEqual(result['today']['date'], '2026-10-07')
        self.assertEqual(result['days'][0]['date'], '2026-10-07')
        self.assertEqual(len(result['days']), 6)

    def test_old_forecast_never_calls_yesterday_today(self):
        cache = w.normalize(fixture()); cache['fetchedAt'] = 0
        result = w.present(cache, 'Offline', now=dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc))
        self.assertIsNone(result['today']); self.assertEqual(result['days'], [])
        self.assertTrue(result['stale'])

    def test_rejects_partial_or_nonfinite_response(self):
        raw = fixture(); raw['daily']['temperature_2m_max'][0] = None
        with self.assertRaises(ValueError): w.normalize(raw)
        raw = fixture(); raw['current']['temperature_2m'] = float('nan')
        with self.assertRaises(ValueError): w.normalize(raw)

    def test_rejects_wrong_response_structure(self):
        for raw in ([], None, {'daily': [], 'current': []}):
            with self.assertRaises(ValueError): w.normalize(raw)

    def test_moon_reference_and_full_cycle(self):
        new = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
        self.assertEqual(w.moon(new)['name'], 'New moon')
        self.assertEqual(w.moon(new)['illumination'], 0)
        self.assertEqual(w.moon(new + dt.timedelta(days=29.530588853 / 2))['illumination'], 100)

    def run_client(self, directory, cache=None):
        state = pathlib.Path(directory)
        location = state / 'location.json'
        location.write_text(json.dumps({'name': 'Test City', 'latitude': 41, 'longitude': -82}))
        if cache: (state / 'forecast.json').write_text(json.dumps(cache))
        output = io.StringIO()
        with patch.object(w, 'STATE', state), patch.object(w, 'LOCATION', location), patch('sys.argv', ['weather.py']), patch.object(w.urllib.request, 'urlopen', side_effect=OSError('offline')) as request, contextlib.redirect_stdout(output):
            w.main()
        return [json.loads(line) for line in output.getvalue().splitlines()], request.call_count

    def test_offline_preserves_cache_and_backoff(self):
        cache = w.normalize(fixture()); cache.update(fetchedAt=0, locationKey=[41, -82], location='Test City')
        with tempfile.TemporaryDirectory() as directory:
            result, calls = self.run_client(directory, cache)
            self.assertTrue(result[-1]['available']); self.assertTrue(result[-1]['stale']); self.assertEqual(calls, 1)
            result, calls = self.run_client(directory)
            self.assertEqual(calls, 0); self.assertTrue(result[-1]['available'])

    def test_location_change_does_not_reuse_wrong_city(self):
        cache = w.normalize(fixture()); cache.update(fetchedAt=0, locationKey=[0, 0], location='Wrong City')
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_client(directory, cache)
            self.assertFalse(result[-1]['available'])

    def test_corrupt_cache_recovers_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            (pathlib.Path(directory) / 'forecast.json').write_text('{broken')
            result, _ = self.run_client(directory)
            self.assertFalse(result[-1]['available'])

    def test_successful_fetch_writes_valid_atomic_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory); location = state / 'location.json'
            location.write_text(json.dumps({'name': 'Test City', 'latitude': 41, 'longitude': -82}))
            response = io.BytesIO(json.dumps(fixture()).encode())
            output = io.StringIO()
            with patch.object(w, 'STATE', state), patch.object(w, 'LOCATION', location), patch('sys.argv', ['weather.py', '--force']), patch.object(w.urllib.request, 'urlopen', return_value=response), contextlib.redirect_stdout(output):
                w.main()
            self.assertEqual(json.loads((state / 'forecast.json').read_text())['location'], 'Test City')
            self.assertFalse((state / 'forecast.tmp').exists())
            self.assertTrue(json.loads(output.getvalue())['available'])

    def test_southern_hemisphere_is_flagged_for_the_moon(self):
        now = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)
        self.assertFalse(w.moon(now)['southern'])
        self.assertTrue(w.present(None, now=now, southern=True)['moon']['southern'])
        self.assertEqual(w.moon(now)['phase'], w.moon(now, southern=True)['phase'])

    def test_missing_location_asks_for_one(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory); output = io.StringIO()
            with patch.object(w, 'STATE', state), patch.object(w, 'LOCATION', state / 'missing.json'), patch('sys.argv', ['weather.py']), contextlib.redirect_stdout(output):
                w.main()
            result = json.loads(output.getvalue())
            self.assertFalse(result['available']); self.assertIn('location', result['error'])

    def test_unusable_state_directory_is_not_blamed_on_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); location = root / 'location.json'
            location.write_text(json.dumps({'name': 'Test City', 'latitude': -41, 'longitude': 174}))
            (root / 'file').write_text('')
            output = io.StringIO()
            with patch.object(w, 'STATE', root / 'file' / 'state'), patch.object(w, 'LOCATION', location), patch('sys.argv', ['weather.py']), contextlib.redirect_stdout(output):
                w.main()
            result = json.loads(output.getvalue())
            self.assertFalse(result['available']); self.assertIn('cache', result['error'])
            self.assertNotIn('location', result['error']); self.assertTrue(result['moon']['southern'])

    def test_request_uses_coarse_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory); location = state / 'location.json'
            location.write_text(json.dumps({'name': 'Test City', 'latitude': 41.27255, 'longitude': -82.05459}))
            response = io.BytesIO(json.dumps(fixture()).encode())
            with patch.object(w, 'STATE', state), patch.object(w, 'LOCATION', location), patch('sys.argv', ['weather.py', '--force']), patch.object(w.urllib.request, 'urlopen', return_value=response) as request, contextlib.redirect_stdout(io.StringIO()):
                w.main()
            url = request.call_args[0][0].full_url
            self.assertIn('latitude=41.27&', url); self.assertIn('longitude=-82.05&', url)
            self.assertEqual(json.loads((state / 'forecast.json').read_text())['locationKey'], [41.27, -82.05])

    def hourly_fixture(self):
        raw = fixture()
        times = ['2026-10-%02dT%02d:00' % (6 + d, h) for d in range(7) for h in range(24)]
        raw['hourly'] = {'time': times, 'temperature_2m': [15] * 168, 'precipitation_probability': [10] * 168, 'weather_code': [1] * 168, 'is_day': [1] * 168}
        return raw

    def test_next_twelve_hours_start_with_the_current_hour(self):
        cache = w.normalize(self.hourly_fixture()); cache['fetchedAt'] = 0
        self.assertEqual(len(cache['hours']), 168)
        # 19:40 UTC is 15:40 in New York.
        result = w.present(cache, now=dt.datetime(2026, 10, 6, 19, 40, tzinfo=dt.timezone.utc))
        self.assertEqual(len(result['hours']), 12)
        self.assertEqual(result['hours'][0]['time'], '2026-10-06T15:00')
        self.assertEqual(result['hours'][-1]['time'], '2026-10-07T02:00')

    def test_bad_hourly_data_never_costs_the_daily_forecast(self):
        for hourly in (None, [], 'nope', {'time': 'nope'}, {'time': ['2026-10-06T00:00']}):
            raw = fixture(); raw['hourly'] = hourly
            self.assertEqual(w.normalize(raw)['hours'], [])
        raw = self.hourly_fixture(); raw['hourly']['temperature_2m'][0] = None; raw['hourly']['time'][1] = 'not a time'
        self.assertEqual(len(w.normalize(raw)['hours']), 166)
        cache = w.normalize(fixture()); cache.update(fetchedAt=0, hours='corrupt')
        self.assertEqual(w.present(cache, now=dt.datetime(2026, 10, 6, 19, tzinfo=dt.timezone.utc))['hours'], [])

    def test_cache_from_an_older_version_still_loads(self):
        cache = w.normalize(fixture()); del cache['hours']
        for day in cache['days']: del day['apparent_temperature_max']
        cache.update(fetchedAt=0, locationKey=[41, -82], location='Test City')
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_client(directory, cache)
            self.assertTrue(result[-1]['available']); self.assertEqual(result[-1]['hours'], [])

if __name__ == '__main__': unittest.main()
