import QtQuick
import qs.Commons
import "Model.js" as Model

Item {
  id: view

  property var weather
  readonly property var root: weather
  readonly property color muted: Util.alpha(Color.foreground, .62)

  implicitHeight: content.implicitHeight

  Flickable {
    anchors.fill: parent
    contentWidth: width
    contentHeight: content.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: content
      width: parent.width
      spacing: Style.space(16)

      // Header: location, date, refresh.
      Row {
        width: parent.width
        spacing: Style.space(12)

        Column {
          width: parent.width - Style.space(100)
          spacing: Style.space(4)

          WeatherText {
            width: parent.width
            text: "WEATHER / " + (root.report.location || "Local weather").toUpperCase()
            font.pixelSize: Style.font.caption
            font.letterSpacing: 2
            color: Color.accent
          }
          WeatherText {
            width: parent.width
            text: root.report.localDate
              ? Qt.formatDate(new Date(root.report.localDate + "T12:00:00"), "dddd, MMMM d")
              : "Your daily outlook"
            color: view.muted
          }
        }

        Rectangle {
          width: Style.space(88)
          height: Style.space(32)
          radius: Style.space(6)
          color: refreshMouse.containsMouse ? Util.alpha(Color.accent, .15) : Util.alpha(Color.foreground, .06)

          WeatherText {
            anchors.centerIn: parent
            text: root.loading ? "Updating…" : "↻ Refresh"
            font.pixelSize: Style.font.caption
          }
          MouseArea {
            id: refreshMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.refresh(true)
          }
        }
      }

      // Alerts: only while NWS has one out for this place. One line until
      // opened, so a long-running advisory never crowds the forecast.
      Rectangle {
        id: banner
        visible: root.alerts.length > 0
        width: parent.width
        height: visible ? bannerColumn.implicitHeight + Style.space(20) : 0
        radius: Style.space(10)
        readonly property color tone: Model.alertUrgent(root.alert) ? Color.urgent : Color.accent
        color: Util.alpha(tone, bannerMouse.containsMouse && !root.alertOpen ? .16 : .1)
        border.color: Util.alpha(tone, .45)
        Behavior on color { ColorAnimation { duration: 140 } }

        Column {
          id: bannerColumn
          x: Style.space(14)
          y: Style.space(10)
          width: parent.width - Style.space(28)
          spacing: Style.space(10)

          Item {
            width: parent.width
            height: Style.space(34)

            WeatherText {
              id: alertGlyph
              width: Style.space(30)
              anchors.verticalCenter: parent.verticalCenter
              horizontalAlignment: Text.AlignHCenter
              text: root.alert ? Model.alertIcon(root.alert.event) : ""
              font.pixelSize: Style.space(22)
              color: banner.tone
            }
            Column {
              anchors.left: alertGlyph.right
              anchors.leftMargin: Style.space(10)
              anchors.right: alertMore.left
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(3)

              WeatherText {
                width: parent.width
                text: root.alert ? root.alert.event.toUpperCase() : ""
                font.pixelSize: Style.font.caption
                font.letterSpacing: 1.5
                font.bold: true
                color: banner.tone
              }
              WeatherText {
                width: parent.width
                text: root.alert ? [root.alertUntil(root.alert), root.alert.sender].filter(function(s) { return s }).join(" · ") : ""
                font.pixelSize: Style.font.caption
                color: view.muted
              }
            }
            WeatherText {
              id: alertMore
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: (root.alerts.length > 1 ? (root.alertIndex + 1) + " of " + root.alerts.length + "  ·  " : "")
                + (root.alertOpen ? "Hide ⌃" : "Details ⌄")
              font.pixelSize: Style.font.caption
              color: view.muted
            }
            MouseArea {
              id: bannerMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.alertOpen = !root.alertOpen
            }
          }

          // Every active alert, when there is more than one to choose from.
          Flow {
            visible: root.alertOpen && root.alerts.length > 1
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.alertOpen ? root.alerts : []

              Rectangle {
                id: chip
                required property var modelData
                required property int index
                readonly property bool current: index === root.alertIndex
                readonly property color tone: Model.alertUrgent(modelData) ? Color.urgent : Color.accent
                width: chipText.implicitWidth + Style.space(16)
                height: Style.space(26)
                radius: Style.space(6)
                color: current ? Util.alpha(tone, .2) : Util.alpha(Color.foreground, chipMouse.containsMouse ? .08 : .04)
                border.width: current ? 1 : 0
                border.color: Util.alpha(tone, .55)

                WeatherText {
                  id: chipText
                  anchors.centerIn: parent
                  text: Model.alertIcon(chip.modelData.event) + "  " + chip.modelData.event
                  font.pixelSize: Style.font.caption
                  color: chip.current ? chip.tone : Color.foreground
                }
                MouseArea {
                  id: chipMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.alertIndex = chip.index
                }
              }
            }
          }

          WeatherText {
            visible: root.alertOpen && text !== ""
            width: parent.width
            text: root.alert ? root.alert.description : ""
            wrapMode: Text.Wrap
            maximumLineCount: 8
            font.pixelSize: Style.font.caption
            lineHeight: 1.15
          }
          WeatherText {
            visible: root.alertOpen && text !== ""
            width: parent.width
            text: root.alert ? root.alert.instruction : ""
            wrapMode: Text.Wrap
            maximumLineCount: 5
            font.pixelSize: Style.font.caption
            font.bold: true
            lineHeight: 1.15
          }
        }
      }

      // Hero: current conditions and today's full-day range.
      Rectangle {
        width: parent.width
        height: Style.space(172)
        radius: Style.space(12)
        border.color: Util.alpha(Color.accent, .2)
        gradient: Gradient {
          GradientStop { position: 0; color: Util.alpha(Color.accent, .12) }
          GradientStop { position: 1; color: Util.alpha(Color.foreground, .025) }
        }

        Column {
          width: parent.width * .56 - Style.space(22)
          anchors.left: parent.left
          anchors.leftMargin: Style.space(22)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(4)

          WeatherText {
            text: root.report.stale ? "LAST KNOWN CONDITIONS" : "RIGHT NOW"
            color: view.muted
            font.pixelSize: Style.font.caption
            font.letterSpacing: 2
          }
          WeatherText {
            text: root.temp(root.current.temperature_2m) + (root.fahrenheit ? "F" : "C")
            font.pixelSize: Style.space(62)
            font.bold: true
          }
          WeatherText {
            width: parent.width
            text: root.nowCondition() + "  ·  Feels like " + root.temp(root.current.apparent_temperature)
            color: view.muted
          }
          // When the rain starts or stops, if it will within a few hours.
          WeatherText {
            visible: root.nowcast !== "" && !root.report.stale
            width: parent.width
            text: root.icon(root.report.nowcast && root.report.nowcast.kind === "snow" ? 71 : 61, 1) + "  " + root.nowcast
            color: Color.accent
            font.pixelSize: Style.font.caption
          }
        }

        Column {
          width: parent.width * .40 - Style.space(22)
          anchors.right: parent.right
          anchors.rightMargin: Style.space(22)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(6)

          WeatherText {
            anchors.right: parent.right
            text: root.icon(root.current.weather_code, root.current.is_day)
            font.pixelSize: Style.space(42)
            color: Color.accent
          }
          WeatherText {
            anchors.right: parent.right
            text: "TODAY’S HIGH / LOW"
            color: view.muted
            font.pixelSize: Style.font.caption
          }
          WeatherText {
            width: parent.width
            anchors.right: parent.right
            horizontalAlignment: Text.AlignRight
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: 12
            text: "↑ " + root.temp(root.report.today ? root.report.today.temperature_2m_max : null)
              + "   ↓ " + root.temp(root.report.today ? root.report.today.temperature_2m_min : null)
            font.pixelSize: Style.font.display
            font.bold: true
          }
          WeatherText {
            anchors.right: parent.right
            visible: root.report.today ? root.number(root.report.today.apparent_temperature_max) : false
            text: root.report.today
              ? "Feels like " + root.temp(root.report.today.apparent_temperature_max) + " / " + root.temp(root.report.today.apparent_temperature_min)
              : ""
            color: view.muted
            font.pixelSize: Style.font.caption
          }
          WeatherText {
            anchors.right: parent.right
            visible: text !== ""
            text: Model.yesterdayNote(root.report.today, root.report.yesterday, root.fahrenheit)
            color: view.muted
            font.pixelSize: Style.font.caption
          }
        }
      }

      // Hourly: how the next twelve hours play out, or the selected day in
      // two-hour steps. Hidden until the helper has hourly data (a forecast
      // cached by an older version has none).
      WeatherText {
        visible: root.shownHours.length > 0
        text: root.laterDay
          ? root.dayName(root.day).toUpperCase() + " / EVERY 2 HOURS"
          : "NEXT " + root.shownHours.length + " HOURS"
        color: view.muted
        font.pixelSize: Style.font.caption
        font.letterSpacing: 2
      }

      Rectangle {
        visible: root.shownHours.length > 0
        width: parent.width
        height: Style.space(96)
        radius: Style.space(8)
        color: Util.alpha(Color.foreground, .035)

        Row {
          id: hourly
          anchors.fill: parent
          anchors.margins: Style.space(6)

          Repeater {
            model: root.shownHours

            Item {
              id: hour
              required property var modelData
              required property int index
              readonly property bool now: hour.index === 0 && !root.laterDay

              width: hourly.width / Math.max(1, root.shownHours.length)
              height: hourly.height

              // How much falls, as a gauge filling the cell from below:
              // full at a downpour (4 mm an hour).
              Rectangle {
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width - Style.space(6)
                radius: Style.space(4)
                readonly property real rate: root.number(hour.modelData.precipitation) ? hour.modelData.precipitation / (root.laterDay ? 2 : 1) : 0
                height: rate >= .1 ? Math.max(Style.space(3), parent.height * Math.min(1, rate / 4)) : 0
                color: Util.alpha(Color.accent, .16)
              }

              Column {
                width: parent.width
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)

                WeatherText {
                  width: parent.width
                  horizontalAlignment: Text.AlignHCenter
                  text: hour.now ? "Now" : root.hourLabel(hour.modelData.time)
                  font.pixelSize: Style.font.caption
                  color: hour.now ? Color.accent : view.muted
                }
                WeatherText {
                  width: parent.width
                  height: Style.space(20)
                  horizontalAlignment: Text.AlignHCenter
                  verticalAlignment: Text.AlignVCenter
                  text: root.icon(hour.modelData.weather_code, hour.modelData.is_day)
                  font.pixelSize: Style.space(17)
                  color: Color.accent
                }
                WeatherText {
                  width: parent.width
                  horizontalAlignment: Text.AlignHCenter
                  text: root.temp(hour.modelData.temperature_2m)
                  font.bold: true
                  font.pixelSize: Style.font.caption
                }
                WeatherText {
                  width: parent.width
                  horizontalAlignment: Text.AlignHCenter
                  text: root.number(hour.modelData.precipitation_probability) ? hour.modelData.precipitation_probability + "%" : "—"
                  color: view.muted
                  font.pixelSize: Style.font.caption
                }
              }
            }
          }
        }
      }

      // Metrics: wind, humidity, and air are current; rain and UV follow the
      // selected day. Air quality takes a fifth tile only when there is a reading.
      Row {
        id: metrics
        width: parent.width
        spacing: Style.space(8)
        readonly property int count: root.air ? 5 : 4
        readonly property real cell: (width - (count - 1) * spacing) / count

        Metric {
          width: metrics.cell
          label: "WIND"
          value: root.speed(root.current.wind_speed_10m)
          detail: root.windDetail()
        }
        Metric {
          width: metrics.cell
          label: "HUMIDITY"
          value: root.number(root.current.relative_humidity_2m) ? root.current.relative_humidity_2m + "%" : "—"
          detail: root.number(root.current.dew_point_2m) ? "Dew point " + root.temp(root.current.dew_point_2m) : "Relative humidity"
        }
        Metric {
          width: metrics.cell
          label: root.precipWord(root.day.weather_code).toUpperCase() + " CHANCE"
          value: root.number(root.day.precipitation_probability_max) ? root.day.precipitation_probability_max + "%" : "—"
          detail: root.days.length
            ? (root.amount(root.day) ? root.amount(root.day) + " · " : "") + root.dayName(root.day)
            : "Daily forecast"
        }
        Metric {
          width: metrics.cell
          label: "UV INDEX"
          value: root.number(root.day.uv_index_max) ? String(Math.round(root.day.uv_index_max)) : "—"
          detail: root.number(root.day.uv_index_max)
            ? root.uvLevel(root.day.uv_index_max) + " · " + root.dayName(root.day)
            : "Daily peak"
        }
        Metric {
          visible: root.air !== null
          width: metrics.cell
          label: "AIR QUALITY"
          value: root.air ? root.air.value : "—"
          tone: root.air && root.air.poor ? Color.urgent : Color.foreground
          detail: root.air ? root.air.detail : ""
        }
      }

      WeatherText {
        text: "SIX-DAY OUTLOOK"
        color: view.muted
        font.pixelSize: Style.font.caption
        font.letterSpacing: 2
      }

      Row {
        width: parent.width
        spacing: Style.space(8)

        Repeater {
          model: root.days

          Rectangle {
            id: card
            required property var modelData
            required property int index
            readonly property bool current: root.selected === index

            width: (content.width - 5 * Style.space(8)) / 6
            height: Style.space(132)
            radius: Style.space(8)
            color: current ? Util.alpha(Color.accent, .12) : Util.alpha(Color.foreground, forecastMouse.containsMouse ? .08 : .035)
            border.width: current ? 1 : 0
            border.color: Util.alpha(Color.accent, .55)
            Behavior on color { ColorAnimation { duration: 140 } }

            Column {
              anchors.centerIn: parent
              width: parent.width - Style.space(8)
              spacing: Style.space(10)

              WeatherText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: root.dayName(card.modelData)
                font.pixelSize: Style.font.caption
                color: card.current ? Color.accent : view.muted
              }
              WeatherText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                // Glyphs differ in height; a fixed box keeps the rows below aligned.
                height: Style.space(32)
                verticalAlignment: Text.AlignVCenter
                text: root.icon(card.modelData.weather_code, 1)
                font.pixelSize: Style.space(25)
                color: Color.accent
              }
              WeatherText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: root.temp(card.modelData.temperature_2m_max) + " / " + root.temp(card.modelData.temperature_2m_min)
                font.bold: true
                font.pixelSize: Style.font.caption
              }
              WeatherText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: !root.number(card.modelData.precipitation_probability_max)
                  ? "—"
                  : card.modelData.precipitation_probability_max + "%"
                    + (root.amount(card.modelData) ? " · " + root.amount(card.modelData) : " " + root.precipWord(card.modelData.weather_code))
                color: view.muted
                font.pixelSize: Style.font.caption
              }
            }
            MouseArea {
              id: forecastMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.selected = card.index
            }
          }
        }
      }

      Row {
        width: parent.width
        spacing: Style.space(8)

        // Sun: the selected day's arc, with the sun riding it through today.
        Rectangle {
          width: (parent.width - parent.spacing) / 2
          height: Style.space(152)
          radius: Style.space(10)
          color: Util.alpha(Color.foreground, .04)

          Column {
            anchors.fill: parent
            anchors.margins: Style.space(14)
            spacing: Style.space(9)

            WeatherText {
              text: "SUN / " + (root.days.length ? root.dayName(root.day).toUpperCase() : "TODAY")
              color: view.muted
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1.5
            }
            Item {
              id: sky
              width: parent.width
              height: Style.space(45)
              // Other days have no "now", so the sun rests at the top of the arc.
              readonly property bool tracked: !isNaN(root.sunProgress)
              readonly property real t: tracked ? Math.max(0, Math.min(1, root.sunProgress)) : .5
              readonly property bool night: tracked && (root.sunProgress < 0 || root.sunProgress > 1)

              Canvas {
                id: sunCanvas
                anchors.fill: parent
                onPaint: {
                  var ctx = getContext("2d")
                  ctx.reset()
                  ctx.strokeStyle = Util.alpha(Color.accent, .45)
                  ctx.lineWidth = 1.5
                  ctx.beginPath()
                  ctx.moveTo(5, height - 5)
                  ctx.bezierCurveTo(width * .25, -height * .45, width * .75, -height * .45, width - 5, height - 5)
                  ctx.stroke()
                  ctx.strokeStyle = Util.alpha(Color.foreground, .12)
                  ctx.beginPath()
                  ctx.moveTo(0, height - 5)
                  ctx.lineTo(width, height - 5)
                  ctx.stroke()
                }
                Connections { target: Color; function onAccentChanged() { sunCanvas.requestPaint() } }
              }
              WeatherText {
                x: Math.max(0, Math.min(sky.width - width, Model.bezier(5, sky.width * .25, sky.width * .75, sky.width - 5, sky.t) - width / 2))
                y: Math.max(0, Math.min(sky.height - height, Model.bezier(sky.height - 5, -sky.height * .45, -sky.height * .45, sky.height - 5, sky.t) - height / 2))
                text: root.icon(0, 1)
                color: Color.accent
                opacity: sky.night ? .35 : 1
                font.pixelSize: Style.space(24)
              }
            }
            WeatherText {
              width: parent.width
              text: "↑ " + root.clock(root.day.sunrise) + "     ↓ " + root.clock(root.day.sunset)
              font.bold: true
              font.pixelSize: Style.font.caption
            }
            WeatherText {
              text: root.day.daylight_duration
                ? Math.floor(root.day.daylight_duration / 3600) + "h " + Math.floor(root.day.daylight_duration % 3600 / 60) + "m of daylight"
                : "Sun times unavailable"
              color: view.muted
              font.pixelSize: Style.font.caption
            }
          }
        }

        // Moon: approximate phase, drawn the way it appears from this hemisphere.
        Rectangle {
          width: (parent.width - parent.spacing) / 2
          height: Style.space(152)
          radius: Style.space(10)
          color: Util.alpha(Color.foreground, .04)

          Column {
            anchors.fill: parent
            anchors.margins: Style.space(14)
            spacing: Style.space(9)

            WeatherText {
              text: "MOON / TONIGHT"
              color: view.muted
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1.5
            }
            Row {
              spacing: Style.space(14)

              Canvas {
                id: moonCanvas
                width: Style.space(44)
                height: width
                onPaint: {
                  var ctx = getContext("2d")
                  var r = width * .45, cx = width / 2, cy = height / 2
                  var p = root.moon.phase || 0
                  ctx.reset()
                  ctx.fillStyle = Util.alpha(Color.accent, .13)
                  ctx.beginPath()
                  ctx.arc(cx, cy, r, 0, Math.PI * 2)
                  ctx.fill()

                  // Lit region: the limb on the lit side, closed by the
                  // terminator (the limb squashed by cos of the phase angle).
                  // Waxing is lit on the right in the north, left in the south.
                  var side = Model.moonLitSide(p, root.moon.southern === true)
                  var k = Math.cos(2 * Math.PI * p)
                  var steps = 60, j, x, y
                  ctx.fillStyle = Color.accent
                  ctx.beginPath()
                  for (j = 0; j <= steps; j++) {
                    y = -r + 2 * r * j / steps
                    x = Math.sqrt(Math.max(0, r * r - y * y))
                    if (j === 0) ctx.moveTo(cx + side * x, cy + y)
                    else ctx.lineTo(cx + side * x, cy + y)
                  }
                  for (j = steps; j >= 0; j--) {
                    y = -r + 2 * r * j / steps
                    x = Math.sqrt(Math.max(0, r * r - y * y))
                    ctx.lineTo(cx + side * k * x, cy + y)
                  }
                  ctx.closePath()
                  ctx.fill()
                }
                Connections { target: root; function onMoonChanged() { moonCanvas.requestPaint() } }
                Connections { target: Color; function onAccentChanged() { moonCanvas.requestPaint() } }
              }
              Column {
                spacing: Style.space(6)

                WeatherText { text: root.moon.name; font.bold: true }
                WeatherText {
                  text: root.moon.illumination + "% illuminated"
                  color: view.muted
                  font.pixelSize: Style.font.caption
                }
              }
            }
            WeatherText {
              width: parent.width
              text: root.moonOutlook()
              font.pixelSize: Style.font.caption
            }
            WeatherText {
              text: "Approximate lunar cycle"
              color: view.muted
              font.pixelSize: Style.font.caption
            }
          }
        }
      }

      WeatherText {
        width: parent.width
        wrapMode: Text.Wrap
        elide: Text.ElideNone
        font.pixelSize: Style.font.caption
        color: root.report.stale || !root.report.available ? Color.urgent : view.muted
        text: !root.report.available
          ? root.report.error
          : (root.report.stale ? "SAVED FORECAST · " : "UPDATED · ")
            + (root.report.ageMinutes === 0 ? "just now" : root.report.ageMinutes + " min ago")
            + "   /   Open-Meteo"
            + (root.alerts.length ? "   /   NWS alerts" : "")
            + (root.observed ? "   /   " + root.observedNote() : "")
            + (root.report.error ? "   /   " + root.report.error : "")
      }
    }
  }
}
