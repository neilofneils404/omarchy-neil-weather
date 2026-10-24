#!/usr/bin/env python3
"""Dependency-free Open-Meteo client, with US station observations and alerts from the NWS. SI cache, atomic writes, bounded requests."""
import argparse, datetime as dt, fcntl, http.client, json, math, os, pathlib, subprocess, time
import urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
HOME = pathlib.Path.home()
STATE = HOME / '.local/state/neil-weather'
LOCATION = HOME / '.local/state/omarchy/settings/weather.json'
FIELDS = 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum,sunrise,sunset,daylight_duration,uv_index_max,apparent_temperature_max,apparent_temperature_min'
CURRENT = 'temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code,is_day'
HOURLY = 'temperature_2m,precipitation_probability,precipitation,weather_code,is_day'
AIR = 'us_aqi,european_aqi,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen'
SYNODIC = 29.530588853
NWS = 'https://api.weather.gov'
USER_AGENT = 'neil.weather/1.4 (https://github.com/neilofneils404/omarchy-neil-weather)'
# A station report stands in for the modeled sky only while it is this recent
# (seconds), and only from a station this close (km).
OBSERVATION_MAX_AGE, OBSERVATION_INTERVAL, STATION_RANGE = 2700, 300, 40
# Alerts are asked for more often than the sky is looked at: a warning can be
# issued minutes before the storm. Air quality is modeled hourly. Seconds.
ALERT_INTERVAL, AIR_INTERVAL, AIR_MAX_AGE, OUTSIDE_RECHECK = 120, 3600, 10800, 2592000
# Rain a 15-minute slot must hold (mm) to count as wet: the smallest amount
# Open-Meteo reports.
WET = .1
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

def clean_minutes(rows):
    # Fifteen-minute rain, each slot the total of the quarter hour ending at
    # its time. Optional like the hours: a bad slot is dropped.
    slots = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get('time'), str) or not number(row.get('precipitation')):
            continue
        try:
            dt.datetime.fromisoformat(row['time'])
        except ValueError:
            continue
        slots.append({'time': row['time'], 'precipitation': row['precipitation']})
    return slots

def minutely_rows(minutely):
    if not isinstance(minutely, dict) or not isinstance(minutely.get('time'), list) or not isinstance(minutely.get('precipitation'), list):
        return []
    rain = minutely['precipitation']
    return clean_minutes([{'time': time, 'precipitation': rain[i] if i < len(rain) else None} for i, time in enumerate(minutely['time'])])

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
    return {'timezone': str(zone), 'current': current, 'days': days, 'hours': hourly_rows(raw.get('hourly')), 'minutely': minutely_rows(raw.get('minutely_15'))}

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

def is_snow(code):
    return number(code) and (71 <= code <= 77 or code in (85, 86))

