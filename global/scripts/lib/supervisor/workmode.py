"""The work mode of a project (normal, publish-first)."""
import json
import os
from datetime import datetime

from . import projects, util


# ---------------------------------------------------------------- work mode
# Two ways of working, on demand: the usual one, and publish-first (static and style checks before publishing, the full
# suite once at the end). The mode is a per-project switch that carries the developer's written order, so nobody
# builds and unbuilds the flow each time, and only that order switches it.
WORK_MODES = ('normal', 'publish-first')


def mode_path(key):
    return os.path.join(util.home(), 'modes', key + '.json')


def read_mode(key):
    try:
        with open(mode_path(key)) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {'mode': 'normal'}
    return data if isinstance(data, dict) and data.get('mode') in WORK_MODES else {'mode': 'normal'}


def cmd_mode(args):
    project = projects.resolve(args.dir)
    key = project['key']
    if args.set:
        if not (args.order or '').strip():
            util.die("--order is required: the developer's words, quoted, that ask for this mode", 2)
        data = {'mode': args.set, 'order': args.order.strip(), 'by': args.session or '-',
                'since': datetime.now().astimezone().isoformat(timespec='seconds'), 'project': project['name']}
        path = mode_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f'.{os.getpid()}.tmp'
        with open(tmp, 'w') as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        print(f'MODE_SET {key} {args.set}')
        return 0
    data = read_mode(key)
    if args.get:
        print(data['mode'])
        return 0
    extra = f' since={data.get("since")} order=«{data.get("order")}»' if data.get('order') else ''
    print(f'MODE {key} {data["mode"]}{extra}')
    return 0
