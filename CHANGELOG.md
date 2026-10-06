# Changelog

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
