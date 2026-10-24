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
            forecast, stations, alerts, air = [call[0][0].full_url for call in request.call_args_list]
            self.assertIn('latitude=41.27&', forecast); self.assertIn('longitude=-82.05&', forecast)
            self.assertTrue(stations.endswith('/points/41.27,-82.05/stations'))
            self.assertTrue(alerts.endswith('/alerts/active?point=41.27,-82.05'))
            self.assertIn('latitude=41.27&longitude=-82.05&', air)
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
        return {'/v1/forecast': forecast, '/points/': {'features': nearby}, 'KLPR': self.observation(5, 'rain'), '/alerts/': {'features': []}, 'air-quality': {'current': {'us_aqi': 42, 'european_aqi': 21, 'grass_pollen': None}}, **extra}

    def test_nearby_station_rain_reaches_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls = self.run_online(directory, self.routes())
            self.assertEqual(result[-1]['observed']['text'], 'Light rain')
            self.assertEqual(result[-1]['observed']['station'], 'Lorain County Regional Airport')
            self.assertEqual(result[-1]['current']['weather_code'], 61)
            self.assertEqual(len(calls), 5)
            self.assertTrue(calls[1].endswith('/points/41.27,-82.05/stations')); self.assertTrue(calls[2].endswith('/stations/KLPR/observations?limit=1'))
            # The station lookup is remembered, and air quality is hourly; the
            # forecast, the observation, and the alerts repeat.
            _, calls = self.run_online(directory, self.routes())
            self.assertEqual(len(calls), 3); self.assertIn('/alerts/', calls[2])

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
        def missing(body, code=404): return w.urllib.error.HTTPError('https://api.weather.gov', code, 'Not Found', None, io.BytesIO(json.dumps(body).encode()))
        with tempfile.TemporaryDirectory() as directory:
            # The second run shows the saved forecast, then the fresh one; neither adds a station report or alerts.
            for expected, reports in ((4, 2), (1, 2)):
                routes = self.routes(**{'/points/': missing({'type': 'https://api.weather.gov/problems/InvalidPoint'}),
                                        '/alerts/': missing({'status': 400, 'detail': 'Parameter "point" is invalid: out of bounds'}, 400)})
                result, calls = self.run_online(directory, routes, latitude=51.51, longitude=-0.13)
                self.assertEqual(len(calls), expected); self.assertEqual(len(result), reports)
                self.assertTrue(result[-1]['available']); self.assertFalse(result[-1]['stale']); self.assertNotIn('observed', result[-1])
                self.assertEqual(result[-1]['alerts'], [])
        # A 404 that is not about the point is passing trouble: ask again next time.
        with tempfile.TemporaryDirectory() as directory:
            for _ in range(2):
                _, calls = self.run_online(directory, self.routes(**{'/points/': missing({'type': 'https://api.weather.gov/problems/NotFound'})}))
                self.assertEqual(len([call for call in calls if '/points/' in call]), 1)
            self.assertFalse((pathlib.Path(directory) / 'stations.json').exists())

    def test_distant_stations_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            far = {'features': [self.station('KFAR', 'Far Airport', 42.3, -82.05)]}
            result, calls = self.run_online(directory, self.routes(**{'/points/': far, 'KFAR': self.observation(5, 'rain')}))
            self.assertFalse(any('KFAR' in call for call in calls)); self.assertNotIn('observed', result[-1])

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

    def test_later_days_are_shown_two_hours_to_a_cell(self):
        hours = [{'time': '2026-10-08T%02d:00' % h, 'temperature_2m': h, 'weather_code': 61 if h == 15 else 1, 'is_day': int(7 <= h < 19),
                  'precipitation_probability': h, 'precipitation': .2 if h in (14, 15) else 0} for h in range(24)]
        cells = w.day_hours(hours, ['2026-10-08', '2026-10-09'])['2026-10-08']
        self.assertEqual(len(cells), 12)
        self.assertEqual(cells[7], {'time': '2026-10-08T14:00', 'temperature_2m': 14, 'weather_code': 61, 'is_day': 1, 'precipitation_probability': 15, 'precipitation': .4})
        self.assertEqual(cells[3]['is_day'], 1)
        # A daylight-saving day with a missing hour still fills its cells in order.
        short = w.day_hours([h for h in hours if h['time'][11:13] != '02'], ['2026-10-08'])['2026-10-08']
        self.assertEqual([c['time'][11:13] for c in short[:3]], ['00', '03', '04'])
        self.assertNotIn('2026-10-09', w.day_hours(hours, ['2026-10-09']))

    def test_later_days_reach_the_report_but_today_does_not(self):
        cache = w.normalize(self.hourly_fixture()); cache['fetchedAt'] = 0
        result = w.present(cache, now=dt.datetime(2026, 10, 6, 19, 40, tzinfo=dt.timezone.utc))
        self.assertEqual(sorted(result['dayHours']), ['2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11'])
        self.assertTrue(all(len(cells) == 12 for cells in result['dayHours'].values()))

    def test_yesterday_is_kept_for_comparison_but_not_listed(self):
        raw = fixture(); raw['daily']['time'] = ['2026-10-%02d' % n for n in range(5, 12)]
        raw['daily']['temperature_2m_max'][0] = 17
        cache = w.normalize(raw); cache['fetchedAt'] = 0
        result = w.present(cache, now=dt.datetime(2026, 10, 6, 19, tzinfo=dt.timezone.utc))
        self.assertEqual(result['yesterday']['temperature_2m_max'], 17)
        self.assertEqual(result['days'][0]['date'], '2026-10-06')
        self.assertIsNone(w.present(w.normalize(fixture()) | {'fetchedAt': 0}, now=dt.datetime(2026, 10, 6, 19, tzinfo=dt.timezone.utc))['yesterday'])

    def minutely(self, *rain, start='2026-10-06T15:45'):
        first = dt.datetime.fromisoformat(start)
        return [{'time': (first + dt.timedelta(minutes=15 * i)).isoformat(timespec='minutes'), 'precipitation': r} for i, r in enumerate(rain)]

    def nowcast(self, rain, seen=None, hours=None, code=3):
        # 19:40 UTC is 15:40 in New York: the first slot, ending 15:45, is now.
        cache = {'minutely': rain, 'hours': hours or [], 'current': {'weather_code': code}}
        return w.nowcast(cache, dt.datetime(2026, 10, 6, 15, 40, tzinfo=w.ZoneInfo('America/New_York')), seen)

    def test_rain_starting_is_timed_from_the_quarter_hour(self):
        self.assertEqual(self.nowcast(self.minutely(0, 0, .3, .5)), {'state': 'starting', 'at': '2026-10-06T16:00', 'minutes': 20, 'kind': 'rain'})
        cold = [{'time': '2026-10-06T16:00', 'temperature_2m': -2, 'weather_code': 3}]
        self.assertEqual(self.nowcast(self.minutely(0, 0, .3), hours=cold)['kind'], 'snow')
        self.assertIsNone(self.nowcast(self.minutely(0, 0, 0, 0)))

    def test_rain_easing_ignores_a_short_lull(self):
        self.assertEqual(self.nowcast(self.minutely(.4, 0, .2, 0, 0, 0))['at'], '2026-10-06T16:15')
        self.assertEqual(self.nowcast(self.minutely(.4, .2, .2), code=73), {'state': 'continuing', 'at': '2026-10-06T16:15', 'minutes': 35, 'kind': 'snow'})

    def test_nowcast_says_nothing_it_cannot_know(self):
        # A station sees rain the model does not.
        self.assertIsNone(self.nowcast(self.minutely(0, 0, .3), seen={'code': 61}))
        # The forecast is too old to reach the present.
        self.assertIsNone(self.nowcast(self.minutely(.3, .3, start='2026-10-06T12:00')))
        for junk in (None, 'nope', [{'time': 'later', 'precipitation': 1}, {'time': '2026-10-06T16:00', 'precipitation': None}]):
            self.assertIsNone(self.nowcast(junk))

    def test_minutely_rain_is_kept_from_the_forecast(self):
        raw = fixture(); raw['minutely_15'] = {'time': ['2026-10-06T16:00', '2026-10-06T16:15', 'bad'], 'precipitation': [0, None, .2]}
        self.assertEqual(w.normalize(raw)['minutely'], [{'time': '2026-10-06T16:00', 'precipitation': 0}])
        self.assertEqual(w.normalize(fixture())['minutely'], [])

    def alert(self, event='Winter Storm Warning', ident='urn:1', severity='Severe', urgency='Expected', expires='2026-10-07T18:00:00-04:00', **extra):
        return {'id': ident, 'properties': {'id': ident, 'event': event, 'severity': severity, 'urgency': urgency, 'status': 'Actual', 'messageType': 'Alert',
                'headline': event + ' issued', 'expires': expires, 'ends': extra.pop('ends', None), 'senderName': 'NWS Cleveland OH',
                'description': '* WHAT...Heavy snow.\nUp to a foot.\n\n* WHEN...Tonight.', 'instruction': None, **extra}}

    def test_alerts_are_read_ranked_and_cleaned(self):
        features = [self.alert('Wind Advisory', 'urn:a', 'Moderate'), self.alert('Winter Storm Watch', 'urn:w'), self.alert(),
                    self.alert('Test Message', 'urn:t', status='Test'), self.alert('Flood Warning', 'urn:c', messageType='Cancel'),
                    self.alert('Freeze Warning', 'urn:x', expires='whenever'), None]
        with patch.object(w, 'get_json', return_value={'features': features}):
            alerts = w.fetch_alerts(41.27, -82.05)
        self.assertEqual([a['event'] for a in alerts], ['Winter Storm Warning', 'Winter Storm Watch', 'Wind Advisory'])
        self.assertEqual([a['tier'] for a in alerts], ['warning', 'watch', 'advisory'])
        self.assertEqual(alerts[0]['description'], '* WHAT...Heavy snow. Up to a foot.\n* WHEN...Tonight.')
        with patch.object(w, 'get_json', return_value={'features': [None]}), self.assertRaises(ValueError):
            w.fetch_alerts(41.27, -82.05)

    def test_alerts_show_in_local_time_until_they_expire(self):
        with patch.object(w, 'get_json', return_value={'features': [self.alert(ends='2026-10-07T14:00:00+00:00'), self.alert('Wind Advisory', 'urn:a', expires='2026-10-06T20:00:00Z')]}):
            alerts = w.check_alerts(41.27, -82.05, None)
        cache = w.normalize(fixture()); cache.update(fetchedAt=0, alerts=alerts)
        result = w.present(cache, now=dt.datetime(2026, 10, 6, 19, tzinfo=dt.timezone.utc))
        self.assertEqual([(a['event'], a['until']) for a in result['alerts']], [('Winter Storm Warning', '2026-10-07T10:00'), ('Wind Advisory', '2026-10-06T16:00')])
        self.assertNotIn('expires', result['alerts'][0])
        later = w.present(cache, now=dt.datetime(2026, 10, 6, 21, tzinfo=dt.timezone.utc))
        self.assertEqual([a['event'] for a in later['alerts']], ['Winter Storm Warning'])
        # A failed check keeps what was known.
        with patch.object(w, 'get_json', side_effect=OSError('down')):
            self.assertEqual(w.check_alerts(41.27, -82.05, alerts)['items'], alerts['items'])

    def test_air_quality_is_shown_only_while_recent(self):
        now = dt.datetime(2026, 10, 6, 19, tzinfo=dt.timezone.utc)
        with patch.object(w, 'get_json', return_value={'current': {'us_aqi': 76, 'european_aqi': 35, 'grass_pollen': 40.5, 'birch_pollen': None}}), patch.object(w.time, 'time', return_value=now.timestamp()):
            air = w.check_air(41.27, -82.05, None)
        cache = w.normalize(fixture()); cache.update(fetchedAt=0, air=air)
        self.assertEqual(w.present(cache, now=now)['air'], {'us_aqi': 76, 'european_aqi': 35, 'pollen': {'grass': 40.5}})
        self.assertIsNone(w.present(cache, now=now + dt.timedelta(hours=4))['air'])
        with patch.object(w, 'get_json', return_value={'current': {'us_aqi': None}}):
            self.assertEqual(w.check_air(41.27, -82.05, air)['us_aqi'], 76)

    def announce(self, directory, alerts, mode='alerts', nowcast=None):
        status = {'available': True, 'stale': False, 'location': 'Test City', 'alerts': alerts, 'nowcast': nowcast}
        with patch.object(w, 'STATE', pathlib.Path(directory)), patch.object(w, 'notify') as sent:
            w.announce(status, mode)
        return [call.args[1] for call in sent.call_args_list]

    def shown(self, event='Winter Storm Warning', ident='urn:1', rank=3, urgency=2, references=()):
        return {'id': ident, 'event': event, 'tier': w.alert_class(event), 'headline': event, 'rank': rank, 'urgency': urgency, 'references': list(references)}

    def test_alert_notifications_announce_each_alert_once(self):
        with tempfile.TemporaryDirectory() as directory:
            # Alerts already active when notifications start are only noted...
            self.assertEqual(self.announce(directory, [self.shown()]), [])
            # ...unless one needs action now.
            with tempfile.TemporaryDirectory() as other:
                self.assertEqual(self.announce(other, [self.shown('Tornado Warning', 'urn:t', 4, 3)]), ['Tornado Warning'])
            self.assertEqual(self.announce(directory, [self.shown(), self.shown('Wind Advisory', 'urn:a', 2)]), [])
            self.assertEqual(self.announce(directory, [self.shown(), self.shown('Winter Storm Watch', 'urn:w', 2)]), ['Winter Storm Watch'])
            # An update is quiet; a watch raised to a warning is not.
            self.assertEqual(self.announce(directory, [self.shown(ident='urn:2', references=['urn:1'])]), [])
            self.assertEqual(self.announce(directory, [self.shown(ident='urn:3', references=['urn:w'])]), ['Winter Storm Warning'])

    def test_notifications_off_still_remember_what_was_active(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.announce(directory, [self.shown('Tornado Warning', 'urn:t', 4, 3)], 'off'), [])
            self.assertEqual(self.announce(directory, [self.shown('Tornado Warning', 'urn:t', 4, 3), self.shown('Flood Watch', 'urn:f', 2)]), [])
            self.assertEqual(self.announce(directory, [self.shown('Flood Warning', 'urn:g', 3)]), ['Flood Warning'])

    def test_rain_notification_comes_once_per_shower(self):
        soon = {'state': 'starting', 'minutes': 18, 'kind': 'rain', 'at': '2026-10-06T16:00'}
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.announce(directory, [], 'alerts', soon), [])
            self.assertEqual(self.announce(directory, [], 'all', soon), ['Rain starting in about 20 minutes'])
            self.assertEqual(self.announce(directory, [], 'all', soon), [])
            self.assertEqual(self.announce(directory, [], 'all', {**soon, 'minutes': 50}), [])

if __name__ == '__main__': unittest.main()
