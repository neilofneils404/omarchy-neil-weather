// Run with: node --test tests/model.test.js
const test = require('node:test')
const assert = require('node:assert/strict')
const m = require('../Model.js')

const METRIC = 0, US = 1, UK = 2

test('auto units follow the locale measurement system', () => {
  assert.equal(m.usesFahrenheit('auto', US), true)
  assert.equal(m.usesFahrenheit('auto', UK), false)
  assert.equal(m.usesFahrenheit('auto', METRIC), false)
  assert.equal(m.usesFahrenheit(undefined, US), true)
  assert.equal(m.windUnit('auto', 'auto', US), 'mph')
  assert.equal(m.windUnit('auto', 'auto', UK), 'mph')
  assert.equal(m.windUnit('auto', 'auto', METRIC), 'km/h')
})

test('explicit unit settings override the locale', () => {
  assert.equal(m.usesFahrenheit(' Imperial ', METRIC), true)
  assert.equal(m.usesFahrenheit('metric', US), false)
  assert.equal(m.windUnit('auto', 'imperial', METRIC), 'mph')
  assert.equal(m.windUnit('auto', 'metric', US), 'km/h')
})

test('an explicit wind unit wins over everything else', () => {
  assert.equal(m.windUnit('m/s', 'imperial', US), 'm/s')
  assert.equal(m.windUnit('KM/H', 'imperial', US), 'km/h')
  assert.equal(m.windUnit('nonsense', 'metric', US), 'km/h')
})

test('temperatures and wind convert from Celsius and km/h', () => {
  assert.equal(m.temp(20, true), '68°')
  assert.equal(m.temp(20, false), '20°')
  assert.equal(m.temp(-0.4, false), '0°')
  for (const missing of [null, undefined, NaN, true]) assert.equal(m.temp(missing, true), '—')
  assert.equal(m.speed(36, 'mph'), '22 mph')
  assert.equal(m.speed(36, 'km/h'), '36 km/h')
  assert.equal(m.speed(36, 'm/s'), '10 m/s')
  assert.equal(m.speed(null, 'mph'), '—')
})

test('clock format is read from the locale pattern', () => {
  assert.equal(m.usesTwelveHourClock('h:mm AP'), true)
  assert.equal(m.usesTwelveHourClock('h:mm Ap'), true)
  assert.equal(m.usesTwelveHourClock('HH:mm'), false)
  assert.equal(m.usesTwelveHourClock("H 'a las' mm"), false)
})

test('clock and hour labels in both formats', () => {
  assert.equal(m.clock('2026-10-06T07:30', true), '7:30 AM')
  assert.equal(m.clock('2026-10-06T19:01', true), '7:01 PM')
  assert.equal(m.clock('2026-10-06T00:05', true), '12:05 AM')
  assert.equal(m.clock('2026-10-06T12:00', true), '12:00 PM')
  assert.equal(m.clock('2026-10-06T07:30', false), '07:30')
  assert.equal(m.clock('2026-10-06T19:01', false), '19:01')
  assert.equal(m.clock(null, true), '—')
  assert.equal(m.clock('garbage', false), '—')
  assert.equal(m.hourLabel('2026-10-06T15:00', true), '3 PM')
  assert.equal(m.hourLabel('2026-10-06T00:00', true), '12 AM')
  assert.equal(m.hourLabel('2026-10-06T15:00', false), '15:00')
  assert.equal(m.hourLabel(undefined, true), '—')
})

test('compass and wind detail', () => {
  assert.equal(m.compass(0), 'N')
  assert.equal(m.compass(225), 'SW')
  assert.equal(m.compass(350), 'N')
  assert.equal(m.compass(null), '')
  assert.equal(m.windDetail({wind_direction_10m: 225, wind_gusts_10m: 36}, 'mph'), 'SW · gusts 22')
  assert.equal(m.windDetail({}, 'mph'), 'At your location')
})

test('UV levels use the standard bands', () => {
  assert.deepEqual([0, 2.4, 2.5, 5.4, 7, 10, 11].map(m.uvLevel), ['Low', 'Low', 'Moderate', 'Moderate', 'High', 'Very high', 'Extreme'])
  assert.equal(m.uvLevel(null), '')
})

