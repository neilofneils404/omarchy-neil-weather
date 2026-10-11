#!/usr/bin/env python3
"""Dependency-free Open-Meteo client, with US station observations from the NWS. SI cache, atomic writes, bounded requests."""
import argparse, datetime as dt, fcntl, http.client, json, math, os, pathlib, time
import urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
HOME = pathlib.Path.home()
STATE = HOME / '.local/state/neil-weather'
LOCATION = HOME / '.local/state/omarchy/settings/weather.json'
FIELDS = 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,daylight_duration,uv_index_max,apparent_temperature_max,apparent_temperature_min'
CURRENT = 'temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code,is_day'
HOURLY = 'temperature_2m,precipitation_probability,weather_code,is_day'
SYNODIC = 29.530588853
NWS = 'https://api.weather.gov'
USER_AGENT = 'neil.weather/1.3 (https://github.com/neilofneils404/omarchy-neil-weather)'
# A station report stands in for the modeled sky only while it is this recent
# (seconds), and only from a station this close (km).
OBSERVATION_MAX_AGE, OBSERVATION_INTERVAL, STATION_RANGE = 2700, 300, 40
FETCH_ERRORS = (OSError, ValueError, KeyError, TypeError, http.client.HTTPException)
# Station reports are a bonus: nothing odd in one may reach the forecast.
OBSERVE_ERRORS = FETCH_ERRORS + (IndexError, AttributeError, OverflowError)

def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def clean_hours(rows):
    # Hourly detail is optional: anything malformed is dropped, never fatal,
    # so a bad hourly block cannot cost the user their daily forecast.
    hours = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get('time'), str):
            continue
        try:
            dt.datetime.fromisoformat(row['time'])
        except ValueError:
            continue
        if number(row.get('temperature_2m')) and number(row.get('weather_code')):
            hours.append({'time': row['time'], **{k: row.get(k) for k in HOURLY.split(',')}})
    return hours

def hourly_rows(hourly):
    # Open-Meteo sends parallel columns; turn them into one row per hour.
    if not isinstance(hourly, dict) or not isinstance(hourly.get('time'), list):
        return []
    columns = {k: hourly.get(k) if isinstance(hourly.get(k), list) else [] for k in HOURLY.split(',')}
    return clean_hours([{'time': time, **{k: v[i] if i < len(v) else None for k, v in columns.items()}} for i, time in enumerate(hourly['time'])])

def normalize(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('daily'), dict) or not isinstance(raw.get('current'), dict):
        raise ValueError('Invalid forecast structure')
    zone = ZoneInfo(raw['timezone'])
    daily, current = raw['daily'], raw['current']
    if not number(current.get('temperature_2m')):
        raise ValueError('Current temperature missing')
    days = []
    for i, date in enumerate(daily['time']):
        dt.date.fromisoformat(date)
        day = {'date': date}
        for field in FIELDS.split(','):
            values = daily.get(field, [])
            day[field] = values[i] if i < len(values) else None
        if not all(number(day[k]) for k in ('temperature_2m_max', 'temperature_2m_min', 'weather_code')):
            raise ValueError('Incomplete daily forecast')
        days.append(day)
    dates = [d['date'] for d in days]
    if dates != sorted(set(dates)):
        raise ValueError('Unordered or duplicate forecast days')
    if any(d['temperature_2m_max'] < d['temperature_2m_min'] for d in days):
        raise ValueError('Invalid temperature range')
    if len(days) < 6:
        raise ValueError('Incomplete six-day forecast')
    return {'timezone': str(zone), 'current': current, 'days': days, 'hours': hourly_rows(raw.get('hourly'))}

def moon(now, southern=False):
    # Mean synodic cycle: approximate phase, not an ephemeris.
    reference = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
    phase = ((now - reference).total_seconds() / 86400 / SYNODIC) % 1
    names = ['New moon', 'Waxing crescent', 'First quarter', 'Waxing gibbous', 'Full moon', 'Waning gibbous', 'Last quarter', 'Waning crescent']
    return {
        'phase': phase,
        'name': names[int(phase * 8 + .5) % 8],
        'illumination': round((1 - math.cos(2 * math.pi * phase)) * 50),
        'nextFull': math.ceil(((.5 - phase) % 1) * SYNODIC),
        'nextNew': math.ceil(((1 - phase) % 1) * SYNODIC),
        # The lit side is mirrored when seen from south of the equator.
        'southern': southern,
    }

