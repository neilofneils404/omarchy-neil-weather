// Display logic for the weather panel: units, formatting, icons, and the sun
// and moon geometry. Pure functions with no QML dependencies, so the same
// file is imported by Panel.qml and run under Node by tests/model.test.js.

// Qt's Locale.MeasurementSystem values.
var METRIC_SYSTEM = 0
var IMPERIAL_US_SYSTEM = 1

function number(v) {
  return v !== null && v !== undefined && typeof v !== "boolean" && isFinite(v)
}

function normalized(value) {
  return String(value === null || value === undefined ? "" : value).replace(/^\s+|\s+$/g, "").toLowerCase()
}

// "auto" follows the locale: Fahrenheit only under the US system.
function usesFahrenheit(unit, measurementSystem) {
  unit = normalized(unit)
  if (unit === "imperial") return true
  if (unit === "metric") return false
  return measurementSystem === IMPERIAL_US_SYSTEM
}

// Returns "mph", "km/h", or "m/s". An explicit wind setting wins; otherwise
// the unit setting decides, and "auto" gives mph wherever miles are used
// (so en_GB gets °C with mph).
function windUnit(wind, unit, measurementSystem) {
  wind = normalized(wind)
  if (wind === "mph" || wind === "km/h" || wind === "m/s") return wind
  unit = normalized(unit)
  if (unit === "imperial") return "mph"
  if (unit === "metric") return "km/h"
  return measurementSystem === METRIC_SYSTEM ? "km/h" : "mph"
}

// A locale time format such as "h:mm AP" or "HH:mm"; quoted literals are
// ignored so a quoted "a" does not read as an AM/PM marker.
function usesTwelveHourClock(timeFormat) {
  return /a/i.test(String(timeFormat || "").replace(/'[^']*'/g, ""))
}

// Temperatures arrive in Celsius.
function temp(v, fahrenheit) {
  return number(v) ? Math.round(fahrenheit ? v * 9 / 5 + 32 : v) + "°" : "—"
}

// Wind speeds arrive in km/h.
function speed(v, unit) {
  if (!number(v)) return "—"
  if (unit === "mph") return Math.round(v * .621371) + " mph"
  if (unit === "m/s") return Math.round(v / 3.6) + " m/s"
  return Math.round(v) + " km/h"
}

function compass(degrees) {
  return number(degrees) ? ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(degrees / 45) % 8] : ""
}

// Gusts are in the same unit as the wind above them, so it is left off to
// fit a narrow tile.
function windDetail(current, unit) {
  var parts = []
  if (compass(current.wind_direction_10m)) parts.push(compass(current.wind_direction_10m))
  if (number(current.wind_gusts_10m)) parts.push("gusts " + speed(current.wind_gusts_10m, unit).split(" ")[0])
  return parts.length ? parts.join(" · ") : "At your location"
}

function uvLevel(v) {
  if (!number(v)) return ""
  var index = Math.round(v)
  if (index < 3) return "Low"
  if (index < 6) return "Moderate"
  if (index < 8) return "High"
  if (index < 11) return "Very high"
  return "Extreme"
}

// Minutes past midnight from "HH:MM" or an ISO "…THH:MM" local timestamp.
function minutes(v) {
  var t = String(v || "")
  if (t.indexOf("T") >= 0) t = t.split("T")[1]
  return /^\d\d:\d\d/.test(t) ? Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5)) : NaN
}

function clock(v, twelveHour) {
  var total = minutes(v)
  if (isNaN(total)) return "—"
  var h = Math.floor(total / 60), m = ("0" + total % 60).slice(-2)
  if (!twelveHour) return ("0" + h).slice(-2) + ":" + m
  return (h % 12 || 12) + ":" + m + (h < 12 ? " AM" : " PM")
}

// Compact label for an hourly cell: "3 PM", or "15:00" on a 24-hour clock.
function hourLabel(v, twelveHour) {
  var total = minutes(v)
  if (isNaN(total)) return "—"
  var h = Math.floor(total / 60)
  if (!twelveHour) return ("0" + h).slice(-2) + ":00"
  return (h % 12 || 12) + (h < 12 ? " AM" : " PM")
}

function isSnow(code) {
  return (code >= 71 && code <= 77) || code === 85 || code === 86
}

function precipWord(code) {
  return isSnow(code) ? "snow" : "rain"
}

// Nerd Font weather glyphs from the shell font, as the built-in weather
// widget uses: one font, so every icon takes the accent color and none
// falls back to a color emoji.
function icon(code, isDay) {
  var night = isDay === 0
  if (!number(code)) return "\ue33d"
  if (code === 0) return night ? "\ue32b" : "\ue30d"
  if (code <= 2) return night ? "\ue32e" : "\ue302"
  if (code === 3) return "\ue33d"
  if (code <= 48) return night ? "\ue346" : "\ue313"
  if (code >= 95) return "\ue31d"
  if (isSnow(code)) return "\ue31a"
  if (code <= 57) return "\ue31b"
  return "\ue318"
}

