"""The `systemd --user` timer that runs `tick` (design D11). The installer never writes these units: the user runs
`usage-watch timer install` once, like `claude-sessions-sync install`. `print` writes nothing."""
from __future__ import annotations

import os
import subprocess
import sys

SERVICE = 'usage-watch.service'
TIMER = 'usage-watch.timer'


def unit_dir() -> str:
    return os.path.expanduser('~/.config/systemd/user')


def units(cfg: dict, script: str) -> dict[str, str]:
    interval = max(1, int(cfg['timer_interval_min']))
    service = ('[Unit]\nDescription=usage-watch measuring cycle (collect, detect, page)\n\n'
               '[Service]\nType=oneshot\n'
               f'ExecStart={sys.executable} {os.path.realpath(script)} tick\n')
    timer = ('[Unit]\nDescription=Run usage-watch tick periodically\n\n'
             f'[Timer]\nOnBootSec=5min\nOnUnitActiveSec={interval}min\nUnit={SERVICE}\n\n'
             '[Install]\nWantedBy=timers.target\n')
    return {SERVICE: service, TIMER: timer}


def _systemctl(*args) -> int:
    try:
        return subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=60).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def run(action: str, cfg: dict, script: str) -> int:
    files = units(cfg, script)
    if action == 'print':
        for name, text in files.items():
            print(f'# {name}\n{text}')
        return 0
    if action == 'status':
        for name in files:
            path = os.path.join(unit_dir(), name)
            print(f'{name}: {"installed" if os.path.isfile(path) else "absent"}')
        return 0
    if action == 'install':
        os.makedirs(unit_dir(), exist_ok=True)
        for name, text in files.items():
            with open(os.path.join(unit_dir(), name), 'w', encoding='utf-8') as fh:
                fh.write(text)
        codes = [_systemctl('daemon-reload'), _systemctl('enable', '--now', TIMER)]
        print(f'usage-watch: timer installed in {unit_dir()}' + ('' if not any(codes) else ' (systemctl failed)'))
        return 0 if not any(codes) else 1
    if action == 'uninstall':
        _systemctl('disable', '--now', TIMER)
        for name in files:
            try:
                os.remove(os.path.join(unit_dir(), name))
            except FileNotFoundError:
                pass
        _systemctl('daemon-reload')
        print('usage-watch: timer removed')
        return 0
    return 2
