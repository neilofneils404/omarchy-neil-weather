#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_dir="$HOME/.config/omarchy/plugins/neil.weather"
shell_config="$HOME/.config/omarchy/shell.json"
mkdir -p "$(dirname "$plugin_dir")"
if [[ -e "$plugin_dir" || -L "$plugin_dir" ]]; then
  if [[ "$(readlink -f "$plugin_dir")" != "$project_dir" ]]; then
    echo "An existing neil.weather installation is present at $plugin_dir. Move it before installing this checkout." >&2
    exit 1
  fi
else
  ln -s "$project_dir" "$plugin_dir"
fi
omarchy-shell -q shell rescanPlugins
# The shell owns shell.json: let it place the widget, and leave an existing
# placement (and every other plugin's slot) exactly as it is.
if [[ -f "$shell_config" ]] && jq -e 'any(.bar.layout[]?[]?; .id? == "neil.weather")' "$shell_config" >/dev/null; then
  echo "neil.weather is already in your bar; left its placement and settings alone."
else
  omarchy plugin enable neil.weather
fi
printf '%s\n' 'Installed neil.weather. If the bar has not refreshed, run: omarchy restart shell'
