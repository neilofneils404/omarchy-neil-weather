import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "neil.weather"
  ipcTarget: "neil.weather"

  property var anchorItem: null
  property var hostWidget: null
  property var report: ({available: false, error: "Loading weather…"})
  property int selected: 0
  // Set once the helper prints a report; a run that ends without one failed.
  property bool reported: false

  readonly property bool loading: fetch.running
  readonly property var days: report.days || []
  readonly property var day: days.length ? days[Math.min(selected, days.length - 1)] : ({})
  readonly property var current: report.current || ({})
  readonly property var moon: report.moon || ({name: "—", illumination: 0, phase: 0})

  // "auto" follows the system locale: Fahrenheit only under the US system,
  // mph wherever miles are used (so en_GB gets °C with mph).
  readonly property string unit: String(setting("unit", "auto")).trim().toLowerCase()
  readonly property int measurement: Qt.locale().measurementSystem
  readonly property bool fahrenheit: unit === "imperial" || (unit !== "metric" && measurement === Locale.ImperialUSSystem)
  readonly property bool mph: unit === "imperial" || (unit !== "metric" && measurement !== Locale.MetricSystem)
  readonly property bool twelveHour: /a/i.test(Qt.locale().timeFormat(Locale.ShortFormat).replace(/'[^']*'/g, ""))

  readonly property string label: report.available
    ? icon(current.weather_code, current.is_day) + " " + temp(current.temperature_2m) + (report.stale ? " ·" : "")
    : icon(undefined) + " —"
  readonly property string tooltip: report.available
    ? report.location
      + " · Today ↑ " + temp(report.today ? report.today.temperature_2m_max : null)
      + " ↓ " + temp(report.today ? report.today.temperature_2m_min : null)
      + (report.stale ? " · saved forecast" : "")
    : report.error

  // Fraction of the selected day's daylight that has passed: below 0 before
  // sunrise, above 1 after sunset, NaN when the selected day is not today.
  readonly property real sunProgress: {
    if (!day.date || day.date !== report.localDate) return NaN
    var rise = minutes(day.sunrise), set = minutes(day.sunset), now = minutes(report.localTime)
    if (!(set > rise) || isNaN(now)) return NaN
    return (now - rise) / (set - rise)
  }

  function number(v) {
    return v !== null && v !== undefined && isFinite(v)
  }

  function temp(v) {
    return number(v) ? Math.round(fahrenheit ? v * 9 / 5 + 32 : v) + "°" : "—"
  }

  function speed(v) {
    return number(v) ? Math.round(mph ? v * .621371 : v) + (mph ? " mph" : " km/h") : "—"
  }

  function compass(degrees) {
    return number(degrees) ? ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(degrees / 45) % 8] : ""
  }

  function windDetail() {
    var parts = []
    if (compass(current.wind_direction_10m)) parts.push(compass(current.wind_direction_10m))
    if (number(current.wind_gusts_10m)) parts.push("gusts " + speed(current.wind_gusts_10m))
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

  function clock(v) {
    var total = minutes(v)
    if (isNaN(total)) return "—"
    var h = Math.floor(total / 60), m = ("0" + total % 60).slice(-2)
    if (!twelveHour) return ("0" + h).slice(-2) + ":" + m
    return (h % 12 || 12) + ":" + m + (h < 12 ? " AM" : " PM")
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
    if (code === undefined) return "\ue33d"
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
    if (code === undefined) return "Waiting for weather"
    if (code === 0) return "Clear skies"
    if (code <= 2) return "Partly cloudy"
    if (code === 3) return "Overcast"
    if (code <= 48) return "Fog"
    if (code >= 95) return "Thunderstorms"
    if (isSnow(code)) return "Snow"
    if (code <= 57) return "Drizzle"
    return "Rain"
  }

  function dayName(d) {
    return d.date === report.localDate ? "Today" : Qt.formatDate(new Date(d.date + "T12:00:00"), "ddd")
  }

  function inDays(n) {
    return "~" + n + (n === 1 ? " day" : " days")
  }

  function moonOutlook() {
    if (!number(moon.nextFull) || !number(moon.nextNew)) return ""
    if (moon.name === "Full moon") return "Full now · new moon in " + inDays(moon.nextNew)
    if (moon.name === "New moon") return "New now · full moon in " + inDays(moon.nextFull)
    return "Full moon in " + inDays(moon.nextFull) + " · new in " + inDays(moon.nextNew)
  }

  function refresh(force) {
    if (fetch.running) return
    var script = decodeURIComponent(Qt.resolvedUrl("weather.py").toString().replace(/^file:\/\//, ""))
    fetch.command = force === true ? ["python3", script, "--force"] : ["python3", script]
    reported = false
    fetch.running = true
  }

  function suppressHover(value) {
    if (root.bar && root.bar.setCenterHoverRevealSuppressed) root.bar.setCenterHoverRevealSuppressed(value)
  }

  function openFromHotkey() {
    root.controller.show()
    refresh()
    Qt.callLater(function() { if (root.opened) root.suppressHover(true) })
  }

  function toggle() {
    if (opened) close()
    else openFromHotkey()
  }

  function close() {
    suppressHover(false)
    root.controller.hide()
  }

  Process {
    id: fetch
    stdout: SplitParser {
      onRead: data => {
        root.reported = true
        try {
          root.report = JSON.parse(data)
          root.selected = Math.min(root.selected, Math.max(0, root.days.length - 1))
        } catch (e) {
          root.report = Object.assign({}, root.report, {stale: true, error: "Could not read weather response"})
        }
      }
    }
    // weather.py prints a report on every path, so silence means it never
    // ran (no python3) or crashed. Say so instead of loading forever.
    onRunningChanged: {
      if (running || root.reported) return
      root.report = Object.assign({}, root.report, {stale: true, error: "Weather helper failed · check that python3 is installed"})
    }
  }

  Timer {
    interval: 60000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  FileView {
    path: Quickshell.env("HOME") + "/.local/state/omarchy/settings/weather.json"
    watchChanges: true
    printErrors: false
    onFileChanged: {
      reload()
      root.refresh(true)
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: catcher
    contentWidth: fittedContentWidth(Style.space(650))
    contentHeight: fittedContentHeight(weatherView.implicitHeight)

    PanelKeyCatcher {
      id: catcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) {
        if (root.bar) root.bar.switchPanelFrom(root.hostWidget || root, direction)
      }
      onMoveRequested: function(dx, dy) {
        if (dx) root.selected = Math.max(0, Math.min(root.days.length - 1, root.selected + dx))
      }
      onTextKey: function(text) {
        if (text === "r" || text === "R") root.refresh(true)
      }

      WeatherView {
        id: weatherView
        anchors.fill: parent
        weather: root
      }
    }
  }
}
