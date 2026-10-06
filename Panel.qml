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
  readonly property bool loading: fetch.running
  property int selected: 0
  property bool imperial: setting("unit", "imperial") !== "metric"
  readonly property var days: report.days || []
  readonly property var day: days.length ? days[Math.min(selected, days.length - 1)] : ({})
  readonly property var current: report.current || ({})
  readonly property var moon: report.moon || ({name: "—", illumination: 0, phase: 0})
  readonly property string label: report.available ? icon(current.weather_code, current.is_day) + " " + temp(current.temperature_2m) + (report.stale ? " ·" : "") : "☁ —"
  readonly property string tooltip: report.available ? report.location + " · Today ↑ " + temp(report.today ? report.today.temperature_2m_max : null) + " ↓ " + temp(report.today ? report.today.temperature_2m_min : null) + (report.stale ? " · saved forecast" : "") : report.error
  function temp(v) { return v === null || v === undefined || !isFinite(v) ? "—" : Math.round(imperial ? v * 9 / 5 + 32 : v) + "°" }
  function clock(v) { if (!v) return "—"; var t = v.split("T")[1]; if (!t) return "—"; var h = Number(t.slice(0,2)); return (h % 12 || 12) + t.slice(2,5) + (h < 12 ? " AM" : " PM") }
  function icon(code, isDay) { if (code === undefined) return "☁"; if (code === 0) return isDay === 0 ? "☾" : "☀"; if (code <= 2) return "⛅"; if (code === 3) return "☁"; if (code <= 48) return "≋"; if (code >= 95) return "ϟ"; if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "❄"; return "☂" }
  function condition(code) { if (code === undefined) return "Waiting for weather"; if (code === 0) return "Clear skies"; if (code <= 2) return "Partly cloudy"; if (code === 3) return "Overcast"; if (code <= 48) return "Fog"; if (code >= 95) return "Thunderstorms"; if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "Snow"; if (code <= 57) return "Drizzle"; return "Rain" }
  function dayName(d) { return d.date === report.localDate ? "Today" : Qt.formatDate(new Date(d.date + "T12:00:00"), "ddd") }
  function refresh(force) { if (fetch.running) return; fetch.command = ["python3", decodeURIComponent(Qt.resolvedUrl("weather.py").toString().replace(/^file:\/\//, ""))]; if (force === true) fetch.command = fetch.command.concat(["--force"]); fetch.running = true }
  function suppressHover(value) { if (root.bar && root.bar.setCenterHoverRevealSuppressed) root.bar.setCenterHoverRevealSuppressed(value) }
  function openFromHotkey() { root.controller.show(); refresh(); Qt.callLater(function() { if (root.opened) root.suppressHover(true) }) }
  function toggle() { if (opened) close(); else openFromHotkey() }
  function close() { suppressHover(false); root.controller.hide() }
  Process {
    id: fetch
    stdout: SplitParser { onRead: data => { try { var next = JSON.parse(data); root.report = next; root.selected = Math.min(root.selected, Math.max(0, root.days.length - 1)) } catch (e) { root.report = Object.assign({}, root.report, {stale:true, error:"Could not read weather response"}) } } }
  }
  Timer { interval: 60000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refresh() }
  FileView { path: Quickshell.env("HOME") + "/.local/state/omarchy/settings/weather.json"; watchChanges: true; printErrors: false; onFileChanged: { reload(); root.refresh(true) } }

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
      onTabRequested: function(direction) { if(root.bar) root.bar.switchPanelFrom(root.hostWidget || root, direction) }
      Keys.onLeftPressed: root.selected = Math.max(0, root.selected - 1)
      Keys.onRightPressed: root.selected = Math.min(root.days.length - 1, root.selected + 1)
      WeatherView { id: weatherView; anchors.fill: parent; weather: root }
    }
  }
}
