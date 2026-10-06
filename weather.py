#!/usr/bin/env python3
"""Dependency-free Open-Meteo client. SI cache, atomic writes, bounded requests."""
import argparse, datetime as dt, fcntl, http.client, json, math, os, pathlib, time
import urllib.parse, urllib.request
from zoneinfo import ZoneInfo
HOME = pathlib.Path.home()
STATE = HOME / '.local/state/neil-weather'
LOCATION = HOME / '.local/state/omarchy/settings/weather.json'
FIELDS = 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,daylight_duration,uv_index_max,apparent_temperature_max,apparent_temperature_min'
CURRENT = 'temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code,is_day'
HOURLY = 'temperature_2m,precipitation_probability,weather_code,is_day'
SYNODIC = 29.530588853
FETCH_ERRORS = (OSError, ValueError, KeyError, TypeError, http.client.HTTPException)

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

def present(cache, error='', now=None, southern=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not cache:
        return {'available': False, 'error': error, 'moon': moon(now, southern)}
    result = dict(cache)
    local = now.astimezone(ZoneInfo(cache['timezone']))
    result['days'] = [d for d in cache['days'] if d['date'] >= local.date().isoformat()][:6]
    # The next twelve hours, starting with the one in progress.
    result['hours'] = [h for h in clean_hours(cache.get('hours')) if h['time'] >= local.strftime('%Y-%m-%dT%H:00')][:12]
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

def fetch(lat, lon):
    params = dict(latitude=lat, longitude=lon, timezone='auto', forecast_days=7, daily=FIELDS, hourly=HOURLY, current=CURRENT)
    url = 'https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': 'neil.weather/1.2'})
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read(1048577)
    if len(data) > 1048576:
        raise ValueError('Response too large')
    return normalize(json.loads(data))

def update(force, name, lat, lon):
    key, southern = [lat, lon], lat < 0
    path, retry_path = STATE / 'forecast.json', STATE / 'retry.json'
    cache = load_cache(path, key, name)
    status = present(cache, southern=southern)
    if cache and not force and time.time() - cache['fetchedAt'] < 900 and status['today']:
        emit(status); return
    if cache:
        emit(status)
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
    fresh.update(fetchedAt=time.time(), locationKey=key, location=name)
    try:
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(fresh, allow_nan=False))
        os.replace(temp, path)
        retry_path.unlink(missing_ok=True)
    except OSError:
        emit(present(fresh, 'Could not save forecast in ~/.local/state/neil-weather', southern=southern)); return
    emit(present(fresh, southern=southern))

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
