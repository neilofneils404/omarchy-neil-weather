import QtQuick
import qs.Commons
Rectangle {
  property string label: ""
  property string value: "—"
  property string detail: ""
  color: Util.alpha(Color.foreground, 0.04)
  radius: Style.space(8)
  implicitHeight: Style.space(78)
  Column {
    anchors.fill: parent; anchors.margins: Style.space(12); spacing: Style.space(5)
    WeatherText { width: parent.width; text: label; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption }
    WeatherText { width: parent.width; text: value; font.pixelSize: Style.font.title; font.bold: true }
    WeatherText { width: parent.width; text: detail; color: Util.alpha(Color.foreground, .62); font.pixelSize: Style.font.caption }
  }
}