function condition(code) {
  if (!number(code)) return "Waiting for weather"
  if (code === 0) return "Clear skies"
  if (code <= 2) return "Partly cloudy"
  if (code === 3) return "Overcast"
  if (code <= 48) return "Fog"
  if (code >= 95) return "Thunderstorms"
  if (isSnow(code)) return "Snow"
  if (code <= 57) return "Drizzle"
  return "Rain"
}

// What the sky is doing now: a nearby station's report when there is one,
// otherwise the modeled condition.
function nowCondition(code, observed) {
  return observed && observed.text ? observed.text : condition(code)
}

// Short form for the tooltip, honest about how old the report is.
function observedBrief(observed) {
  if (!observed || !observed.text) return ""
  return observed.text + (observed.ageMinutes > 0 ? " " + observed.ageMinutes + " min ago" : " now")
}

// Credit for a station report that replaced the modeled sky.
function observedNote(observed) {
  if (!observed || !observed.text) return ""
  return observed.text + " observed "
    + (observed.ageMinutes > 0 ? observed.ageMinutes + " min ago" : "just now")
    + (observed.station ? " at " + observed.station : "")
    + " · NWS"
}

// A day's rain, or its snow on a snowy day: "0.4 in", "12 mm", "5 cm".
// Precipitation arrives in mm and snowfall in cm. Empty for a trace.
function amount(day, fahrenheit) {
  if (!day) return ""
  var snow = isSnow(day.weather_code) && number(day.snowfall_sum) && day.snowfall_sum >= .1
  var v = snow ? day.snowfall_sum * 10 : day.precipitation_sum
  if (!number(v) || v < (snow ? 1 : .1)) return ""
  if (fahrenheit) {
    var inches = v / 25.4
    return (inches < .05 ? "<0.1" : inches < 10 ? inches.toFixed(1) : Math.round(inches)) + " in"
  }
  if (snow) return Math.max(1, Math.round(v / 10)) + " cm"
  return (v < 1 ? "<1" : Math.round(v)) + " mm"
}

// How today compares with yesterday, by their highs, in display degrees.
function yesterdayNote(today, yesterday, fahrenheit) {
  if (!today || !yesterday || !number(today.temperature_2m_max) || !number(yesterday.temperature_2m_max)) return ""
  var diff = Math.round((today.temperature_2m_max - yesterday.temperature_2m_max) * (fahrenheit ? 9 / 5 : 1))
  if (Math.abs(diff) < 2) return "About the same as yesterday"
  return Math.abs(diff) + "° " + (diff > 0 ? "warmer" : "cooler") + " than yesterday"
}

// When the rain starts or stops, from the helper's nowcast.
function nowcastText(n, twelveHour) {
  if (!n || !n.state || !n.at) return ""
  var what = n.kind === "snow" ? "Snow" : "Rain"
  var soon = number(n.minutes) && n.minutes < 60
  var when = soon ? "in ~" + Math.max(5, Math.round(n.minutes / 5) * 5) + " min" : "around " + clock(n.at, twelveHour)
  if (n.state === "starting") return what + " starting " + when
  if (n.state === "easing") return what + " easing " + when
  return what + " through at least " + clock(n.at, twelveHour)
}

// Air quality by the index used where the forecast is: the European index in
// Europe, the US AQI elsewhere. null when there is no reading.
function air(reading, timezone) {
  if (!reading) return null
  var european = /^Europe\//.test(String(timezone || "")) && number(reading.european_aqi)
  var v = european ? reading.european_aqi : reading.us_aqi
  if (!number(v)) return null
  v = Math.round(v)
  var levels = european
    ? [[20, "Good"], [40, "Fair"], [60, "Moderate"], [80, "Poor"], [100, "Very poor"], [Infinity, "Extremely poor"]]
    : [[50, "Good"], [100, "Moderate"], [150, "Sensitive groups"], [200, "Unhealthy"], [300, "Very unhealthy"], [Infinity, "Hazardous"]]
  var level = ""
  for (var i = 0; i < levels.length && !level; i++) if (v <= levels[i][0]) level = levels[i][1]
  var pollen = pollenNote(reading.pollen)
  return {
    value: String(v),
    level: level,
    detail: pollen || level,
    // Past "Moderate", where some people should take care.
    poor: european ? v > 60 : v > 100
  }
}

// The strongest pollen worth mentioning: "Grass pollen high". Grains per m³,
// on a rough common scale; Open-Meteo only models pollen in Europe.
function pollenNote(pollen) {
  if (!pollen) return ""
  var top = "", most = 0
  for (var name in pollen) {
    if (number(pollen[name]) && pollen[name] > most) { top = name; most = pollen[name] }
  }
  if (most < 50) return ""
  return top.charAt(0).toUpperCase() + top.slice(1) + " pollen " + (most < 200 ? "high" : "very high")
}

