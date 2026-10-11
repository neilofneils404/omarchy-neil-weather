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
            forecast, stations = [call[0][0].full_url for call in request.call_args_list]
            self.assertIn('latitude=41.27&', forecast); self.assertIn('longitude=-82.05&', forecast)
            self.assertTrue(stations.endswith('/points/41.27,-82.05/stations'))
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

    def test_station_reports_map_to_weather_codes(self):
        def seen(*reports): return w.observed_weather([dict(zip(('weather', 'intensity', 'modifier'), r)) for r in reports])
        self.assertEqual(seen(('rain', 'light')), (61, 'Light rain'))
        self.assertEqual(seen(('rain', None)), (63, 'Rain'))
        self.assertEqual(seen(('rain', 'heavy', 'showers')), (82, 'Heavy rain showers'))
        self.assertEqual(seen(('rain', 'light', 'freezing')), (66, 'Light freezing rain'))
        self.assertEqual(seen(('drizzle', 'light')), (51, 'Light drizzle'))
        self.assertEqual(seen(('snow', 'heavy')), (75, 'Heavy snow'))
        self.assertEqual(seen(('ice_pellets', None)), (77, 'Sleet'))
        self.assertEqual(seen(('snow', 'heavy', 'showers')), (86, 'Heavy snow showers'))
        # Snow blown off the ground is not snow falling.
        self.assertEqual(seen(('snow', None, 'blowing'), ('snow', None, 'low_drifting')), (None, ''))
        # Unidentified precipitation is drawn as snow only when it is freezing.
        self.assertEqual(seen(('unknown', 'light')), (61, 'Light precipitation'))
        self.assertEqual(w.observed_weather([{'weather': 'unknown', 'intensity': 'light'}], cold=True), (71, 'Light precipitation'))
        # The strongest thing falling wins; mist and haze are not precipitation.
        self.assertEqual(seen(('fog_mist', None), ('rain', 'light'), ('snow', 'light')), (71, 'Light snow'))
        self.assertEqual(seen(('rain', 'heavy'), ('thunderstorms', None)), (95, 'Thunderstorms'))
        self.assertEqual(seen(('fog_mist', None), ('haze', None)), (None, ''))
        self.assertEqual(w.observed_weather([{'weather': 'rain', 'intensity': 'light', 'inVicinity': True}]), (None, ''))
        for junk in (None, 'rain', [None, 'rain', {}], [{'weather': None}]):
            self.assertEqual(w.observed_weather(junk), (None, ''))

    def test_observed_rain_replaces_the_modeled_sky_only_while_recent(self):
        cache = w.normalize(self.hourly_fixture())
        now = dt.datetime(2026, 10, 6, 19, 40, tzinfo=dt.timezone.utc)
        cache.update(fetchedAt=now.timestamp(), observation={'time': now.timestamp() - 480, 'code': 61, 'text': 'Light rain', 'name': 'Test Airport'})
        cache['current']['weather_code'] = 3
        result = w.present(cache, now=now)
        self.assertEqual(result['observed'], {'code': 61, 'text': 'Light rain', 'station': 'Test Airport', 'ageMinutes': 8})
        self.assertEqual(result['current']['weather_code'], 61)
        self.assertEqual([h['weather_code'] for h in result['hours'][:2]], [61, 1])
        self.assertNotIn('observation', result)
        # The saved forecast itself is left as modeled.
        self.assertEqual(cache['current']['weather_code'], 3); self.assertEqual(cache['hours'][15]['weather_code'], 1)
        later = w.present(cache, now=now + dt.timedelta(minutes=50))
        self.assertNotIn('observed', later); self.assertEqual(later['current']['weather_code'], 3)

    def test_dry_or_malformed_observations_change_nothing(self):
        now = dt.datetime(2026, 10, 6, 19, 40, tzinfo=dt.timezone.utc)
        for observation in ({'time': now.timestamp(), 'code': None, 'text': ''}, {'checkedAt': 1}, {'time': 'now', 'code': 61, 'text': 'Rain'}, {'time': now.timestamp(), 'code': 61}, 'corrupt', None):
            cache = w.normalize(fixture()); cache.update(fetchedAt=now.timestamp(), observation=observation)
            result = w.present(cache, now=now)
            self.assertNotIn('observed', result); self.assertNotIn('weather_code', result['current'])

    def run_online(self, directory, routes, force=True, latitude=41.27255, longitude=-82.05459):
        # routes maps a URL fragment to a JSON body, or to an exception to raise.
        state = pathlib.Path(directory); location = state / 'location.json'
        location.write_text(json.dumps({'name': 'Test City', 'latitude': latitude, 'longitude': longitude}))
        calls, output = [], io.StringIO()
        def urlopen(request, timeout=None):
            calls.append(request.full_url)
            body = next((body for fragment, body in routes.items() if fragment in request.full_url), OSError('unrouted'))
            if isinstance(body, Exception): raise body
            return io.BytesIO(json.dumps(body).encode())
        with patch.object(w, 'STATE', state), patch.object(w, 'LOCATION', location), patch('sys.argv', ['weather.py'] + ['--force'] * force), patch.object(w.urllib.request, 'urlopen', side_effect=urlopen), contextlib.redirect_stdout(output):
            w.main()
        return [json.loads(line) for line in output.getvalue().splitlines()], calls

    def station(self, identifier, name, latitude, longitude):
        return {'properties': {'stationIdentifier': identifier, 'name': name}, 'geometry': {'coordinates': [longitude, latitude]}}

    def observation(self, minutes_ago=5, *weather):
        when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
        return {'features': [{'properties': {'timestamp': when.isoformat(timespec='seconds'), 'presentWeather': [{'weather': kind, 'intensity': 'light', 'modifier': None} for kind in weather]}}]}

    def routes(self, **extra):
        nearby = [self.station('KLPR', 'Lorain / Elyria, Lorain County Regional Airport', 41.34, -82.18), self.station('KCLE', 'Cleveland Hopkins International Airport', 41.41, -81.85), self.station('KBKL', 'Cleveland, Burke Lakefront Airport', 41.52, -81.68)]
        # A forecast that covers the real today, whenever the suite runs.
        forecast = fixture(); start = dt.date.today() - dt.timedelta(days=2)
        forecast['daily']['time'] = [(start + dt.timedelta(days=n)).isoformat() for n in range(7)]
        return {'open-meteo': forecast, '/points/': {'features': nearby}, 'KLPR': self.observation(5, 'rain'), **extra}

    def test_nearby_station_rain_reaches_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls = self.run_online(directory, self.routes())
            self.assertEqual(result[-1]['observed']['text'], 'Light rain')
            self.assertEqual(result[-1]['observed']['station'], 'Lorain County Regional Airport')
            self.assertEqual(result[-1]['current']['weather_code'], 61)
            self.assertEqual(len(calls), 3)
            self.assertTrue(calls[1].endswith('/points/41.27,-82.05/stations')); self.assertTrue(calls[2].endswith('/stations/KLPR/observations?limit=1'))
            # The station lookup is remembered; only the forecast and the observation repeat.
            _, calls = self.run_online(directory, self.routes())
            self.assertEqual(len(calls), 2)

    def test_fresh_forecast_rechecks_only_the_sky(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_online(directory, self.routes(KLPR=self.observation(5)))
            result, calls = self.run_online(directory, self.routes(), force=False)
            self.assertEqual(calls, []); self.assertNotIn('observed', result[-1])
            path = pathlib.Path(directory) / 'forecast.json'
            cache = json.loads(path.read_text()); cache['observation']['checkedAt'] -= 400; path.write_text(json.dumps(cache))
            result, calls = self.run_online(directory, self.routes(), force=False)
            self.assertEqual(len(calls), 1); self.assertIn('KLPR', calls[0])
            self.assertEqual(result[-1]['observed']['text'], 'Light rain'); self.assertFalse(result[-1]['stale'])

    def test_stale_or_failing_station_falls_back_to_the_next(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls = self.run_online(directory, self.routes(KLPR=self.observation(90, 'rain'), KCLE=self.observation(5, 'snow')))
            self.assertEqual(result[-1]['observed']['text'], 'Light snow'); self.assertEqual(result[-1]['observed']['station'], 'Cleveland Hopkins International Airport')
            result, calls = self.run_online(directory, self.routes(KLPR=OSError('down'), KCLE={'features': []}))
            # Nothing newer could be had, so the earlier report stays until it ages out.
            self.assertEqual(result[-1]['observed']['text'], 'Light snow')
            self.assertFalse(any('KBKL' in call for call in calls))

    def test_outside_nws_coverage_is_remembered_and_shows_nothing(self):
        def missing(body): return w.urllib.error.HTTPError('https://api.weather.gov', 404, 'Not Found', None, io.BytesIO(json.dumps(body).encode()))
        with tempfile.TemporaryDirectory() as directory:
            # The second run shows the saved forecast, then the fresh one; neither adds a station report.
            for expected, reports in ((2, 1), (1, 2)):
                routes = self.routes(**{'/points/': missing({'type': 'https://api.weather.gov/problems/InvalidPoint'})})
                result, calls = self.run_online(directory, routes, latitude=51.51, longitude=-0.13)
                self.assertEqual(len(calls), expected); self.assertEqual(len(result), reports)
                self.assertTrue(result[-1]['available']); self.assertFalse(result[-1]['stale']); self.assertNotIn('observed', result[-1])
        # A 404 that is not about the point is passing trouble: ask again next time.
        with tempfile.TemporaryDirectory() as directory:
            for _ in range(2):
                _, calls = self.run_online(directory, self.routes(**{'/points/': missing({'type': 'https://api.weather.gov/problems/NotFound'})}))
                self.assertEqual(len(calls), 2)
            self.assertFalse((pathlib.Path(directory) / 'stations.json').exists())

    def test_distant_stations_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            far = {'features': [self.station('KFAR', 'Far Airport', 42.3, -82.05)]}
            result, calls = self.run_online(directory, self.routes(**{'/points/': far, 'KFAR': self.observation(5, 'rain')}))
            self.assertEqual(len(calls), 2); self.assertNotIn('observed', result[-1])

    def test_nws_trouble_never_costs_the_forecast(self):
        for trouble in (OSError('down'), {'features': 'nope'}, {'features': [{'properties': {}}]}, []):
            with tempfile.TemporaryDirectory() as directory:
                result, _ = self.run_online(directory, self.routes(**{'/points/': trouble}))
                self.assertTrue(result[-1]['available']); self.assertFalse(result[-1]['stale']); self.assertEqual(result[-1]['error'], '')

    def test_nearest_station_wins_whatever_order_nws_lists_them_in(self):
        with tempfile.TemporaryDirectory() as directory:
            listed = {'features': [self.station('KBKL', 'Burke Lakefront Airport', 41.52, -81.68), self.station('KCLE', 'Cleveland Hopkins International Airport', 41.41, -81.85), self.station('KLPR', 'Lorain County Regional Airport', 41.34, -82.18)]}
            result, calls = self.run_online(directory, self.routes(**{'/points/': listed}))
            self.assertIn('KLPR', calls[2]); self.assertEqual(json.loads((pathlib.Path(directory) / 'stations.json').read_text())['stations'][1]['id'], 'KCLE')

    def test_forecast_is_saved_and_shown_before_the_station_is_asked(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_online(directory, self.routes())
            self.assertEqual(len(result), 2)
            self.assertNotIn('observed', result[0]); self.assertEqual(result[1]['observed']['text'], 'Light rain')

    def test_bogus_station_timestamps_are_skipped_not_fatal(self):
        for timestamp in ('0001-01-01T00:00:00+00:00', (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).isoformat(), 'yesterday', None):
            with tempfile.TemporaryDirectory() as directory:
                broken = self.observation(5, 'rain'); broken['features'][0]['properties']['timestamp'] = timestamp
                result, calls = self.run_online(directory, self.routes(KLPR=broken, KCLE=self.observation(5, 'snow')))
                self.assertEqual(result[-1]['observed']['text'], 'Light snow', timestamp)

    def test_one_malformed_station_does_not_hide_the_others(self):
        with tempfile.TemporaryDirectory() as directory:
            mixed = {'features': [{'properties': {'stationIdentifier': 'KBAD'}, 'geometry': None}, None, self.station('KLPR', 'Lorain County Regional Airport', 41.34, -82.18)]}
            result, _ = self.run_online(directory, self.routes(**{'/points/': mixed}))
            self.assertEqual(result[-1]['observed']['station'], 'Lorain County Regional Airport')

if __name__ == '__main__': unittest.main()
