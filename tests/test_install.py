"""Installer integration checks using a disposable HOME and stub shell IPC."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class InstallTests(unittest.TestCase):
    def run_install(self, ready_after, existing=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / 'bin'
            commands.mkdir()
            stub = '''#!/usr/bin/python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['HOME'])
with (root / 'calls').open('a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:] == ['plugin', 'list', '--json']:
    counter = root / 'counter'
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    print(json.dumps([{'id': 'neil.weather'}] if count >= int(os.environ['READY_AFTER']) else []))
'''
            for name, body in [('omarchy', stub), ('omarchy-shell', '#!/bin/sh\nexit 0\n'),
                               ('sleep', '#!/bin/sh\nexit 0\n')]:
                path = commands / name
                path.write_text(body)
                path.chmod(0o755)
            config = root / '.config/omarchy/shell.json'
            config.parent.mkdir(parents=True)
            saved = {'bar': {'layout': {'center': [{'id': 'neil.weather', 'unit': 'metric'}]}},
                     'disabledPlugins': ['neil.weather']} if existing else {}
            config.write_text(json.dumps(saved))
            env = {**os.environ, 'HOME': str(root), 'PATH': str(commands) + os.pathsep + os.environ['PATH'],
                   'READY_AFTER': str(ready_after)}
            run = subprocess.run(['bash', str(Path(__file__).resolve().parents[1] / 'install.sh')],
                                 env=env, capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
            self.assertEqual(json.loads(config.read_text()), saved)
            return run, calls

    def test_waits_for_async_discovery_before_enabling(self):
        run, calls = self.run_install(3)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls, [['plugin', 'list', '--json']] * 3 + [['plugin', 'enable', 'neil.weather']])

    def test_existing_disabled_placement_is_reenabled(self):
        run, calls = self.run_install(1, existing=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls[-1], ['plugin', 'enable', 'neil.weather'])

    def test_discovery_timeout_does_not_enable(self):
        run, calls = self.run_install(100)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('has not discovered', run.stderr)
        self.assertEqual(calls, [['plugin', 'list', '--json']] * 40)
