"""Work left in a project and the rules of a supervisor on guard."""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime

from . import census, closing, language, lint, lock as lock_mod, projects, providers, util


# ---------------------------------------------------------------- work left: the backlog and the guard
# A supervisor on guard while documented work is left is a stopped supervisor. Three controls check it:
#   - `backlog`: the open tasks of the project's OpenSpec changes, read from disk. Each change with open tasks is WORK
#     until it is done or parked with a kind and a reason (it expires, so a third party is asked again).
#   - `beat --phase guardia` refuses (7) while there is WORK, while a message of the developer on guard has no outcome,
#     or while the registry has no guard section (settings.GUARD_SECTION); the Stop hook blocks a guard in the same
#     cases.
#   - a message the developer types to a supervisor on guard is an order until it leaves guard or records
#     `beat --no-work`.
BACKLOG_KINDS = ('tercero', 'limite-duro', 'protegido', 'superado')
BACKLOG_PARK_H = 72
BACKLOG_PARK_MAX_H = 336
BACKLOG_WHY_MIN = 20
BACKLOG_REANNOUNCE_S = 6 * 3600
GUARD_SECTION_MIN_LINES = 4
_RE_OPEN_TASK = re.compile(r'^\s*[-*]\s+\[ \]\s+(\S.*)$', re.M)


def on_guard(owner):
    return str((owner or {}).get('phase') or '').strip().lower().startswith('guardia')


