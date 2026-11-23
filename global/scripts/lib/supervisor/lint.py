"""The skill file a supervisor runs on: freshness and lint."""
import glob
import os
import re
from datetime import datetime

from . import lock as lock_mod, settings, util


def skill_file():
    return os.path.expanduser(os.environ.get('SUPERVISOR_SKILL_FILE', settings.SKILL_FILE))


def skill_mtime():
    """Newest mtime (float) of the skill file and of reference/*.md next to it, or None when SKILL.md is missing."""
    try:
        newest = os.stat(skill_file()).st_mtime
    except OSError:
        return None
    for path in glob.glob(os.path.join(glob.escape(os.path.dirname(skill_file())), 'reference', '*.md')):
        newest = max(newest, util.file_mtime(path))
    return newest


GUARD_SECTION = settings.GUARD_SECTION


# ---------------------------------------------------------------- skill lint
# Fixes to the skill tend to grow its core past the 20,000 characters the app keeps after a compaction (the cut then
# falls before the sections that must survive it), and to leave in the detail files the text a fix replaced.
# `skill-lint` fails on both, and the self-test runs it on the installed skill.
SKILL_CORE_MAX_CHARS = 17500      # the body, without the frontmatter
SKILL_FILE_MAX_BYTES = 20000      # the whole file: the strictest reading of «the first 20,000»
SKILL_ANCHORS = settings.SKILL_ANCHORS   # what the core must keep within the part a compaction keeps
SKILL_STALE = (
    (r'TANDA FINAL`? y libera el cerrojo', 'tras la tanda final no se libera el cerrojo: se queda de guardia'),
    (r'el cerrojo sin liberar', 'el cerrojo no se libera al terminar: guardia'),
    (r'ni aunque (?:[eé]l )?acabe de escribir', 'una sesión que el desarrollador lleva en persona sí puede preguntarle'),
    (r'tambi[eé]n la deniega\s+aunque haya escrito', 'con el desarrollador delante la pregunta pasa'),
    (r'Al recargarla tras el (?:segundo )?cambio', 'los pasos de recarga van en reference/cambios.md, no en el núcleo'),
)


def lint_roots():
    env = os.environ.get('SUPERVISOR_LINT_ROOTS')
    if env is not None:
        return [p for p in env.split(os.pathsep) if p]
    claude = os.path.expanduser('~/.claude')
    return [os.path.dirname(skill_file()), os.path.join(claude, 'rules'),
            os.path.join(claude, 'commands', 'supervisa-sesiones.md')] + [os.path.expanduser(p) for p in settings.SKILL_LINT_ROOTS]


def skill_lint():
    """Problems of the installed skill, as lines; [] when it is sound."""
    problems = []
    path = skill_file()
    try:
        raw = open(path, 'rb').read()
    except OSError:
        return [f'MISSING {path}']
    text = raw.decode('utf-8', errors='replace')
    body = text.split('\n---\n', 1)[1] if text.startswith('---\n') and '\n---\n' in text else text
    if len(body) > SKILL_CORE_MAX_CHARS:
        problems.append(f'CORE_TOO_LONG {len(body)} caracteres de núcleo (máximo {SKILL_CORE_MAX_CHARS})')
    if len(raw) > SKILL_FILE_MAX_BYTES:
        problems.append(f'FILE_TOO_LONG {len(raw)} bytes (máximo {SKILL_FILE_MAX_BYTES}: la app corta ahí al compactar)')
    kept = raw[:SKILL_FILE_MAX_BYTES].decode('utf-8', errors='replace')
    for anchor in SKILL_ANCHORS:
        if anchor not in kept:
            problems.append(f'ANCHOR_MISSING «{anchor}» no está en la parte del núcleo que sobrevive a una compactación')
    for ref in sorted(set(re.findall(r'reference/[\w.-]+\.md', text))):
        if not os.path.isfile(os.path.join(os.path.dirname(path), ref)):
            problems.append(f'REFERENCE_MISSING {ref}')
    files = []
    for root in lint_roots():
        if os.path.isfile(root):
            files.append(root)
        else:
            files += [f for f in glob.glob(os.path.join(glob.escape(root), '**', '*.md'), recursive=True)]
    for name in sorted(set(files)):
        if '.bak' in os.path.basename(name) or os.path.basename(name) == 'cambios.md':
            continue  # a history of the fixes quotes what each one replaced
        try:
            content = open(name, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for pattern, why in SKILL_STALE:
            for m in re.finditer(pattern, content, re.I):
                line = content.count('\n', 0, m.start()) + 1
                problems.append(f'STALE {name}:{line} «{m.group(0)}»: {why}')
    return problems


def cmd_skill_lint(args):
    problems = skill_lint()
    for line in problems:
        print(line)
    print(f'SKILL_LINT {"FAIL" if problems else "ok"} {len(problems)}')
    return 1 if problems else 0


def skill_newer(lock):
    """mtime of the skill file when the lock's owner has not read it or read an older version (`skill_seen`).

    Without `skill_seen` the owner never read it (acquire/reclaim do not record it): any existing skill file counts.
    """
    mtime = skill_mtime()
    if mtime is None:
        return None
    seen = util.num(lock.get('skill_seen'))
    return mtime if seen is None or mtime > seen + 1e-6 else None


def skill_changed_line(project, owner_id):
    """SKILL_CHANGED line when `owner_id` holds the project lock and the skill file is newer than what it has read."""
    lock = lock_mod.Store().read(project['key'])
    if lock is None or lock.get('session_id') != owner_id:
        return None
    mtime = skill_newer(lock)
    if mtime is None:
        return None
    stamp = datetime.fromtimestamp(mtime).astimezone().isoformat(timespec='seconds')
    if util.num(lock.get('skill_seen')) is None:
        return (f'SKILL_CHANGED {stamp} (the skill has not been read since the lock was taken: invoke supervisa-sesiones, '
                f'open the question mailbox (F0b-F0c), then: supervisor-lock beat --session {owner_id} --skill-seen)')
    return (f'SKILL_CHANGED {stamp} (re-invoke supervisa-sesiones and re-read the reference files you are using, then: '
            f'supervisor-lock beat --session {owner_id} --skill-seen)')