test('every WMO weather code gets a condition, an icon, and the right precipitation word', () => {
  const expected = {0: 'Clear skies', 1: 'Partly cloudy', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Fog', 51: 'Drizzle', 57: 'Drizzle',
    61: 'Rain', 67: 'Rain', 71: 'Snow', 77: 'Snow', 80: 'Rain', 82: 'Rain', 85: 'Snow', 86: 'Snow', 95: 'Thunderstorms', 99: 'Thunderstorms'}
  for (const [code, name] of Object.entries(expected)) {
    assert.equal(m.condition(Number(code)), name, 'condition for ' + code)
    assert.match(m.icon(Number(code), 1), /^[-]$/, 'icon for ' + code)
    assert.equal(m.precipWord(Number(code)), name === 'Snow' ? 'snow' : 'rain')
  }
  assert.equal(m.condition(undefined), 'Waiting for weather')
  assert.equal(m.precipWord(undefined), 'rain')
})

test('a station report takes over the current condition and is credited', () => {
  const observed = {code: 61, text: 'Light rain', station: 'Lorain County Regional Airport', ageMinutes: 8}
  assert.equal(m.nowCondition(3, observed), 'Light rain')
  assert.equal(m.nowCondition(3, undefined), 'Overcast')
  assert.equal(m.nowCondition(3, {}), 'Overcast')
  assert.equal(m.observedNote(observed), 'Light rain observed 8 min ago at Lorain County Regional Airport · NWS')
  assert.equal(m.observedNote({text: 'Snow', ageMinutes: 0}), 'Snow observed just now · NWS')
  assert.equal(m.observedBrief(observed), 'Light rain 8 min ago')
  assert.equal(m.observedBrief({text: 'Snow', ageMinutes: 0}), 'Snow now')
  assert.equal(m.observedBrief(null), '')
  assert.equal(m.observedNote(undefined), '')
  assert.equal(m.observedNote({}), '')
})

test('clear, partly cloudy, and fog have night icons', () => {
  for (const code of [0, 2, 45]) assert.notEqual(m.icon(code, 0), m.icon(code, 1))
  assert.equal(m.icon(3, 0), m.icon(3, 1))
  assert.equal(m.icon(undefined), m.icon(3, 1))
})

test('moon outlook wording', () => {
  assert.equal(m.moonOutlook({name: 'Waning crescent', nextFull: 20, nextNew: 5}), 'Full moon in ~20 days · new in ~5 days')
  assert.equal(m.moonOutlook({name: 'Waxing gibbous', nextFull: 1, nextNew: 16}), 'Full moon in ~1 day · new in ~16 days')
  assert.equal(m.moonOutlook({name: 'Full moon', nextFull: 30, nextNew: 15}), 'Full now · new moon in ~15 days')
  assert.equal(m.moonOutlook({name: 'New moon', nextFull: 15, nextNew: 29}), 'New now · full moon in ~15 days')
  assert.equal(m.moonOutlook({name: '—'}), '')
})

test('the moon is lit on the opposite side south of the equator', () => {
  assert.equal(m.moonLitSide(.25, false), 1)
  assert.equal(m.moonLitSide(.75, false), -1)
  assert.equal(m.moonLitSide(.25, true), -1)
  assert.equal(m.moonLitSide(.75, true), 1)
})

test('sun progress tracks today only', () => {
  const day = {date: '2026-10-06', sunrise: '2026-10-06T06:00', sunset: '2026-10-06T18:00'}
  assert.equal(m.sunProgress(day, '2026-10-06', '12:00'), .5)
  assert.equal(m.sunProgress(day, '2026-10-06', '06:00'), 0)
  assert.ok(m.sunProgress(day, '2026-10-06', '05:00') < 0)
  assert.ok(m.sunProgress(day, '2026-10-06', '21:00') > 1)
  assert.ok(Number.isNaN(m.sunProgress(day, '2026-10-07', '12:00')))
  assert.ok(Number.isNaN(m.sunProgress({date: '2026-10-06'}, '2026-10-06', '12:00')))
  assert.ok(Number.isNaN(m.sunProgress({}, undefined, undefined)))
})

test('bezier hits its endpoints and midpoint', () => {
  assert.equal(m.bezier(5, 10, 20, 95, 0), 5)
  assert.equal(m.bezier(5, 10, 20, 95, 1), 95)
  assert.equal(m.bezier(0, 0, 8, 8, .5), 4)
})

