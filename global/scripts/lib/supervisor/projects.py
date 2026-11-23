"""Which project a directory belongs to: repository, workspace, names, matcher."""
import hashlib
import json
import os
import subprocess
import sys

from . import util


def git(args, cwd):
    out = subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def common_dir_of(directory):
    """Absolute git common dir of a directory, or None when it is not inside a git repo."""
    if not os.path.isdir(directory):
        return None
    common = git(['rev-parse', '--path-format=absolute', '--git-common-dir'], directory)
    return os.path.realpath(common) if common else None


def is_home_or_above(directory):
    """True for $HOME and every folder that contains it (/, /home): never a workspace."""
    home_dir = os.path.realpath(os.path.expanduser('~'))
    return directory == home_dir or home_dir.startswith(directory.rstrip('/') + '/')


def workspace_marks(directory):
    """A non-git folder that groups projects: CLAUDE.md, openspec/, or a subfolder that is a git repo."""
    if os.path.exists(os.path.join(directory, 'CLAUDE.md')) or os.path.isdir(os.path.join(directory, 'openspec')):
        return True
    try:
        return any(os.path.exists(os.path.join(entry.path, '.git')) for entry in os.scandir(directory) if entry.is_dir())
    except OSError:
        return False


def resolve(directory):
    directory = os.path.realpath(directory or os.getcwd())
    common = common_dir_of(directory)
    if common:
        checkout = os.path.dirname(common) if os.path.basename(common) == '.git' else common
        name = os.path.basename(checkout)
        digest = hashlib.sha1(common.encode()).hexdigest()[:8]
        return {
            'kind': 'git',
            'key': f'{name}-{digest}',
            'name': name,
            'checkout': checkout,
            'common_dir': common,
            'registry_dir': os.path.join(checkout, '.claude', 'context', 'supervisor'),
        }
    if os.path.isdir(directory) and not is_home_or_above(directory) and workspace_marks(directory):
        name = os.path.basename(directory)
        return {
            'kind': 'workspace',
            'key': f'{name}-{hashlib.sha1(directory.encode()).hexdigest()[:8]}',
            'name': name,
            'checkout': directory,
            'common_dir': None,
            'registry_dir': os.path.join(directory, '.claude', 'context', 'supervisor'),
        }
    util.die(f'NOT A GIT REPOSITORY: {directory}')


# ---------------------------------------------------------------- subcommands

def cmd_project(args):
    project = resolve(args.dir)
    if args.json:
        print(json.dumps(project, indent=2, sort_keys=True))
    else:
        for field in ('kind', 'key', 'name', 'checkout', 'common_dir', 'registry_dir'):
            print(f'{field}={project[field] if project[field] is not None else "-"}')
    return 0


def cmd_registry_dir(args):
    project = resolve(args.dir)
    os.makedirs(project['registry_dir'], exist_ok=True)
    if project['kind'] == 'workspace':
        print(f'supervisor-lock: {project["checkout"]} is a workspace (not a git repo): nothing to git-exclude',
              file=sys.stderr)
        print(project['registry_dir'])
        return 0
    probe = '.claude/context/supervisor/probe.md'
    ignored = subprocess.run(['git', '-C', project['checkout'], 'check-ignore', '-q', probe]).returncode == 0
    if not ignored:
        exclude = os.path.join(project['common_dir'], 'info', 'exclude')
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        line = '/.claude/context/supervisor/'
        existing = open(exclude).read() if os.path.exists(exclude) else ''
        if line not in existing.splitlines():
            with open(exclude, 'a') as fh:
                fh.write(('' if not existing or existing.endswith('\n') else '\n') + line + '\n')
            print(f'supervisor-lock: added {line} to {exclude}', file=sys.stderr)
    print(project['registry_dir'])
    return 0


def project_names(project):
    """Project name plus the folder names of all its worktrees: what heavy-job slot lines mention."""
    names = {project['name']}
    repos = [project['checkout']]
    if project['kind'] == 'workspace':
        try:
            repos = [e.path for e in os.scandir(project['checkout']) if e.is_dir() and os.path.exists(os.path.join(e.path, '.git'))]
        except OSError:
            repos = []
        names.update(os.path.basename(path) for path in repos)
    for repo in repos:
        listing = git(['worktree', 'list', '--porcelain'], repo) or ''
        names.update(os.path.basename(line[9:].rstrip('/')) for line in listing.splitlines() if line.startswith('worktree '))
    return {n for n in names if n}


def project_dir_matcher(project):
    """cwd -> True when it is the project's checkout, one of its worktrees or a folder inside them."""
    cache = {}
    root = project['checkout']

    def inside(path):
        return path == root or path.startswith(root + '/')

    def match(cwd):
        if not isinstance(cwd, str) or not cwd:
            return False
        real = os.path.realpath(cwd)
        if inside(real):
            return True
        if real not in cache:
            cache[real] = common_dir_of(real) if os.path.isdir(real) else None
        common = cache[real]
        if not common:
            return False
        return inside(common) if project.get('kind') == 'workspace' else common == project.get('common_dir')
    return match
