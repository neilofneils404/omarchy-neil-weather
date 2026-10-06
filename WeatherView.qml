import QtQuick
import qs.Commons

Item {
  property var weather
  readonly property var root: weather
  implicitHeight: content.implicitHeight
      Flickable {
        anchors.fill: parent; contentWidth: width; contentHeight: content.implicitHeight; clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column {
          id: content; width: parent.width; spacing: Style.space(16)
          Row {
            width: parent.width; spacing: Style.space(12)
            Column {
              width: parent.width - Style.space(100); spacing: Style.space(4)
              WeatherText { text: "WEATHER / " + (root.report.location || "Local weather").toUpperCase(); font.pixelSize: Style.font.caption; font.letterSpacing: 2; color: Color.accent; width: parent.width }
              WeatherText { text: root.report.localDate ? Qt.formatDate(new Date(root.report.localDate + "T12:00:00"), "dddd, MMMM d") : "Your daily outlook"; width: parent.width; color: Util.alpha(Color.foreground, .62) }
            }
            Rectangle {
              width: Style.space(88); height: Style.space(32); radius: Style.space(6)
              color: refreshMouse.containsMouse ? Util.alpha(Color.accent,.15) : Util.alpha(Color.foreground,.06)
              WeatherText { anchors.centerIn: parent; text: root.loading ? "Updating…" : "↻ Refresh"; font.pixelSize: Style.font.caption }
              MouseArea { id: refreshMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.refresh(true) }
            }
          }
          Rectangle {
            width: parent.width; height: Style.space(172); radius: Style.space(12)
            gradient: Gradient { GradientStop { position: 0; color: Util.alpha(Color.accent,.12) } GradientStop { position: 1; color: Util.alpha(Color.foreground,.025) } }
            border.color: Util.alpha(Color.accent,.2)
            Column {
              width: parent.width * .56 - Style.space(22); anchors.left: parent.left; anchors.leftMargin: Style.space(22); anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(4)
              WeatherText { text: root.report.stale ? "LAST KNOWN CONDITIONS" : "RIGHT NOW"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption; font.letterSpacing: 2 }
              WeatherText { text: root.temp(root.current.temperature_2m) + (root.imperial ? "F" : "C"); font.pixelSize: Style.space(62); font.bold: true }
              WeatherText { width: parent.width; text: root.condition(root.current.weather_code) + "  ·  Feels like " + root.temp(root.current.apparent_temperature); color: Util.alpha(Color.foreground, .62) }
            }
            Column {
              width: parent.width * .40 - Style.space(22); anchors.right: parent.right; anchors.rightMargin: Style.space(22); anchors.verticalCenter: parent.verticalCenter; spacing: Style.space(8)
              WeatherText { anchors.right: parent.right; text: root.icon(root.current.weather_code, root.current.is_day); font.pixelSize: Style.space(46); color: Color.accent }
              WeatherText { anchors.right: parent.right; text: "TODAY’S HIGH / LOW"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption }
              WeatherText { width: parent.width; horizontalAlignment: Text.AlignRight; fontSizeMode: Text.HorizontalFit; minimumPixelSize: 12; anchors.right: parent.right; text: "↑ " + root.temp(root.report.today ? root.report.today.temperature_2m_max : null) + "   ↓ " + root.temp(root.report.today ? root.report.today.temperature_2m_min : null); font.pixelSize: Style.font.display; font.bold: true }
            }
          }
          Row {
            width: parent.width; spacing: Style.space(8)
            Metric { width: (parent.width - 2 * parent.spacing) / 3; label: "WIND"; value: root.current.wind_speed_10m === undefined || root.current.wind_speed_10m === null ? "—" : Math.round(root.current.wind_speed_10m * (root.imperial ? .621371 : 1)) + (root.imperial ? " mph" : " km/h"); detail: "At your location" }
            Metric { width: (parent.width - 2 * parent.spacing) / 3; label: "HUMIDITY"; value: root.current.relative_humidity_2m === undefined || root.current.relative_humidity_2m === null ? "—" : root.current.relative_humidity_2m + "%"; detail: "Relative humidity" }
            Metric { width: (parent.width - 2 * parent.spacing) / 3; label: "RAIN CHANCE"; value: root.day.precipitation_probability_max === undefined || root.day.precipitation_probability_max === null ? "—" : root.day.precipitation_probability_max + "%"; detail: root.days.length ? root.dayName(root.day) : "Daily forecast" }
          }
          WeatherText { text: "SIX-DAY OUTLOOK"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption; font.letterSpacing: 2 }
          Row {
            width: parent.width; spacing: Style.space(8)
            Repeater {
              model: root.days
              Rectangle {
                id: card; required property var modelData; required property int index
                width: (content.width - 5 * Style.space(8)) / 6; height: Style.space(132); radius: Style.space(8)
                color: root.selected === index ? Util.alpha(Color.accent,.12) : Util.alpha(Color.foreground, forecastMouse.containsMouse ? .08 : .035)
                border.width: root.selected === index ? 1 : 0; border.color: Util.alpha(Color.accent,.55)
                Behavior on color { ColorAnimation { duration: 140 } }
                Column {
                  anchors.centerIn: parent; width: parent.width - Style.space(8); spacing: Style.space(10)
                  WeatherText { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.dayName(card.modelData); font.pixelSize: Style.font.caption; color: root.selected === card.index ? Color.accent : Util.alpha(Color.foreground, .62) }
                  WeatherText { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.icon(card.modelData.weather_code, 1); font.pixelSize: Style.space(25); color: Color.accent }
                  WeatherText { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.temp(card.modelData.temperature_2m_max) + " / " + root.temp(card.modelData.temperature_2m_min); font.bold: true; font.pixelSize: Style.font.caption }
                  WeatherText { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: card.modelData.precipitation_probability_max === null ? "—" : card.modelData.precipitation_probability_max + "% rain"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption }
                }
                MouseArea { id: forecastMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.selected = card.index }
              }
            }
          }
          Row {
            width: parent.width; spacing: Style.space(8)
            Rectangle {
              width: (parent.width - parent.spacing) / 2; height: Style.space(152); radius: Style.space(10); color: Util.alpha(Color.foreground,.04)
              Column {
                anchors.fill: parent; anchors.margins: Style.space(14); spacing: Style.space(9)
                WeatherText { text: "SUN / " + (root.days.length ? root.dayName(root.day).toUpperCase() : "TODAY"); color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption; font.letterSpacing: 1.5 }
                Item {
                  width: parent.width; height: Style.space(45)
                  Canvas {
                    id: sunCanvas
                    anchors.fill: parent
                    onPaint: { var ctx = getContext("2d"); ctx.reset(); ctx.strokeStyle = Util.alpha(Color.accent,.45); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(5,height-5); ctx.bezierCurveTo(width*.25,-height*.45,width*.75,-height*.45,width-5,height-5); ctx.stroke(); ctx.strokeStyle = Util.alpha(Color.foreground,.12); ctx.beginPath(); ctx.moveTo(0,height-5); ctx.lineTo(width,height-5); ctx.stroke() }
                    Connections { target: Color; function onAccentChanged() { sunCanvas.requestPaint() } }
                  }
                  WeatherText { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; text: "☀"; color: Color.accent; font.pixelSize: Style.space(24) }
                }
                WeatherText { width: parent.width; text: "↑ " + root.clock(root.day.sunrise) + "     ↓ " + root.clock(root.day.sunset); font.bold: true; font.pixelSize: Style.font.caption }
                WeatherText { text: root.day.daylight_duration ? Math.floor(root.day.daylight_duration / 3600) + "h " + Math.round(root.day.daylight_duration % 3600 / 60) + "m of daylight" : "Sun times unavailable"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption }
              }
            }
            Rectangle {
              width: (parent.width - parent.spacing) / 2; height: Style.space(152); radius: Style.space(10); color: Util.alpha(Color.foreground,.04)
              Column {
                anchors.fill: parent; anchors.margins: Style.space(14); spacing: Style.space(9)
                WeatherText { text: "MOON / TONIGHT"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption; font.letterSpacing: 1.5 }
                Row {
                  spacing: Style.space(14)
                  Canvas {
                    id: moonCanvas; width: Style.space(44); height: width
                    onPaint: {
                      var ctx=getContext("2d"), r=width*.45, cx=width/2, cy=height/2, p=root.moon.phase || 0;
                      ctx.reset(); ctx.fillStyle=Util.alpha(Color.accent,.13); ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2); ctx.fill();
                      ctx.fillStyle=Color.accent; ctx.beginPath();
                      var side=p < .5 ? 1 : -1, k=Math.cos(2*Math.PI*p);
                      for(var j=0;j<=60;j++){var y=-r+2*r*j/60, x=Math.sqrt(Math.max(0,r*r-y*y)); if(j===0)ctx.moveTo(cx+side*x,cy+y);else ctx.lineTo(cx+side*x,cy+y)}
                      for(var j=60;j>=0;j--){var y=-r+2*r*j/60, x=Math.sqrt(Math.max(0,r*r-y*y));ctx.lineTo(cx+side*k*x,cy+y)}ctx.closePath();ctx.fill();
                    }
                    Connections { target: root; function onMoonChanged() { moonCanvas.requestPaint() } }
                    Connections { target: Color; function onAccentChanged() { moonCanvas.requestPaint() } }
                  }
                  Column {
                    spacing: Style.space(6)
                    WeatherText { text: root.moon.name; font.bold: true }
                    WeatherText { text: root.moon.illumination + "% illuminated"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption }
                  }
                }
                WeatherText { text: "Full moon in ~" + (root.moon.nextFull || 0) + " days"; font.pixelSize: Style.font.caption }
                WeatherText { text: "Approximate lunar cycle"; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption }
              }
            }
          }
          WeatherText {
            width: parent.width; wrapMode: Text.Wrap; elide: Text.ElideNone; font.pixelSize: Style.font.caption
            color: root.report.stale || !root.report.available ? Color.urgent : Util.alpha(Color.foreground, .62)
            text: !root.report.available ? root.report.error : (root.report.stale ? "SAVED FORECAST · " : "UPDATED · ") + (root.report.ageMinutes === 0 ? "just now" : root.report.ageMinutes + " min ago") + "   /   Open-Meteo" + (root.report.error ? "   /   " + root.report.error : "")
          }
        }
      }
}