def backlog_items(checkout):
    """[{id, open, first, digest}] for every OpenSpec change with unchecked tasks under `checkout` (or, for a folder
    that groups repositories, under its direct subfolders). Archived changes do not count. Never raises."""
    out = []
    try:
        root = os.path.realpath(checkout or '')
        bases = [('', root)]
        if not os.path.isdir(os.path.join(root, 'openspec', 'changes')):
            bases = [(name + ':', os.path.join(root, name)) for name in sorted(os.listdir(root))
                     if os.path.isdir(os.path.join(root, name, 'openspec', 'changes'))]
        for prefix, base in bases:
            for tasks in sorted(glob.glob(os.path.join(glob.escape(base), 'openspec', 'changes', '*', 'tasks.md'))):
                name = os.path.basename(os.path.dirname(tasks))
                if name == 'archive':
                    continue
                try:
                    with open(tasks, encoding='utf-8', errors='replace') as fh:
                        lines = [' '.join(m.split()) for m in _RE_OPEN_TASK.findall(fh.read())]
                except OSError:
                    continue
                if lines:
                    digest = hashlib.sha1('\n'.join(lines).encode()).hexdigest()[:12]
                    out.append({'id': prefix + name, 'open': len(lines), 'first': lines[0][:120], 'digest': digest})
    except Exception:
        try:
            util.hook_log('hook-errors.log', 'backlog\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
    return out


USAGE_WATCH = '~/.claude/scripts/usage-watch'   # module `usage`, optional: without it there are no USAGE lines
USAGE_TIMEOUT_S = 8


def usage_items(checkout):
    """Authorised usage-watch findings of the project that its supervisor applies (usage-watch, design D10), as backlog
    work: [{id, open, first, digest, usage: True}]. Each stays work until `usage-watch apply ID --how TEXT`. Without
    the script, or when it fails, nothing is added and the failure is logged, never raised."""
    script = os.path.expanduser(USAGE_WATCH)
    if not os.path.isfile(script):
        return []
    try:
        r = subprocess.run([sys.executable, script, 'list', '--project', os.path.realpath(checkout or ''), '--state',
                            'authorized', '--applier', 'project-supervisor', '--json'],
                           capture_output=True, text=True, timeout=USAGE_TIMEOUT_S)
        if r.returncode != 0:
            raise RuntimeError(f'usage-watch list exit {r.returncode}: {r.stderr.strip()[:300]}')
        found = json.loads(r.stdout or '[]')
        out = []
        for f in found if isinstance(found, list) else []:
            if not isinstance(f, dict) or not isinstance(f.get('id'), str):
                continue
            text = ' '.join(str((f.get('proposal') or {}).get('text') or '').split())
            out.append({'id': f['id'], 'open': 1, 'first': f'{f.get("rule")}: {text}'[:200],
                        'digest': hashlib.sha1(f['id'].encode()).hexdigest()[:12], 'usage': True})
        return out
    except Exception:
        try:
            util.hook_log('hook-errors.log', 'backlog usage-watch\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
        return []


def backlog_path(key):
    return os.path.join(util.home(), 'backlog', f'{key}.json')


def backlog_state(key, checkout, now=None):
    """(work, parked): changes with open tasks that nobody parked, and the parked ones with their record. A park is
    void once it expires or once the open tasks of the change are no longer the ones it was written for."""
    now = time.time() if now is None else now
    parks = util.read_json(backlog_path(key), {})
    parks = parks if isinstance(parks, dict) else {}
    work, parked = [], []
    for item in backlog_items(checkout):
        park = parks.get(item['id'])
        if (isinstance(park, dict) and park.get('digest') == item['digest'] and (util.num(park.get('until')) or 0) > now):
            parked.append(dict(item, **{k: park.get(k) for k in ('kind', 'why', 'until')}))
        else:
            work.append(item)
    work += usage_items(checkout)   # never parked: applying the finding is what ends it
    return work, parked


def backlog_lines(work, parked):
    lines = [f'USAGE {w["id"]} {w["first"]}' if w.get('usage') else f'WORK {w["id"]} open={w["open"]} «{w["first"]}»'
             for w in work]
    lines += [f'PARKED {p["id"]} as={p["kind"]} open={p["open"]} '
              f'until={datetime.fromtimestamp(p["until"]).strftime("%d-%m %H:%M")} «{p["why"]}»' for p in parked]
    return lines


def cmd_backlog(args):
    project = projects.resolve(args.dir)
    key = project['key']
    if args.park or args.unpark:
        with lock_mod.Store() as store:
            owner = store.read(key)
            if owner is None or owner.get('session_id') != args.session:
                return lock_mod.not_owner(key)
            parks = util.read_json(backlog_path(key), {})
            parks = parks if isinstance(parks, dict) else {}
            if args.unpark:
                parks.pop(args.unpark, None)
            else:
                item = next((i for i in backlog_items(project['checkout']) if i['id'] == args.park), None)
                if item is None:
                    print(f'NOT FOUND {args.park}: no es un change con tareas abiertas', file=sys.stderr)
                    return 2
                why = ' '.join((args.why or '').split())
                folded = util.fold_text(why)
                words = language._RE_WORD.findall(folded)
                if (sum(w in language._EN_WORDS for w in words) >= 3
                        and sum(w in language._EN_WORDS for w in words) > sum(w in language._ES_WORDS for w in words)):
                    print('IN ENGLISH: el motivo lo lee el desarrollador en la tanda final: escríbelo en español.', file=sys.stderr)
                    return 2
                if re.search(r'\ben (vuelo|marcha|curso|cola)\b|\bin (flight|progress)\b|\bse revisa al acabar\b', folded):
                    print('IN FLIGHT: lo que está en marcha, en cola o esperando a tu propio deploy no se aparca: es '
                          'trabajo en vuelo (registro, «Trabajo en vuelo»). Se aparca solo lo que ningún agente puede hacer.',
                          file=sys.stderr)
                    return 2
                if args.kind not in BACKLOG_KINDS or len(why) < BACKLOG_WHY_MIN:
                    print(f'USAGE: --as {"|".join(BACKLOG_KINDS)} --why "<qué falta, de quién depende y qué comprobaste; '
                          f'{BACKLOG_WHY_MIN} caracteres o más>"', file=sys.stderr)
                    return 2
                default_h = BACKLOG_PARK_MAX_H if args.kind in ('limite-duro', 'protegido') else BACKLOG_PARK_H
                hours = max(1.0, min(float(args.hours if args.hours is not None else default_h), BACKLOG_PARK_MAX_H))
                parks[item['id']] = {'kind': args.kind, 'why': why[:400], 'digest': item['digest'],
                                     'until': time.time() + hours * 3600, 'at': util.now_iso(), 'by': args.session}
            os.makedirs(os.path.dirname(backlog_path(key)), exist_ok=True)
            util.write_json_atomic(backlog_path(key), parks)
    work, parked = backlog_state(key, project['checkout'])
    if getattr(args, 'json', False):
        print(json.dumps({'work': work, 'parked': parked}, ensure_ascii=False))
    else:
        for line in backlog_lines(work, parked):
            print(line)
        print(f'BACKLOG work={len(work)} parked={len(parked)}')
    return 7 if work else 0


def guard_section_ok(owner):
    """True when the registry of the lock explains the guard: a section headed settings.GUARD_SECTION with at least
    GUARD_SECTION_MIN_LINES lines. True also when the registry cannot be read (never blocks on a missing file)."""
    path = owner.get('registry') or ''
    try:
        # the lock keeps the registry of the cycle that took it; each later cycle opens a new SUPERVISOR-<stamp>.md
        # next to it without `acquire`, so the one that counts is the newest of the folder
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        files = sorted(glob.glob(os.path.join(glob.escape(folder), 'SUPERVISOR-*.md')), key=util.file_mtime) if folder else []
        if files:
            path = files[-1]
        if not path or not os.path.isfile(path):
            return True
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return True
    head = util.fold_text(lint.GUARD_SECTION)
    section = None
    for line in text.splitlines():
        if util.fold_text(line).strip().startswith(head):
            section = []
        elif section is not None:
            if line.startswith('## '):
                break
            if line.strip():
                section.append(line)
    return section is not None and len(section) >= GUARD_SECTION_MIN_LINES


def guard_refusal(owner, local):
    """Why this lock may not be (or stay) on guard, as text for the supervisor, or ''. Never raises."""
    try:
        if providers.pause_of(owner.get('checkout')):
            return ''
        order = owner.get('guard_order')
        if isinstance(order, dict) and order.get('text'):
            return (f'el desarrollador te escribió estando de guardia [{order.get("at")}] «{order.get("text")}» y no '
                    f'consta qué hiciste con ello. Si pide trabajo, lo da por supuesto o describe lo que espera recibir, '
                    f'es la orden que abre el ciclo siguiente: `supervisor-lock beat --session {local} --phase F1`, un '
                    f'registro nuevo con ese objetivo y el primer paso lanzado en este turno. Solo si no pide ni implica '
                    f'trabajo (un agradecimiento, una confirmación sin más, una pregunta que ya contestaste): '
                    f'`supervisor-lock beat --session {local} --no-work "<por qué ese mensaje no pide trabajo>"`. '
                    f'Anotarlo como decisión y seguir de guardia deja su mensaje sin atender')
        work, _ = backlog_state(owner.get('key'), owner.get('checkout'))
        if work:
            listed = '; '.join(f'{w["id"]} ({w["open"]} tareas; la primera: «{w["first"]}»)' for w in work[:6])
            more = f' y {len(work) - 6} más' if len(work) > 6 else ''
            return (f'el proyecto tiene trabajo documentado sin hacer: {listed}{more}. La guardia es para cuando no queda '
                    f'nada que una sesión pueda hacer. Sal de guardia (`supervisor-lock beat --session {local} --phase '
                    f'F1`) y lánzalo en este turno, lo que se pueda en paralelo. Lo que de verdad no puedas hacer se '
                    f'aparca change a change, con lo que comprobaste: `supervisor-lock backlog --session {local} --park '
                    f'<change> --as {"|".join(BACKLOG_KINDS)} --why "<qué falta, de quién depende, qué probaste>"` '
                    f'(caduca a las {BACKLOG_PARK_H} h, para volver a mirarlo). «tercero» y «limite-duro» son para lo '
                    f'que ningún agente puede hacer con navegador, emulador, ssh, cuentas de prueba o una API ya '
                    f'configurada; si solo una parte del change depende de otro, se hace el resto')
        if not guard_section_ok(owner):
            return (f'tu registro no explica la guardia. Antes de quedarte de guardia recorres, por este orden, de dónde '
                    f'puede salir trabajo y lo escribes en una sección «{lint.GUARD_SECTION}» del registro, una línea por '
                    f'fuente con lo que miraste: (1) sus mensajes en tu sesión desde el ciclo anterior; (2) sus respuestas '
                    f'a la tanda final; (3) `supervisor-lock backlog`; (4) la meta escrita del proyecto (CLAUDE.md, README, '
                    f'su estado y su registro de decisiones) y el siguiente paso hacia ella. Si alguna da trabajo que '
                    f'una sesión puede hacer, no hay guardia: es el ciclo siguiente. Si de la meta sale un paso pero no '
                    f'está escrito cuál, lo elige el panel')
    except Exception:
        try:
            util.hook_log('hook-errors.log', 'guard-refusal\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
    return ''


IDLE_BLOCK_EVERY_S = 30 * 60
_WAIT_ONLY = ('supervisor-lock wait', 'heavy-job', 'cloud-tests wait', 'cloud-tests request', 'sleep ')


def idle_block(owner, local, payload):
    """Stop-hook reason for a supervisor in a cycle when nobody is working (no busy session of the project, no
    subagent or command of its own other than waits) while changes with open tasks are left; '' otherwise. A
    supervisor that reports a wait (the machine queue, a test, a child session) instead of launching what does not
    depend on it is idle. At most once per IDLE_BLOCK_EVERY_S per lock."""
    try:
        if on_guard(owner) or providers.pause_of(owner.get('checkout')):
            return ''
        tasks = payload.get('background_tasks')
        if not isinstance(tasks, list):
            return ''  # the app did not say what it has running: never guess
        for task in tasks:
            if not isinstance(task, dict) or str(task.get('status') or 'running').lower() not in ('running', 'pending'):
                continue
            text = ' '.join(str(task.get(f) or '') for f in ('command', 'description'))
            if str(task.get('type') or '').lower() != 'shell' or not any(w in text for w in _WAIT_ONLY):
                return ''  # a subagent, or a command that is not a wait: somebody is working
        stamp = os.path.join(util.home(), 'backlog', (owner.get('key') or 'lock') + '.idle-blocked')
        if time.time() - util.file_mtime(stamp) < IDLE_BLOCK_EVERY_S:
            return ''
        work, _ = backlog_state(owner.get('key'), owner.get('checkout'))
        if not work:
            return ''
        project = projects.resolve(owner.get('checkout'))
        mine = {local, owner.get('session_id')}
        for row in census.collect_sessions(project, False, {}):
            if row['id'] in mine or row.get('cli') in mine or closing.is_helper_row(row, owner):
                continue
            if row.get('live') and row.get('status') == 'busy':
                return ''
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        open(stamp, 'w').close()
        listed = '; '.join(f'{w["id"]} ({w["open"]}; «{w["first"][:80]}»)' for w in work[:6])
        more = f' y {len(work) - 6} más' if len(work) > 6 else ''
        return (f'Antes de terminar el turno: en {owner.get("project")} no trabaja nadie ahora mismo (ninguna sesión del '
                f'proyecto ocupada, ningún subagente tuyo; solo esperas) y quedan {len(work)} change(s) con tareas '
                f'abiertas sin aparcar: {listed}{more}. Esperar no es trabajar: lo que esperas (la cola de la máquina, un '
                f'test, una respuesta) no ocupa a nadie. Lanza en este turno lo que no dependa de ello, con subagentes '
                f'(`Agent`) o una sesión parada del proyecto, empezando por lo que más acerca la meta. Lo que ningún '
                f'agente puede hacer se aparca con lo que comprobaste (`supervisor-lock backlog --session {local} --park '
                f'<change> --as … --why "…"`). Una supervisora actúa sin parar mientras quede trabajo, sin esperar a nadie.')
    except Exception:
        try:
            util.hook_log('hook-errors.log', 'idle-block\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
        return ''


def guard_block(owner, local):
    """Stop-hook reason for a supervisor on guard that has work left, or ''."""
    if not on_guard(owner):
        return ''
    why = guard_refusal(owner, local)
    if not why:
        return ''
    return (f'Antes de terminar el turno: estás de guardia en {owner.get("project")} y {why}. De guardia con trabajo '
            f'pendiente es estar parada: lo primero es actuar, sin esperar al desarrollador.')
