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

function windDetail(current, unit) {
  var parts = []
  if (compass(current.wind_direction_10m)) parts.push(compass(current.wind_direction_10m))
  if (number(current.wind_gusts_10m)) parts.push("gusts " + speed(current.wind_gusts_10m, unit))
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
    inDays: inDays,
    moonOutlook: moonOutlook,
    moonLitSide: moonLitSide,
    sunProgress: sunProgress,
    bezier: bezier
  }
}
