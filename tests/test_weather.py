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

if __name__ == '__main__': unittest.main()