test('a day shows its rain, or its snow on a snowy day', () => {
  assert.equal(m.amount({weather_code: 61, precipitation_sum: 10.2}, false), '10 mm')
  assert.equal(m.amount({weather_code: 61, precipitation_sum: 10.2}, true), '0.4 in')
  assert.equal(m.amount({weather_code: 61, precipitation_sum: .4}, false), '<1 mm')
  assert.equal(m.amount({weather_code: 61, precipitation_sum: .5}, true), '<0.1 in')
  assert.equal(m.amount({weather_code: 73, precipitation_sum: 8, snowfall_sum: 6.3}, false), '6 cm')
  assert.equal(m.amount({weather_code: 73, precipitation_sum: 8, snowfall_sum: 6.3}, true), '2.5 in')
  // A trace, or a forecast saved before amounts were kept, shows nothing.
  assert.equal(m.amount({weather_code: 61, precipitation_sum: 0}, false), '')
  assert.equal(m.amount({weather_code: 61}, true), '')
  assert.equal(m.amount(null, true), '')
})

test('today is compared with yesterday in display degrees', () => {
  assert.equal(m.yesterdayNote({temperature_2m_max: 20}, {temperature_2m_max: 15}, false), '5° warmer than yesterday')
  assert.equal(m.yesterdayNote({temperature_2m_max: 15}, {temperature_2m_max: 20}, true), '9° cooler than yesterday')
  assert.equal(m.yesterdayNote({temperature_2m_max: 15}, {temperature_2m_max: 15.5}, true), 'About the same as yesterday')
  assert.equal(m.yesterdayNote({temperature_2m_max: 15}, null, true), '')
})

test('the nowcast reads as minutes soon and as a time later', () => {
  assert.equal(m.nowcastText({state: 'starting', at: '2026-10-06T16:00', minutes: 18, kind: 'rain'}, true), 'Rain starting in ~20 min')
  assert.equal(m.nowcastText({state: 'starting', at: '2026-10-06T16:00', minutes: 2, kind: 'rain'}, true), 'Rain starting in ~5 min')
  assert.equal(m.nowcastText({state: 'easing', at: '2026-10-06T17:45', minutes: 125, kind: 'snow'}, false), 'Snow easing around 17:45')
  assert.equal(m.nowcastText({state: 'continuing', at: '2026-10-06T19:45', minutes: 245, kind: 'rain'}, true), 'Rain through at least 7:45 PM')
  assert.equal(m.nowcastText(null, true), '')
})

test('air quality uses the index of the place', () => {
  const reading = {us_aqi: 112, european_aqi: 35, pollen: {}}
  assert.deepEqual(m.air(reading, 'America/New_York'), {value: '112', level: 'Sensitive groups', detail: 'Sensitive groups', poor: true})
  assert.deepEqual(m.air(reading, 'Europe/Berlin'), {value: '35', level: 'Fair', detail: 'Fair', poor: false})
  assert.equal(m.air({us_aqi: 40, european_aqi: 12, pollen: {grass: 80, birch: 12}}, 'Europe/London').detail, 'Grass pollen high')
  assert.equal(m.air({us_aqi: 40}, 'Europe/London').value, '40')
  assert.equal(m.air(null, 'Europe/London'), null)
  assert.equal(m.air({us_aqi: null}, 'America/Chicago'), null)
})

test('alerts get a glyph, a deadline, and an urgency', () => {
  assert.equal(m.alertIcon('Tornado Warning'), '')
  assert.equal(m.alertIcon('Winter Storm Watch'), '')
  assert.equal(m.alertIcon('Civil Danger Warning'), '󰀦')
  assert.equal(m.alertUntil({until: '2026-10-06T18:00'}, '2026-10-06', true), 'until 6:00 PM')
  assert.equal(m.alertUntil({until: '2026-10-10T06:30'}, '2026-10-06', false), 'until Sat 06:30')
  assert.equal(m.alertUntil({until: ''}, '2026-10-06', true), '')
  assert.equal(m.alertUrgent({tier: 'warning', rank: 2}), true)
  assert.equal(m.alertUrgent({tier: 'watch', rank: 3}), true)
  assert.equal(m.alertUrgent({tier: 'advisory', rank: 2}), false)
  assert.equal(m.alertUrgent(null), false)
})
