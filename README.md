# Weather / Neil

An Omarchy weather plugin built around the question: **what is today actually going to feel like?**

Current temperature, today's full-day high and low, the next twelve hours, today plus the next five days, and a quiet sun-and-moon panel. Uses the active Omarchy palette, spacing, and typography. No radar, API key, pip packages, or separate background service.

![Weather panel with illustrative demo data](preview.png)

## Features

- Current conditions, feels-like temperature, wind direction and gusts, humidity, and dew point.
- Today's high and low, and what they will feel like, stay visible even after the warmest part of the day passes.
- The next twelve hours at a glance: temperature, conditions, and rain chance for each.
- Six forecast cards with highs, lows, conditions, and rain probability.
- Select a day to inspect its rain or snow chance, peak UV index, sunrise, sunset, and daylight duration.
- The sun moves along its arc through the day, and dims once it has set.
- Drawn moon phase, oriented for your hemisphere, with approximate illumination and days until the next full and new moon.
- Units and the 12- or 24-hour clock follow your system locale by default.
- Saved forecast appears immediately while the next request runs.
- Atomic disk cache, location-specific cache validation, response limits, a 12-second request timeout, and persistent exponential retry backoff.
- Forecast dates follow the location's timezone. A seven-day response leaves room for rollover to the next local day during an outage.
- Stale readings are labeled **last known conditions** and **saved forecast**, and the bar label dims.

## Requirements

An Omarchy installation using the Quickshell plugin runtime, Python 3.9+ with system timezone data, and network access to `https://api.open-meteo.com`. Weather icons are Nerd Font glyphs drawn from the shell font, which is a Nerd Font on a stock Omarchy install.

Waybar-era Omarchy installations are not supported. Omarchy shell APIs can change; this initial version was validated against the shell installed on October 6, 2026.

## Install from a checkout

```bash
./install.sh
```

The installer links the checkout into `~/.config/omarchy/plugins/neil.weather` and asks the shell to enable it, which adds it to the center of the bar. It does not edit `shell.json` itself, and it leaves other weather plugins and an existing `neil.weather` placement untouched. Running it again is harmless.

If needed, run `omarchy restart shell` after installation. During development, restart the shell after editing QML. As of Omarchy 4.0.4 the shell does not notice edits made through the symlink, and `omarchy-shell shell rescanPlugins` reuses the already-loaded QML.

## Install with the plugin manager

```bash
omarchy plugin add https://github.com/neilofneils404/omarchy-neil-weather.git --enable
```

## Location and units

Uses Omarchy's shared location at `~/.local/state/omarchy/settings/weather.json`. Configure a location with coordinates through Omarchy or its CLI:

```bash
omarchy weather location --set "Your city" latitude,longitude
```

Stored coordinates are required. This plugin does not silently guess your location from your IP address. Coordinates are rounded to two decimal places (about 1 km) before they are sent to Open-Meteo, which is finer than the forecast grid.

The bar entry in `~/.config/omarchy/shell.json` accepts:

```json
{"id": "neil.weather", "unit": "auto"}
```

`unit` can also be changed from the widget's settings in Omarchy's bar setup:

- `auto` (default) follows your system locale: Fahrenheit and mph in the US, Celsius and mph in the UK, Celsius and km/h elsewhere.
- `imperial` forces Fahrenheit and mph.
- `metric` forces Celsius and km/h.

`wind` sets the wind speed unit on its own: `auto` (default, follows `unit`), `mph`, `km/h`, or `m/s`.

Sunrise, sunset, and the hourly strip use a 12- or 24-hour clock according to your locale.

## Controls

- Left or right click the bar pill: open/close. The panel always opens on today.
- Hover the bar pill: today's high/low and freshness. A dimmed pill means a saved forecast.
- Middle click: force a refresh.
- Click **Refresh** in the popup, or press R: force a refresh.
- Click a forecast card or use Left/Right (or H/L): select the day.
- Escape or click outside: close.
- Tab: move between Omarchy panels.

## Data and accuracy

Weather comes from [Open-Meteo](https://open-meteo.com/), using its best-match forecast models. Current conditions are modeled weather, not a personal weather-station observation. Data attribution: Open-Meteo, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The moon uses a mean synodic cycle calculation anchored to January 6, 2000. Phase, illumination, and next full and new moon timing are **approximate**, and labeled accordingly. It does not provide moonrise/moonset or a precision astronomical ephemeris. Sun times are supplied by Open-Meteo.

Forecasts refresh every 15 minutes; the plugin checks once a minute for freshness, timezone rollover, and retry eligibility. The cache and retry state live in `~/.local/state/neil-weather/`, outside the repository. After an extended outage, expired forecast days disappear rather than being relabeled as today.

If the panel reports that the weather helper failed, check that `python3` is on the shell's `PATH`. A message about the weather cache means `~/.local/state/neil-weather/` is not writable.

## Development

```bash
python3 -m unittest discover -s tests -v
node --test tests/model.test.js
qmllint -I /usr/share/omarchy/shell *.qml
```

CI runs the Python tests on 3.9 and 3.13, and the display-logic tests under Node.

`weather.py` handles fetching, validation, caching, and lunar estimates. `Model.js` holds the display logic (units, clock, icons, wording, sun and moon geometry) as plain functions so it can be tested without a running shell. `Panel.qml` handles the shell lifecycle and state. `WeatherView.qml` is the panel layout; `Metric.qml` and `WeatherText.qml` provide shared styles. There are no third-party Python dependencies.

## Uninstall

Remove `neil.weather` from your bar layout, then remove its directory or symlink under `~/.config/omarchy/plugins/`. The project checkout and shared Omarchy location remain untouched. Optionally remove `~/.local/state/neil-weather/` to clear its cache.

## Changes

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT. The bar/popup integration is adapted from Omarchy; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