def observed_weather(reports, cold=False):
    # Strongest precipitation a station reports, as (WMO code, wording), so
    # the display keeps speaking one vocabulary. (None, '') when it is dry.
    # cold: at or below freezing, where unidentified precipitation is drawn as snow.
    best = (-1, 0, None, '')
    for report in reports if isinstance(reports, list) else []:
        # "In the vicinity" is not falling on the station itself.
        if not isinstance(report, dict) or report.get('inVicinity'):
            continue
        kind, modifier = str(report.get('weather') or ''), str(report.get('modifier') or '')
        # Snow lifted off the ground by wind is not snow falling.
        if modifier in ('blowing', 'low_drifting'):
            continue
        step = {'light': 0, 'heavy': 2}.get(report.get('intensity'), 1)
        freezing = 'freezing' in (kind, modifier) or kind.startswith('freezing')
        if 'thunder' in kind:
            found = (5, 2, 95, 'Thunderstorms')
        elif kind == 'hail':
            found = (5, 1, 96, 'Hail')
        elif 'rain' in kind and freezing:
            found = (4, step, 67 if step else 66, 'freezing rain')
        elif kind == 'snow':
            found = (3, step, (86 if step == 2 else 85) if modifier == 'showers' else 71 + 2 * step, 'snow showers' if modifier == 'showers' else 'snow')
        elif kind in ('ice_pellets', 'snow_pellets', 'snow_grains'):
            found = (3, step, 77, 'sleet' if kind == 'ice_pellets' else kind.replace('_', ' '))
        elif 'rain' in kind:
            found = (2, step, (80 if modifier == 'showers' else 61 + step) + step, 'rain showers' if modifier == 'showers' else 'rain')
        elif 'drizzle' in kind:
            found = (1, step, (57 if step else 56) if freezing else 51 + 2 * step, 'freezing drizzle' if freezing else 'drizzle')
        elif kind == 'unknown':
            found = (0, step, (71 if cold else 61) + 2 * step, 'precipitation')
        else:
            continue
        if found[:2] > best[:2]:
            best = found
    rank, step, code, words = best
    if code is None:
        return None, ''
    if words[0].islower():
        words = ({0: 'light ', 2: 'heavy '}.get(step, '') + words).capitalize()
    return code, words

def observed(cache, now):
    # The stored station report, if it still describes the present.
    report = cache.get('observation')
    if not isinstance(report, dict) or not number(report.get('time')) or not number(report.get('code')) or not isinstance(report.get('text'), str):
        return None
    age = now.timestamp() - report['time']
    if not -300 <= age <= OBSERVATION_MAX_AGE:
        return None
    return {'code': report['code'], 'text': report['text'], 'station': str(report.get('name') or ''), 'ageMinutes': max(0, int(age / 60))}

