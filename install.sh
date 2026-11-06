#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_dir="$HOME/.config/omarchy/plugins/neil.weather"
for dependency in omarchy omarchy-shell jq; do
  command -v "$dependency" >/dev/null || {
    echo "Weather requires $dependency." >&2
    exit 1
  }
done
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
# Discovery is asynchronous. Do not enable a plugin the shell has not loaded.
discovered=0
for ((attempt = 0; attempt < 40; attempt++)); do
  if omarchy plugin list --json | jq -e 'any(.[]; .id == "neil.weather")' >/dev/null; then
    discovered=1
    break
  fi
  sleep 0.05
done
if (( ! discovered )); then
  echo "The Omarchy shell has not discovered neil.weather. Check that the shell is running, then rerun install.sh." >&2
  exit 1
fi
# The shell preserves existing placement/settings and re-enables disabled entries.
omarchy plugin enable neil.weather
printf '%s\n' 'Installed neil.weather. If the bar has not refreshed, run: omarchy restart shell'