def day_hours(hours, dates):
    # Later days in the same twelve cells as the next twelve hours: every
    # other hour, each cell speaking for both. Grouping by clock hour keeps
    # daylight-saving days, with 23 or 25 hours, in step.
    out = {}
    for date in dates:
        pairs = {}
        for hour in hours:
            if hour['time'][:10] == date:
                pairs.setdefault(int(hour['time'][11:13]) // 2, []).append(hour)
        cells = []
        for _, pair in sorted(pairs.items()):
            chances = [h['precipitation_probability'] for h in pair if number(h.get('precipitation_probability'))]
            amounts = [h['precipitation'] for h in pair if number(h.get('precipitation'))]
            cells.append({
                'time': pair[0]['time'], 'temperature_2m': pair[0]['temperature_2m'],
                # The wetter, stormier hour describes the pair.
                'weather_code': max(h['weather_code'] for h in pair),
                'is_day': max((h['is_day'] for h in pair if number(h.get('is_day'))), default=None),
                'precipitation_probability': max(chances) if chances else None,
                'precipitation': round(sum(amounts), 1) if amounts else None,
            })
        if cells:
            out[date] = cells
    return out

def nowcast(cache, local, seen):
    # When the rain starts or stops, from the fifteen-minute forecast:
    # {'state': 'starting' | 'easing' | 'continuing', 'at': local time,
    # 'minutes': from now, 'kind': 'rain' | 'snow'}, or None when the next
    # few hours look dry (or the forecast is too old to say).
    clock = local.replace(tzinfo=None)
    slots = [s for s in clean_minutes(cache.get('minutely')) if dt.datetime.fromisoformat(s['time']) > clock]
    if len(slots) < 2:
        return None
    wet = [s['precipitation'] >= WET for s in slots]
    def begins(i):
        return dt.datetime.fromisoformat(slots[i]['time']) - dt.timedelta(minutes=15)
    if wet[0]:
        # One dry quarter hour is a lull, not the end.
        end = next((i for i in range(1, len(slots)) if not wet[i] and (i + 1 == len(slots) or not wet[i + 1])), None)
        state, at = ('easing', begins(end)) if end else ('continuing', dt.datetime.fromisoformat(slots[-1]['time']))
        code = (seen or {}).get('code', (cache.get('current') or {}).get('weather_code'))
    elif seen:
        # A station sees rain the model does not: it cannot say when it ends.
        return None
    else:
        start = next((i for i in range(1, len(slots)) if wet[i]), None)
        if start is None:
            return None
        state, at = 'starting', begins(start)
        hour = next((h for h in clean_hours(cache.get('hours')) if h['time'] == at.strftime('%Y-%m-%dT%H:00')), {})
        code = hour.get('weather_code')
        if not is_snow(code) and number(hour.get('temperature_2m')) and hour['temperature_2m'] <= 0:
            code = 71
    return {'state': state, 'at': at.strftime('%Y-%m-%dT%H:%M'), 'minutes': max(0, int((at - clock).total_seconds() // 60)), 'kind': 'snow' if is_snow(code) else 'rain'}

def instant(text):
    # NWS writes offsets; an older Python cannot read a trailing Z.
    stamp = dt.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Time without an offset')
    return stamp

def active_alerts(cache, now, zone):
    # Saved alerts that have not expired, with the time each runs until in
    # the location's own clock. Survives a failed check: an alert is dropped
    # only when NWS says it is over or it expires.
    report = cache.get('alerts')
    out = []
    for alert in report.get('items', []) if isinstance(report, dict) and isinstance(report.get('items'), list) else []:
        try:
            if alert.get('expires') and instant(alert['expires']) <= now:
                continue
            ends = alert.get('ends') or alert.get('expires')
            until = instant(ends).astimezone(zone).strftime('%Y-%m-%dT%H:%M') if ends else ''
            out.append({**{k: v for k, v in alert.items() if k not in ('expires', 'ends')}, 'until': until})
        except (AttributeError, TypeError, ValueError):
            continue
    return out

def fresh_air(cache, now):
    air = cache.get('air')
    if not isinstance(air, dict) or not number(air.get('time')) or not 0 <= now.timestamp() - air['time'] <= AIR_MAX_AGE:
        return None
    pollen = {k[:-len('_pollen')]: air[k] for k in AIR.split(',') if k.endswith('_pollen') and number(air.get(k))}
    return {'us_aqi': air.get('us_aqi'), 'european_aqi': air.get('european_aqi'), 'pollen': pollen}

def present(cache, error='', now=None, southern=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not cache:
        return {'available': False, 'error': error, 'moon': moon(now, southern)}
    result = dict(cache)
    zone = ZoneInfo(cache['timezone'])
    local = now.astimezone(zone)
    today = local.date().isoformat()
    result['days'] = [d for d in cache['days'] if d['date'] >= today][:6]
    # Yesterday, kept by the forecast for comparison with today.
    result['yesterday'] = next((d for d in cache['days'] if d['date'] == (local.date() - dt.timedelta(days=1)).isoformat()), None)
    # The next twelve hours, starting with the one in progress, and every
    # other hour of each later day for when one of them is selected.
    hours = clean_hours(cache.get('hours'))
    result['hours'] = [h for h in hours if h['time'] >= local.strftime('%Y-%m-%dT%H:00')][:12]
    result['dayHours'] = day_hours(hours, [d['date'] for d in result['days'] if d['date'] != today])
    # Precipitation seen at a nearby station outranks the modeled sky, for
    # right now only: the forecast hours and days stay as modeled.
    for internal in ('observation', 'minutely'):
        result.pop(internal, None)
    seen = observed(cache, now)
    if seen:
        result['observed'] = seen
        result['current'] = {**cache['current'], 'weather_code': seen['code']}
        if result['hours'] and result['hours'][0]['time'] == local.strftime('%Y-%m-%dT%H:00'):
            result['hours'][0] = {**result['hours'][0], 'weather_code': seen['code']}
    result['nowcast'] = nowcast(cache, local, seen)
    result['alerts'] = active_alerts(cache, now, zone)
    result['air'] = fresh_air(cache, now)
    result['today'] = next((d for d in result['days'] if d['date'] == today), None)
    age = max(0, now.timestamp() - cache['fetchedAt'])
    result.update(available=True, stale=bool(error) or age > 1800, ageMinutes=int(age / 60), error=error, localDate=local.date().isoformat(), localTime=local.strftime('%H:%M'), moon=moon(now, southern))
    return result

def emit(report):
    print(json.dumps(report, allow_nan=False), flush=True)
    return report

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
    # One past day, for "warmer than yesterday"; four hours of quarter-hour
    # rain, for when it starts or stops.
    params = dict(latitude=lat, longitude=lon, timezone='auto', forecast_days=7, past_days=1, daily=FIELDS, hourly=HOURLY, current=CURRENT,
                  minutely_15='precipitation', forecast_minutely_15=16, past_minutely_15=0)
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

SEVERITY_RANK = {'Extreme': 4, 'Severe': 3, 'Moderate': 2, 'Minor': 1}
URGENCY_RANK = {'Immediate': 3, 'Expected': 2, 'Future': 1}
# Follow-ups and life-safety products that act as warnings whatever their name.
WARNING_PRODUCTS = ('Flash Flood Statement', 'Flood Statement', 'Severe Weather Statement', 'Evacuation Immediate', 'Civil Emergency Message')

def alert_class(event):
    if event in WARNING_PRODUCTS or event.endswith(('Warning', 'Emergency')):
        return 'warning'
    return 'watch' if event.endswith('Watch') else 'advisory'

def unwrap(text, limit):
    # NWS hard-wraps its text at 69 columns; keep only the paragraph breaks.
    paragraphs = [' '.join(p.split()) for p in str(text or '').split('\n\n')]
    text = '\n'.join(p for p in paragraphs if p)
    return text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0] + '…'

def read_alert(feature):
    properties = feature['properties']
    event = str(properties.get('event') or '').strip()
    # Tests, exercises, and cancellations are not weather.
    if not event or properties.get('status', 'Actual') != 'Actual' or properties.get('messageType') == 'Cancel':
        return None
    for stamp in ('expires', 'ends'):
        if properties.get(stamp):
            instant(properties[stamp])
    return {
        'id': str(properties.get('id') or feature.get('id') or event + '|' + str(properties.get('sent'))),
        'event': event, 'tier': alert_class(event),
        'headline': str(properties.get('headline') or event)[:300],
        'rank': SEVERITY_RANK.get(properties.get('severity'), 0), 'urgency': URGENCY_RANK.get(properties.get('urgency'), 0),
        'expires': str(properties.get('expires') or ''), 'ends': str(properties.get('ends') or ''),
        'description': unwrap(properties.get('description'), 900), 'instruction': unwrap(properties.get('instruction'), 500),
        'sender': str(properties.get('senderName') or '')[:80],
        'references': [str(r.get('identifier')) for r in properties.get('references') or [] if isinstance(r, dict) and r.get('identifier')],
    }

def fetch_alerts(lat, lon):
    # Active alerts for the point, most dangerous first. None outside NWS
    # coverage. One unreadable alert is skipped, not allowed to hide the rest.
    try:
        features = get_json('%s/alerts/active?point=%s,%s' % (NWS, lat, lon), 8)['features']
    except urllib.error.HTTPError as error:
        if error.code == 400 and 'out of bounds' in str(json.loads(error.read(65536)).get('detail')):
            return None
        raise
    alerts, unreadable = [], 0
    for feature in features:
        try:
            alert = read_alert(feature)
        except (AttributeError, KeyError, TypeError, ValueError):
            unreadable += 1
            continue
        if alert:
            alerts.append(alert)
    if unreadable and not alerts:
        raise ValueError('Unreadable alerts')
    rank = {'warning': 2, 'watch': 1, 'advisory': 0}
    alerts.sort(key=lambda a: (-rank[a['tier']], -a['rank'], -a['urgency'], a['expires'], a['event']))
    return alerts[:8]

def check_alerts(lat, lon, previous):
    # A failed check keeps what was known; the alerts expire on their own.
    checked = {'checkedAt': time.time()}
    try:
        alerts = fetch_alerts(lat, lon)
    except OBSERVE_ERRORS:
        return {**(previous if isinstance(previous, dict) else {}), **checked}
    return {**checked, 'outside': alerts is None, 'items': alerts or []}

def alerts_due(cache):
    report = cache.get('alerts')
    if not isinstance(report, dict) or not number(report.get('checkedAt')):
        return True
    # Outside the US there is nothing to ask NWS for; look again monthly.
    return not 0 <= time.time() - report['checkedAt'] < (OUTSIDE_RECHECK if report.get('outside') else ALERT_INTERVAL)

def check_air(lat, lon, previous):
    checked = {'checkedAt': time.time()}
    try:
        current = get_json('https://air-quality-api.open-meteo.com/v1/air-quality?' + urllib.parse.urlencode(dict(latitude=lat, longitude=lon, current=AIR)), 8)['current']
        reading = {k: current[k] for k in AIR.split(',') if number(current.get(k))}
        if not number(reading.get('us_aqi')) and not number(reading.get('european_aqi')):
            raise ValueError('No air quality index')
    except OBSERVE_ERRORS:
        return {**(previous if isinstance(previous, dict) else {}), **checked}
    return {**checked, 'time': checked['checkedAt'], **reading}

def air_due(cache):
    air = cache.get('air')
    return not isinstance(air, dict) or not number(air.get('checkedAt')) or not 0 <= time.time() - air['checkedAt'] < AIR_INTERVAL

def save(path, cache):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(cache, allow_nan=False))
    os.replace(temp, path)

def outside_due(cache):
    return observation_due(cache) or alerts_due(cache) or air_due(cache)

def look_outside(path, cache, shown, lat, lon, southern, force=False):
    # Runs only after the forecast is saved and on screen, so a slow NWS can
    # never hold it up; a second report goes out only if something changed.
    if force or observation_due(cache):
        cache['observation'] = observe(lat, lon, cache.get('observation'))
    if alerts_due(cache) or (force and not (cache.get('alerts') or {}).get('outside')):
        cache['alerts'] = check_alerts(lat, lon, cache.get('alerts'))
    if air_due(cache):
        cache['air'] = check_air(lat, lon, cache.get('air'))
    try:
        save(path, cache)
    except OSError:
        pass
    status = present(cache, southern=southern)
    if any(status.get(k) != shown.get(k) for k in ('observed', 'current', 'hours', 'nowcast', 'alerts', 'air')):
        emit(status)
    return status

def update(force, name, lat, lon):
    # Returns the last report shown.
    key, southern = [lat, lon], lat < 0
    path, retry_path = STATE / 'forecast.json', STATE / 'retry.json'
    cache = load_cache(path, key, name)
    status = present(cache, southern=southern)
    current = cache and not force and time.time() - cache['fetchedAt'] < 900 and status['today']
    if current and not outside_due(cache):
        return emit(status)
    if cache:
        emit(status)
    if current:
        # The forecast is still fresh; only the sky, alerts, and air need another look.
        return look_outside(path, cache, status, lat, lon, southern)
    # Retry backoff persists across popup opens and shell restarts.
    retry = load_retry(retry_path)
    if not force and retry.get('key') == key and retry.get('after', 0) > time.time():
        return emit(present(cache, 'Offline · retrying shortly', southern=southern))
    try:
        fresh = fetch(lat, lon)
    except FETCH_ERRORS:
        failures = retry.get('failures', 0) + 1 if retry.get('key') == key else 1
        try:
            retry_path.write_text(json.dumps({'key': key, 'failures': failures, 'after': time.time() + min(900, 30 * 2 ** min(failures - 1, 5))}))
        except OSError:
            pass  # No backoff without a writable state directory; the report below still goes out.
        return emit(present(cache, 'Weather service unavailable · saved forecast' if cache else 'Weather service unavailable · retrying', southern=southern))
    fresh.update(fetchedAt=time.time(), locationKey=key, location=name, **{k: cache.get(k) if cache else None for k in ('observation', 'alerts', 'air')})
    try:
        save(path, fresh)
        retry_path.unlink(missing_ok=True)
    except OSError:
        return emit(present(fresh, 'Could not save forecast in ~/.local/state/neil-weather', southern=southern))
    status = present(fresh, southern=southern)
    emit(status)
    return look_outside(path, fresh, status, lat, lon, southern, force=True)

# Nerd Font glyphs for notifications, as the bar draws them.
ALERT_GLYPH, RAIN_GLYPH = '\U000f0026', '\ue318'

def notify(glyph, headline, description, urgency='normal'):
    # Fire and forget: a missing notifier never costs the forecast. Clicking
    # the notification opens the panel.
    try:
        subprocess.Popen(['omarchy-notification-send', '--app-name', 'Weather', '-u', urgency, '-g', glyph,
                          headline, description, '--exec', 'omarchy-shell', 'shell', 'summon', 'neil.weather', '{}'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass

def worth_announcing(alert, seen, first):
    if alert['id'] in seen:
        return False
    # An update to an alert already announced stays quiet unless it is a
    # different event (a watch raised to a warning) or more severe or urgent.
    for ref in alert.get('references', []):
        prior = seen.get(ref)
        if isinstance(prior, dict) and prior.get('event') == alert['event'] and alert['rank'] <= prior.get('rank', 4) and alert['urgency'] <= prior.get('urgency', 3):
            return False
    # The first check after notifications are switched on interrupts only for
    # a severe warning that needs action now.
    if first:
        return alert['tier'] == 'warning' and alert['rank'] >= 3 and alert['urgency'] >= 3
    return alert['tier'] in ('warning', 'watch') or alert['rank'] >= 3

def announce(status, mode):
    # Desktop notifications: mode is 'off', 'alerts', or 'all' (alerts and
    # rain starting soon). Alerts are remembered even while notifications are
    # off, so switching them on does not replay everything already active.
    if not status or not status.get('available') or status.get('stale'):
        return
    path = STATE / 'notices.json'
    try:
        notices = json.loads(path.read_text())
        seen, first = notices['alerts'], False
        if not isinstance(seen, dict):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError):
        notices, seen, first = {}, {}, True
    first = first or notices.get('mode', 'off') == 'off'
    now = time.time()
    alerts = status.get('alerts') or []
    for alert in alerts:
        if mode != 'off' and worth_announcing(alert, seen, first):
            notify(ALERT_GLYPH, alert['event'], alert['headline'], 'critical' if alert['tier'] == 'warning' and alert['rank'] >= 3 else 'normal')
    active = {a['id'] for a in alerts}
    kept = {k: v for k, v in seen.items() if k in active or (isinstance(v, dict) and number(v.get('at')) and now - v['at'] < 172800)}
    kept.update({a['id']: {'at': now, 'event': a['event'], 'rank': a['rank'], 'urgency': a['urgency']} for a in alerts if a['id'] not in seen})
    rain = notices.get('rain', 0) if number(notices.get('rain', 0)) else 0
    soon = status.get('nowcast') or {}
    if mode == 'all' and soon.get('state') == 'starting' and soon.get('minutes', 99) <= 30 and now - rain > 7200:
        rain = now
        minutes = max(5, int(round(soon['minutes'] / 5.0)) * 5)
        notify(RAIN_GLYPH, '%s starting in about %d minutes' % (soon['kind'].capitalize(), minutes), status.get('location') or 'Local weather')
    record = {'alerts': kept, 'rain': rain, 'mode': mode}
    if record != notices:
        try:
            save(path, record)
        except OSError:
            pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--notify', choices=('off', 'alerts', 'all'), default='off')
    args = parser.parse_args()
    try:
        name, lat, lon = read_location()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        emit(present(None, 'No weather location set · run: omarchy weather location --set "Your city" latitude,longitude')); return
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / 'lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            announce(update(args.force, name, lat, lon), args.notify)
    except OSError:
        emit(present(None, 'Cannot use the weather cache in ~/.local/state/neil-weather', southern=lat < 0))

if __name__ == '__main__':
    main()
