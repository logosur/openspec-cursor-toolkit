"""Command line: ./install.sh <command> [options]."""
from __future__ import annotations

import argparse
import subprocess
import sys

from . import apply as apply_mod
from . import deps, modules, overlay, plan as plan_mod
from .modules import ManifestError
from .overlay import OverrideError
from .paths import REPO_ROOT, resolve_override, resolve_target
from .settings_merge import SettingsError

from .modules import DEFAULT_MODULES  # noqa: E402


def toolkit_version() -> str:
    try:
        return subprocess.run(['git', '-C', str(REPO_ROOT), 'describe', '--always', '--dirty'],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def _common(ap: argparse.ArgumentParser) -> None:
    ap.add_argument('--target', help='Claude dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)')
    ap.add_argument('--override', help='override dir (default: $CLAUDE_TOOLKIT_OVERRIDE or ~/.config/claude-toolkit; "" for none)')
    ap.add_argument('--modules', help=f'comma-separated modules (default: override.yaml or {",".join(DEFAULT_MODULES)})')


def _context(args):
    target = resolve_target(args.target)
    ov = overlay.load(resolve_override(args.override))
    names = args.modules.split(',') if args.modules else (ov.modules or DEFAULT_MODULES)
    mods = modules.load_many(names)
    return target, ov, mods


def print_plan(p: plan_mod.Plan, verbose: bool) -> None:
    print(f'target   {p.target}')
    print(f'modules  {", ".join(p.modules)}')
    for a in p.actions:
        if a.kind == 'unchanged' and not verbose:
            continue
        src = f' [{a.desired.source}]' if a.desired else ''
        print(f'{a.kind:<11} {a.dest}{src}{"  (backup first)" if a.backup else ""}')
    for rec in p.hooks_to_add:
        print(f'hook-add    {rec["event"]} {rec.get("matcher") or "*"} -> {rec["hook"]["command"]}')
    c = p.counts()
    print('summary  ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items())))
    for note in p.notes:
        print(f'note     {note}')


def cmd_install(args) -> int:
    target, ov, mods = _context(args)
    errors, warnings = deps.check(mods)
    for w in warnings:
        print(f'WARN {w}')
    if errors:
        for e in errors:
            print(f'ERROR {e}')
        return 2
    p = plan_mod.build(target, mods, ov)
    print_plan(p, args.verbose)
    if args.dry_run:
        print('dry run: nothing written')
        return 0
    if not p.changes() and p.previous:
        print('already installed: nothing to do')
        return 0
    from . import contracts
    replaced = {d for d, x in p.desired.items() if x.source.startswith('override')}
    if replaced & {c['dest'] for c in contracts.load_all()}:
        ran, failures = contracts.check_plan_in_sandbox(p, {'override', 'override-extra'})
        for f in failures:
            print(f.render())
        if failures and not args.allow_contract_failures:
            print('install refused: a piece provided by the override breaks its contract (--allow-contract-failures to force)')
            return 3
    target.mkdir(parents=True, exist_ok=True)
    apply_mod.install(p, toolkit_version())
    print(f'installed into {target}')
    return 0


def cmd_uninstall(args) -> int:
    target = resolve_target(args.target)
    for line in apply_mod.uninstall(target, dry_run=args.dry_run):
        print(line)
    if args.dry_run:
        print('dry run: nothing written')
    return 0


def cmd_status(args) -> int:
    target, ov, mods = _context(args)
    p = plan_mod.build(target, mods, ov)
    m = p.previous
    print(f'target     {target}')
    print(f'override   {ov.root or "(none)"}')
    print(f'installed  {m.get("toolkit_version", "no") if m else "no"} {m.get("installed_at", "") if m else ""}')
    print('pending    ' + (', '.join(f'{k} {v}' for k, v in sorted(p.counts().items())) if p.changes() else 'nothing'))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='install.sh', description='Install and maintain the global Claude Code toolkit.')
    sub = ap.add_subparsers(dest='command', required=True)
    p_install = sub.add_parser('install', help='install or update the toolkit')
    _common(p_install)
    p_install.add_argument('--dry-run', action='store_true')
    p_install.add_argument('-v', '--verbose', action='store_true')
    p_install.add_argument('--allow-contract-failures', action='store_true')
    p_install.set_defaults(func=cmd_install)
    p_un = sub.add_parser('uninstall', help='remove what the last install wrote and restore backups')
    p_un.add_argument('--target')
    p_un.add_argument('--dry-run', action='store_true')
    p_un.set_defaults(func=cmd_uninstall)
    p_status = sub.add_parser('status', help='what is installed and what an install would change')
    _common(p_status)
    p_status.set_defaults(func=cmd_status)
    try:
        from . import contracts, drift, equivalence  # noqa: F401  (optional commands)
        contracts.register(sub, _common)
        drift.register(sub, _common)
        equivalence.register(sub, _common)
    except ImportError:
        pass
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ManifestError, OverrideError, SettingsError) as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2
