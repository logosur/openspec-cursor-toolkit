"""Protocol values of the supervision, read once from the config piece `supervision`.

The toolkit ships neutral defaults (global/config/supervision.json, repeated in DEFAULTS); the user's override sets the
real ones. A missing, corrupt or mistyped file gives these defaults (toolkit_config.load_checked), never more
permission. Environment variables keep their priority where a piece reads one. Nothing else in the package imports
from the package at import time, so this module can be read first by any of them.
"""
import math
import os
import sys

_LIB = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # scripts/lib: toolkit_config
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
try:
    from toolkit_config import load_checked as _load_config
except ImportError:  # a copy of the package without the toolkit library: the defaults
    def _load_config(piece, defaults):
        return dict(defaults)

DEFAULTS = {
    'account_switch_marker': '[cambio de cuenta]',
    'supervisor_revive_marker': '[reanimar supervisora]',
    'supervisor_revive_valid_s': 1800,
    'presence_min': 20,
    'fresh_min': 3,
    'queued_reannounce_min': 120,
    'slotheld_reannounce_min': 120,
    'all_idle_backoff_max_min': 120,
    'app_sessions_dir': '~/.config/Claude/claude-code-sessions',
    'questions_session_titles': ['sesión de preguntas', 'preguntas de la supervisión', 'buzón de preguntas'],
    'questions_session_title': 'Sesión de preguntas de {project}',
    'closer_session_titles': ['cierre de sesiones de'],
    'skill_file': '~/.claude/skills/supervisa-sesiones/SKILL.md',
    'guard_section': '## Motivo de la guardia',
    'skill_anchors': ['## Prohibido', '## §0', '## Nunca parada', '$L backlog', '$L wait-closer',
                      '--no-work', 'en español', 'reference/cambios.md'],
    'skill_lint_roots': [],
    'reload_globs': ['~/.claude/skills/*/SKILL.md', '~/.claude/skills/*/reference/*.md', '~/.claude/rules/*.md',
                     '~/.claude/scripts/supervisor-lock', '~/.claude/scripts/lib/supervisor/*.py'],
    'deploy_rule': 'despliegue-y-limites-duros.md',
    'deploy_preauthorised': False,
    'excluded_projects': [],
    'archive_preauthorised': False,
    'decision_criterion': 'la opción mejor fundada en lo documentado (ante la duda, la más reversible)',
}
CONFIG = _load_config('supervision', DEFAULTS)

# markers of automatic messages (the first one also tells an automatic turn from the developer's)
ACCOUNT_SWITCH_MARKER = CONFIG['account_switch_marker']
REVIVE_MARKER = CONFIG['supervisor_revive_marker']
REVIVE_VALID_S = CONFIG['supervisor_revive_valid_s']   # how long a revive plan lets its marker through

# presence: minutes of the developer's input that count as "here", and how fresh a message alone allows a question
PRESENCE_MIN = CONFIG['presence_min']
FRESH_MIN = CONFIG['fresh_min']



def _positive(key):
    """A positive finite number of the piece, else the default (load_checked already refused other shapes)."""
    value = CONFIG[key]
    return value if math.isfinite(value) and value > 0 else DEFAULTS[key]


# how often the watcher repeats an unchanged item, and how far ALLIDLE backs off while nothing moves (minutes)
QUEUED_REANNOUNCE_MIN = _positive('queued_reannounce_min')
SLOTHELD_REANNOUNCE_MIN = _positive('slotheld_reannounce_min')
ALL_IDLE_BACKOFF_MAX_MIN = _positive('all_idle_backoff_max_min')

# the app's session records (one json per session under <dir>/<account>/<org>/)
APP_SESSIONS_GLOB = os.path.join(CONFIG['app_sessions_dir'], '*', '*', 'local_*.json')

# the supervisor's fixed child sessions, recognised by title (case and accents folded)
QUESTIONS_TITLES = tuple(CONFIG['questions_session_titles'])
CLOSER_TITLES = tuple(t.lower() for t in CONFIG['closer_session_titles'])


def questions_title(project):
    """The title a supervisor gives to the questions session of `project`."""
    return CONFIG['questions_session_title'].replace('{project}', str(project))


# the skill a supervisor runs on, the anchors its core must keep and what else its lint reads
SKILL_FILE = CONFIG['skill_file']
GUARD_SECTION = CONFIG['guard_section']
SKILL_ANCHORS = tuple(CONFIG['skill_anchors'][:5]) + (GUARD_SECTION,) + tuple(CONFIG['skill_anchors'][5:])
SKILL_LINT_ROOTS = tuple(CONFIG['skill_lint_roots'])
# what a skill reload covers: a change to any of these files after a supervisor last loaded the skill is an update it
# has not read (the message gate lets a reload order through for it, and `beat --skill-seen` asks for a newer load)
RELOAD_GLOBS = tuple(CONFIG['reload_globs'])

# deploys: the rule that says who may deploy, and whether the developer has authorised them in writing
DEPLOY_RULE = '~/.claude/rules/' + CONFIG['deploy_rule']
DEPLOY_PREAUTHORISED = CONFIG['deploy_preauthorised']
EXCLUDED_PROJECTS = tuple(CONFIG['excluded_projects'])   # never deployed without the developer, even when authorised

# archiving finished sessions: only with the developer's written authorisation; otherwise it is queued for them
ARCHIVE_PREAUTHORISED = CONFIG['archive_preauthorised']
# how a session chooses when the documented sources do not settle a doubt (the text the deny messages quote)
DECISION_CRITERION = CONFIG['decision_criterion']
QUEUED_MARK = 'ask-queue'   # a hold whose reason names it parks a session whose archiving waits in the queue


def archive_queued(hold):
    """True when a hold says the archiving decision is queued for the developer."""
    return isinstance(hold, dict) and QUEUED_MARK in str(hold.get('reason') or '')