def present(cache, error='', now=None, southern=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not cache:
        return {'available': False, 'error': error, 'moon': moon(now, southern)}
    result = dict(cache)
    local = now.astimezone(ZoneInfo(cache['timezone']))
    result['days'] = [d for d in cache['days'] if d['date'] >= local.date().isoformat()][:6]
    # The next twelve hours, starting with the one in progress.
    result['hours'] = [h for h in clean_hours(cache.get('hours')) if h['time'] >= local.strftime('%Y-%m-%dT%H:00')][:12]
    # Precipitation seen at a nearby station outranks the modeled sky, for
    # right now only: the forecast hours and days stay as modeled.
    result.pop('observation', None)
    seen = observed(cache, now)
    if seen:
        result['observed'] = seen
        result['current'] = {**cache['current'], 'weather_code': seen['code']}
        if result['hours'] and result['hours'][0]['time'] == local.strftime('%Y-%m-%dT%H:00'):
            result['hours'][0] = {**result['hours'][0], 'weather_code': seen['code']}
    result['today'] = next((d for d in result['days'] if d['date'] == local.date().isoformat()), None)
    age = max(0, now.timestamp() - cache['fetchedAt'])
    result.update(available=True, stale=bool(error) or age > 1800, ageMinutes=int(age / 60), error=error, localDate=local.date().isoformat(), localTime=local.strftime('%H:%M'), moon=moon(now, southern))
    return result

def emit(report):
    print(json.dumps(report, allow_nan=False), flush=True)

def read_location():
    loc = json.loads(LOCATION.read_text())
    # Two decimals (about 1 km) is finer than the forecast grid, and keeps
    # the exact address out of the request.
    lat, lon = round(float(loc['latitude']), 2), round(float(loc['longitude']), 2)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Invalid location coordinates')
    return str(loc.get('name') or 'Local weather'), lat, lon

def load_cache(path, key, name):
    try:
        saved = json.loads(path.read_text())
        if not isinstance(saved, dict) or saved.get('locationKey') != key:
            return None
        normalize({'timezone': saved['timezone'], 'current': saved['current'], 'daily': {'time': [d['date'] for d in saved['days']], **{k: [d.get(k) for d in saved['days']] for k in FIELDS.split(',')}}})
        if not number(saved.get('fetchedAt')):
            return None
        saved['location'] = name
        return saved
    except (OSError, ValueError, KeyError, TypeError):
        return None

def load_retry(path):
    try:
        retry = json.loads(path.read_text())
        if isinstance(retry, dict) and number(retry.get('after', 0)) and number(retry.get('failures', 0)):
            return retry
    except (OSError, ValueError):
        pass
    return {}

def get_json(url, timeout=12):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/geo+json, application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(1048577)
    if len(data) > 1048576:
        raise ValueError('Response too large')
    return json.loads(data)

def fetch(lat, lon):
    params = dict(latitude=lat, longitude=lon, timezone='auto', forecast_days=7, daily=FIELDS, hourly=HOURLY, current=CURRENT)
    return normalize(get_json('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(params)))

def distance(lat, lon, other_lat, other_lon):
    # Great-circle distance in km.
    a, b = math.radians(lat), math.radians(other_lat)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(other_lon - lon) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))

def station_name(name):
    # "Lorain / Elyria, Lorain County Regional Airport" reads better without the town.
    return str(name or '').rsplit(', ', 1)[-1][:60]

def nearby_stations(lat, lon):
    # The two closest NWS stations, looked up once per location and kept for
    # a month. NWS only covers the US: anywhere else it answers 404, and the
    # empty list is remembered just the same.
    key, path = [lat, lon], STATE / 'stations.json'
    try:
        saved = json.loads(path.read_text())
        if saved['key'] == key and 0 <= time.time() - saved['at'] < 2592000 and isinstance(saved['stations'], list):
            return saved['stations']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    found = []
    try:
        features = get_json('%s/points/%s,%s/stations' % (NWS, lat, lon), 8)['features']
    except urllib.error.HTTPError as error:
        # Only "no data for this point" means outside coverage; any other
        # failure is passing trouble, and is not remembered.
        if error.code != 404 or 'InvalidPoint' not in str(json.loads(error.read(65536)).get('type')):
            raise
        features = []
    for feature in features:
        # One odd entry must not cost the rest of the list.
        try:
            station, (east, north) = feature['properties'], feature['geometry']['coordinates'][:2]
            away = distance(lat, lon, north, east)
            if str(station['stationIdentifier']).isalnum() and away <= STATION_RANGE:
                found.append((away, {'id': str(station['stationIdentifier']), 'name': station_name(station.get('name'))}))
        except (ValueError, KeyError, TypeError):
            continue
    if features and not found and not any(isinstance(f, dict) and isinstance(f.get('geometry'), dict) for f in features):
        raise ValueError('Unreadable station list')
    found = [station for _, station in sorted(found, key=lambda pair: pair[0])[:2]]
    try:
        path.write_text(json.dumps({'key': key, 'at': time.time(), 'stations': found}))
    except OSError:
        pass
    return found

def observe(lat, lon, previous=None):
    # What the nearest station with a recent report is seeing. A bonus on top
    # of the forecast, so this never raises; when nothing newer can be had,
    # the previous report stays and simply ages out.
    checked = {'checkedAt': time.time()}
    try:
        for station in nearby_stations(lat, lon):
            try:
                # The list is served fresher than .../observations/latest.
                report = get_json('%s/stations/%s/observations?limit=1' % (NWS, station['id']), 8)['features'][0]['properties']
                when = dt.datetime.fromisoformat(report['timestamp']).timestamp()
                air = (report.get('temperature') or {}).get('value')
            except OBSERVE_ERRORS:
                continue
            # A report from the future is a broken clock, not news.
            if not -300 <= time.time() - when <= OBSERVATION_MAX_AGE:
                continue
            code, text = observed_weather(report.get('presentWeather'), number(air) and air <= 0)
            return {**checked, 'station': station['id'], 'name': station['name'], 'time': when, 'code': code, 'text': text}
    except OBSERVE_ERRORS:
        pass
    return {**(previous if isinstance(previous, dict) else {}), **checked}

def observation_due(cache):
    report = cache.get('observation')
    return not isinstance(report, dict) or not number(report.get('checkedAt')) or not 0 <= time.time() - report['checkedAt'] < OBSERVATION_INTERVAL

def save(path, cache):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(cache, allow_nan=False))
    os.replace(temp, path)