// Alert glyphs from the shell font, chosen by what the event is about.
function alertIcon(event) {
  var text = String(event || "").toLowerCase()
  if (text.indexOf("tornado") !== -1) return "\ue347"
  if (text.indexOf("hurricane") !== -1 || text.indexOf("tropical") !== -1) return "\ue36c"
  if (text.indexOf("thunder") !== -1) return "\ue31d"
  if (text.indexOf("blizzard") !== -1) return "\ue35e"
  if (/\bice\b/.test(text) || text.indexOf("freezing rain") !== -1) return "\ue3ad"
  if (text.indexOf("snow") !== -1 || text.indexOf("winter") !== -1) return "\ue31a"
  if (text.indexOf("flood") !== -1) return "\ue318"
  if (text.indexOf("heat") !== -1) return "\ue36b"
  if (text.indexOf("wind") !== -1) return "\ue300"
  if (text.indexOf("dust") !== -1) return "\ue35d"
  if (text.indexOf("avalanche") !== -1) return "\ue366"
  if (text.indexOf("cold") !== -1 || text.indexOf("chill") !== -1 || text.indexOf("freeze") !== -1 || text.indexOf("frost") !== -1) return "\ue33e"
  if (text.indexOf("fire") !== -1 || text.indexOf("red flag") !== -1) return "\ue37b"
  if (text.indexOf("marine") !== -1 || text.indexOf("gale") !== -1) return "\ue35d"
  if (text.indexOf("fog") !== -1 || text.indexOf("smoke") !== -1) return "\ue313"
  return "\udb80\udc26"
}

// A warning tints the bar; watches and advisories stay in the panel.
function alertUrgent(alert) {
  return !!alert && (alert.tier === "warning" || alert.rank >= 3)
}

var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

// "until 6:00 PM", or "until Sat 6:00 PM" when it is not today.
function alertUntil(alert, localDate, twelveHour) {
  if (!alert || !alert.until) return ""
  var date = alert.until.slice(0, 10)
  var day = date === localDate ? "" : WEEKDAYS[new Date(date + "T12:00:00").getDay()] + " "
  return "until " + day + clock(alert.until, twelveHour)
}

function inDays(n) {
  return "~" + n + (n === 1 ? " day" : " days")
}

function moonOutlook(moon) {
  if (!moon || !number(moon.nextFull) || !number(moon.nextNew)) return ""
  if (moon.name === "Full moon") return "Full now · new moon in " + inDays(moon.nextNew)
  if (moon.name === "New moon") return "New now · full moon in " + inDays(moon.nextFull)
  return "Full moon in " + inDays(moon.nextFull) + " · new in " + inDays(moon.nextNew)
}

// Which limb is lit: 1 for the right, -1 for the left. Waxing is lit on the
// right from the northern hemisphere and on the left from the southern.
function moonLitSide(phase, southern) {
  return (phase < .5 ? 1 : -1) * (southern ? -1 : 1)
}

// Fraction of the day's daylight that has passed: below 0 before sunrise,
// above 1 after sunset, NaN when the day is not today or has no sun times.
function sunProgress(day, localDate, localTime) {
  if (!day || !day.date || day.date !== localDate) return NaN
  var rise = minutes(day.sunrise), set = minutes(day.sunset), now = minutes(localTime)
  if (!(set > rise) || isNaN(now)) return NaN
  return (now - rise) / (set - rise)
}

// Point on a cubic Bézier, one axis at a time.
function bezier(a, b, c, d, t) {
  var u = 1 - t
  return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d
}

if (typeof module !== "undefined") {
  module.exports = {
    METRIC_SYSTEM: METRIC_SYSTEM,
    IMPERIAL_US_SYSTEM: IMPERIAL_US_SYSTEM,
    number: number,
    usesFahrenheit: usesFahrenheit,
    windUnit: windUnit,
    usesTwelveHourClock: usesTwelveHourClock,
    temp: temp,
    speed: speed,
    compass: compass,
    windDetail: windDetail,
    uvLevel: uvLevel,
    minutes: minutes,
    clock: clock,
    hourLabel: hourLabel,
    isSnow: isSnow,
    precipWord: precipWord,
    icon: icon,
    condition: condition,
    nowCondition: nowCondition,
    observedBrief: observedBrief,
    observedNote: observedNote,
    amount: amount,
    yesterdayNote: yesterdayNote,
    nowcastText: nowcastText,
    air: air,
    pollenNote: pollenNote,
    alertIcon: alertIcon,
    alertUrgent: alertUrgent,
    alertUntil: alertUntil,
    inDays: inDays,
    moonOutlook: moonOutlook,
    moonLitSide: moonLitSide,
    sunProgress: sunProgress,
    bezier: bezier
  }
}
