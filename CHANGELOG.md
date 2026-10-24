# Changelog

## 1.4.0 — 2026-10-23

- Weather alerts (US only): active NWS watches, warnings, and advisories as a one-line banner that opens to the full text. A warning tints the bar pill in the theme's urgent color. Checked every 2 minutes; expired alerts drop off even while NWS is unreachable.
- Rain timing: "Rain starting in ~20 min" or "Rain easing around 4:15 PM", from the 15-minute forecast, in the panel and the tooltip.
- Rain and snow amounts on the day cards and in the rain tile.
- The hourly strip shows a faint rain gauge, and follows the selected day in two-hour steps.
- Today compared with yesterday's high.
- Air quality tile: US AQI, or the European index in Europe, with notable pollen.
- New `notify` setting: `off`, `alerts`, or `all` (alerts and rain about to start).
- Wind gusts drop their repeated unit, to fit a fifth tile.

## 1.3.0 — 2026-10-10

- Observed precipitation (US only): rain, snow, or thunderstorms reported by a nearby NWS station now replace the modeled sky in the bar icon, the current condition, and the **Now** hour, with intensity ("Light rain"). The footer and tooltip credit the station.
- Station reports are re-checked every 5 minutes, independently of the 15-minute forecast refresh.
- The forecast is saved and shown before the station is asked, so a slow NWS never delays it.
- Outside NWS coverage nothing changes, and the location is asked about at most once a month.

## 1.2.0 — 2026-10-06

- Hourly strip: temperature, conditions, and rain chance for the next twelve hours.
- Today's feels-like high and low under the day's range.
- New `wind` setting: `auto`, `mph`, `km/h`, or `m/s`.
- The bar label dims while it is showing a saved forecast, replacing the trailing dot.
- The panel always opens on today instead of the day last inspected.
- The missing-location message now includes the command that sets one.
- Display logic moved into `Model.js` and covered by tests that run in CI.

## 1.1.0 — 2026-10-06

- Units default to `auto` and follow the system locale; `unit` can be changed from the bar settings.
- Sunrise and sunset follow the locale's 12- or 24-hour clock.
- The moon is drawn for your hemisphere, and its countdown covers both full and new moon.
- New UV index tile; wind shows direction and gusts, humidity shows dew point.
- Snow days say "snow"; the sun moves along its arc through the day.
- Press R to refresh; H and L also move between days.
- Icons use the shell font's weather glyphs, so they all take the accent color.
- A crashed or missing helper and an unwritable cache each report their own error.
- Coordinates are rounded to two decimals before being sent to Open-Meteo.
- The installer no longer edits `shell.json` or replaces another plugin's slot.

## 1.0.0 — 2026-10-06

- Initial release: current conditions, six-day forecast, sun and moon.