def look_outside(path, cache, shown, lat, lon, southern):
    # Runs only after the forecast is saved and on screen, so a slow NWS can
    # never hold it up; a second report goes out only if the sky changed.
    cache['observation'] = observe(lat, lon, cache.get('observation'))
    try:
        save(path, cache)
    except OSError:
        pass
    status = present(cache, southern=southern)
    if any(status.get(k) != shown.get(k) for k in ('observed', 'current', 'hours')):
        emit(status)

def update(force, name, lat, lon):
    key, southern = [lat, lon], lat < 0
    path, retry_path = STATE / 'forecast.json', STATE / 'retry.json'
    cache = load_cache(path, key, name)
    status = present(cache, southern=southern)
    current = cache and not force and time.time() - cache['fetchedAt'] < 900 and status['today']
    if current and not observation_due(cache):
        emit(status); return
    if cache:
        emit(status)
    if current:
        # The forecast is still fresh; only the sky needs another look.
        look_outside(path, cache, status, lat, lon, southern); return
    # Retry backoff persists across popup opens and shell restarts.
    retry = load_retry(retry_path)
    if not force and retry.get('key') == key and retry.get('after', 0) > time.time():
        emit(present(cache, 'Offline · retrying shortly', southern=southern)); return
    try:
        fresh = fetch(lat, lon)
    except FETCH_ERRORS:
        failures = retry.get('failures', 0) + 1 if retry.get('key') == key else 1
        try:
            retry_path.write_text(json.dumps({'key': key, 'failures': failures, 'after': time.time() + min(900, 30 * 2 ** min(failures - 1, 5))}))
        except OSError:
            pass  # No backoff without a writable state directory; the report below still goes out.
        emit(present(cache, 'Weather service unavailable · saved forecast' if cache else 'Weather service unavailable · retrying', southern=southern)); return
    fresh.update(fetchedAt=time.time(), locationKey=key, location=name, observation=cache.get('observation') if cache else None)
    try:
        save(path, fresh)
        retry_path.unlink(missing_ok=True)
    except OSError:
        emit(present(fresh, 'Could not save forecast in ~/.local/state/neil-weather', southern=southern)); return
    status = present(fresh, southern=southern)
    emit(status)
    look_outside(path, fresh, status, lat, lon, southern)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        name, lat, lon = read_location()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        emit(present(None, 'No weather location set · run: omarchy weather location --set "Your city" latitude,longitude')); return
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / 'lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            update(args.force, name, lat, lon)
    except OSError:
        emit(present(None, 'Cannot use the weather cache in ~/.local/state/neil-weather', southern=lat < 0))

if __name__ == '__main__':
    main()
