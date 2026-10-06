#!/usr/bin/env python3
"""Dependency-free Open-Meteo client. SI cache, atomic writes, bounded requests."""
import argparse, datetime as dt, fcntl, json, math, os, pathlib, time
import urllib.parse, urllib.request
from zoneinfo import ZoneInfo
HOME = pathlib.Path.home()
STATE = HOME / '.local/state/neil-weather'
LOCATION = HOME / '.local/state/omarchy/settings/weather.json'
FIELDS = 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,daylight_duration,uv_index_max'

def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

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
    return {'timezone': str(zone), 'current': current, 'days': days}

def moon(now):
    # Mean synodic cycle: approximate phase, not an ephemeris.
    reference = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
    phase = ((now - reference).total_seconds() / 86400 / 29.530588853) % 1
    names = ['New moon', 'Waxing crescent', 'First quarter', 'Waxing gibbous', 'Full moon', 'Waning gibbous', 'Last quarter', 'Waning crescent']
    return {'phase': phase, 'name': names[int(phase * 8 + .5) % 8], 'illumination': round((1 - math.cos(2 * math.pi * phase)) * 50), 'nextFull': math.ceil(((.5 - phase) % 1) * 29.530588853), 'nextNew': math.ceil(((1 - phase) % 1) * 29.530588853)}

def present(cache, error='', now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not cache:
        return {'available': False, 'error': error, 'moon': moon(now)}
    result = dict(cache)
    local = now.astimezone(ZoneInfo(cache['timezone']))
    result['days'] = [d for d in cache['days'] if d['date'] >= local.date().isoformat()][:6]
    result['today'] = next((d for d in result['days'] if d['date'] == local.date().isoformat()), None)
    age = max(0, now.timestamp() - cache['fetchedAt'])
    result.update(available=True, stale=bool(error) or age > 1800, ageMinutes=int(age / 60), error=error, localDate=local.date().isoformat(), localTime=local.strftime('%H:%M'), moon=moon(now))
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = None
        try:
            loc = json.loads(LOCATION.read_text())
            lat, lon = float(loc['latitude']), float(loc['longitude'])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError('Invalid location coordinates')
            key = [lat, lon]
            path = STATE / 'forecast.json'
            try:
                saved = json.loads(path.read_text())
                if isinstance(saved, dict) and saved.get('locationKey') == key:
                    normalize({'timezone': saved['timezone'], 'current': saved['current'], 'daily': {'time': [d['date'] for d in saved['days']], **{k: [d.get(k) for d in saved['days']] for k in FIELDS.split(',')}}})
                    ZoneInfo(saved['timezone'])
                    if isinstance(saved.get('days'), list) and number(saved.get('fetchedAt')):
                        cache = saved
                        cache['location'] = loc.get('name', 'Local weather')
            except (OSError, ValueError, KeyError, TypeError):
                pass
            status = present(cache)
            if cache and not args.force and time.time() - cache['fetchedAt'] < 900 and status['today']:
                print(json.dumps(status, allow_nan=False)); return
            if cache:
                print(json.dumps(status, allow_nan=False), flush=True)
            # Retry backoff persists across popup opens and shell restarts.
            retry_path = STATE / 'retry.json'
            try:
                retry = json.loads(retry_path.read_text())
                if not isinstance(retry, dict) or not number(retry.get('after', 0)) or not number(retry.get('failures', 0)):
                    retry = {}
            except (OSError, ValueError):
                retry = {}
            if not args.force and retry.get('key') == key and retry.get('after', 0) > time.time():
                print(json.dumps(present(cache, 'Offline · retrying shortly'), allow_nan=False)); return
            params = dict(latitude=lat, longitude=lon, timezone='auto', forecast_days=7, daily=FIELDS, current='temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day')
            url = 'https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(params)
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'neil.weather/1.0'})
                with urllib.request.urlopen(request, timeout=12) as response:
                    data = response.read(1048577)
                if len(data) > 1048576:
                    raise ValueError('Response too large')
                fresh = normalize(json.loads(data))
                fresh.update(fetchedAt=time.time(), locationKey=key, location=loc.get('name', 'Local weather'))
                temp = path.with_suffix('.tmp')
                temp.write_text(json.dumps(fresh, allow_nan=False))
                os.replace(temp, path)
                retry_path.unlink(missing_ok=True)
                cache = fresh
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failures = retry.get('failures', 0) + 1 if retry.get('key') == key else 1
                retry_path.write_text(json.dumps({'key': key, 'failures': failures, 'after': time.time() + min(900, 30 * 2 ** min(failures - 1, 5))}))
                print(json.dumps(present(cache, 'Weather service unavailable · saved forecast' if cache else 'Weather service unavailable · retrying'), allow_nan=False)); return
            print(json.dumps(present(cache), allow_nan=False))
        except (OSError, ValueError, KeyError, TypeError):
            print(json.dumps({'available': False, 'error': 'Set your weather location in Omarchy settings', 'moon': moon(dt.datetime.now(dt.timezone.utc))}))

if __name__ == '__main__':
    main()
