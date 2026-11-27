"""ASKDUE: the questions of the project's queue that must reach the developer before the final batch.

`ask-queue` decides what is blocking-due and whether the project's partial batch may be sent now
(`partial_batch_state`); this module only tells the lock owner, from the watcher (`wait --owner`, also on guard) and
from `beat`. The supervisor then sends the due items to its questions session, the way it sends a radical question.
Reading the queue is advisory: any failure gives no line and never changes what the caller prints or returns.
"""
import traceback

from . import cloud, providers, util

ASKDUE_POLL_S = 300                 # the watcher reads the queue at most this often
ASKDUE_REANNOUNCE_S = 6 * 3600      # an unchanged set of due ids is announced again after this long


def askdue_state(project):
    """ask-queue's partial batch state for the project's checkout, or None when the queue cannot be read."""
    try:
        queue = providers.ask_queue_module()
    except (OSError, ImportError):
        return None  # no queue installed (a bare HOME, a partial install): nothing to say
    try:
        return queue.partial_batch_state(queue.project_root(project['checkout']))
    except Exception:
        try:
            util.hook_log('askdue-errors.log', traceback.format_exc().rstrip())
        except OSError:
            pass
        return None


def askdue_line(project, state=None):
    """`ASKDUE <n> <ids> (…)` when the project's partial batch may be sent now, else None."""
    state = askdue_state(project) if state is None else state
    if not isinstance(state, dict) or not state.get('allowed') or not state.get('due'):
        return None
    ids = [str(i.get('id')) for i in state['due']]
    orders = sum(1 for i in state['due'] if i.get('due_reason') == 'order')
    why = (f'{orders} por bloquear una orden del desarrollador' if orders
           else 'todas por llevar tiempo bloqueando trabajo')
    return (f'ASKDUE {len(ids)} {",".join(ids)} (tanda parcial: {len(ids)} pregunta(s) de la cola sin presentar, {why}. '
            f'Míralas con `~/.claude/scripts/ask-queue list --due --project "{project["checkout"]}"`, márcalas con '
            f'`ask-queue asked <ids> --to <sesión de preguntas>` y mándalas juntas a tu sesión de preguntas, como un '
            f'radical; lo afectado se aparca y lo demás sigue. Mientras no se le presenten, nada dice que espera su '
            f'respuesta (f5-decisiones.md, «Antes del final»))')


def askdue_events(project, now=None):
    """The ASKDUE line through announce_once: once per set of due ids, again after ASKDUE_REANNOUNCE_S."""
    state = askdue_state(project)
    line = askdue_line(project, state) if state else None
    if not line:
        return []
    pair = ','.join(sorted(str(i.get('id')) for i in state['due']))
    return cloud.announce_once(project['key'], 'askdue', [(pair, line)], ASKDUE_REANNOUNCE_S, now)
