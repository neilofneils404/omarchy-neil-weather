#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_dir="$HOME/.config/omarchy/plugins/neil.weather"
mkdir -p "$(dirname "$plugin_dir")"
if [[ -e "$plugin_dir" || -L "$plugin_dir" ]]; then
  if [[ "$(readlink -f "$plugin_dir")" != "$project_dir" ]]; then
    echo "An existing neil.weather installation is present at $plugin_dir. Move it before installing this checkout." >&2
    exit 1
  fi
else
  ln -s "$project_dir" "$plugin_dir"
fi
python3 - <<'PY'
import json, pathlib, shutil, time
path = pathlib.Path.home() / '.config/omarchy/shell.json'
config = json.loads(path.read_text()) if path.exists() else {'version': 1, 'bar': {'layout': {'center': []}}}
if path.exists():
    backup = pathlib.Path.home() / '.local/state/neil-weather'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup / ('shell-before-install-' + str(time.time_ns()) + '.json'))
layout = config.setdefault('bar', {}).setdefault('layout', {})
found = any(entry.get('id') == 'neil.weather' for entries in layout.values() for entry in entries)
if not found:
    for entries in layout.values():
        for entry in entries:
            if entry.get('id') in ('jmthomas00.linecast', 'omarchy.weather'):
                entry.clear(); entry.update(id='neil.weather', unit='imperial'); found = True; break
        if found: break
if not found: layout.setdefault('center', []).append({'id': 'neil.weather', 'unit': 'imperial'})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(config, indent=2) + '\n')
PY
omarchy-shell -q shell rescanPlugins
printf '%s\n' 'Installed neil.weather. If the bar has not refreshed, run: omarchy restart shell'
