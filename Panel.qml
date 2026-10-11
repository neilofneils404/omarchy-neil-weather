import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

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
  // Precipitation a nearby NWS station is reporting right now (US only).
  readonly property var observed: report.observed || null
  readonly property var moon: report.moon || ({name: "—", illumination: 0, phase: 0})

  // Units and clock follow the system locale unless a setting says otherwise;
  // the rules live in Model.js.
  readonly property bool fahrenheit: Model.usesFahrenheit(setting("unit", "auto"), Qt.locale().measurementSystem)
  readonly property string windUnit: Model.windUnit(setting("wind", "auto"), setting("unit", "auto"), Qt.locale().measurementSystem)
  readonly property bool twelveHour: Model.usesTwelveHourClock(Qt.locale().timeFormat(Locale.ShortFormat))

  readonly property bool stale: report.available === true && report.stale === true
  readonly property string label: report.available
    ? icon(current.weather_code, current.is_day) + " " + temp(current.temperature_2m)
    : icon(undefined) + " —"
  readonly property string tooltip: report.available
    ? report.location
      + (observed ? " · " + Model.observedBrief(observed) : "")
      + " · Today ↑ " + temp(report.today ? report.today.temperature_2m_max : null)
      + " ↓ " + temp(report.today ? report.today.temperature_2m_min : null)
      + (report.stale ? " · saved forecast" : "")
    : report.error

  readonly property var hours: report.hours || []
  readonly property real sunProgress: Model.sunProgress(day, report.localDate, report.localTime)

  // Thin wrappers that bind the current unit and clock settings.
  function number(v) { return Model.number(v) }
  function temp(v) { return Model.temp(v, fahrenheit) }
  function speed(v) { return Model.speed(v, windUnit) }
  function windDetail() { return Model.windDetail(current, windUnit) }
  function uvLevel(v) { return Model.uvLevel(v) }
  function clock(v) { return Model.clock(v, twelveHour) }
  function hourLabel(v) { return Model.hourLabel(v, twelveHour) }
  function precipWord(code) { return Model.precipWord(code) }
  function icon(code, isDay) { return Model.icon(code, isDay) }
  function condition(code) { return Model.condition(code) }
  function nowCondition() { return Model.nowCondition(current.weather_code, observed) }
  function observedNote() { return Model.observedNote(observed) }
  function moonOutlook() { return Model.moonOutlook(moon) }

  function dayName(d) {
    return d.date === report.localDate ? "Today" : Qt.formatDate(new Date(d.date + "T12:00:00"), "ddd")
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
    // Always open on today, whichever day was being inspected last time.
    root.selected = 0
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
