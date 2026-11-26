"""Tests for global/scripts/handoff-guard (stops sessions from handing work back to the developer).

Every test runs in a temporary state dir, rules dir, app-sessions dir and config dir, with a temporary HOME, so nothing
of the machine is read or written. The Spanish matchers are the protocol and are tested as such; the values a machine
sets (deploy rule, question-session titles, wording of the reasons) are tested through the config pieces.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = os.environ.get('HANDOFF_GUARD_SCRIPT') or str(REPO_ROOT / 'global/scripts/handoff-guard')
STOP_GATE = str(REPO_ROOT / 'global/hooks/supervisor-stop-gate')

HANDS_BACK = 'Todo desplegado. La prueba final con tu cuenta queda para ti.'
CLEAN = 'Hecho: 3 commits integrados en la rama principal y verificados en el navegador.'


def load_module(env=None):
    with mock.patch.dict(os.environ, env or {}):
        loader = importlib.machinery.SourceFileLoader('handoff_guard_under_test', SCRIPT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    return module


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='handoff-guard-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, 'home')
        self.state = os.path.join(self.tmp, 'state')
        self.rules = os.path.join(self.tmp, 'rules')
        self.app = os.path.join(self.tmp, 'app')
        self.cfg = os.path.join(self.tmp, 'cfg')
        for d in (self.home, self.rules, self.cfg, os.path.join(self.app, 'acct', 'org')):
            os.makedirs(d)
        self.env = dict(os.environ, HOME=self.home, HANDOFF_GUARD_HOME=self.state, HANDOFF_GUARD_RULES_DIR=self.rules,
                        HANDOFF_GUARD_APP_GLOB=os.path.join(self.app, '*', '*', 'local_*.json'),
                        CLAUDE_TOOLKIT_CONFIG_DIR=self.cfg)
        self.env.pop('HANDOFF_GUARD', None)
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.counter = 0

    def config(self, piece, data):
        with open(os.path.join(self.cfg, piece + '.json'), 'w') as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def module(self):
        """The script, read with the config written so far."""
        return load_module(self.env)

    def session(self, mod=None):
        self.counter += 1
        sid = f'sess-{self.counter:04d}-test'
        if mod:
            mod.hook_decide(json.dumps({'hook_event_name': 'SessionStart', 'session_id': sid}))
        return sid

    def touch_rule(self, name, when=None):
        path = os.path.join(self.rules, name)
        with open(path, 'w') as fh:
            fh.write('# rule\n')
        when = when if when is not None else time.time() - 1000
        os.utime(path, (when, when))
        return path

    def run_cli(self, *args, stdin='', env=None):
        return subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True, text=True,
                              env=env or self.env, timeout=30)

    @staticmethod
    def stop(mod, sid, text=None, **extra):
        payload = {'hook_event_name': 'Stop', 'session_id': sid, 'stop_hook_active': False}
        if text is not None:
            payload['last_assistant_message'] = text
        payload.update(extra)
        return mod.hook_decide(json.dumps(payload))

    @staticmethod
    def ask(mod, sid, questions):
        return mod.hook_decide(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'AskUserQuestion',
                                           'session_id': sid, 'tool_input': {'questions': questions}}))

    @staticmethod
    def blocked(out):
        return bool(out) and json.loads(out).get('decision') == 'block'

    @staticmethod
    def denied(out):
        return bool(out) and json.loads(out)['hookSpecificOutput']['permissionDecision'] == 'deny'

    def write_ficha(self, session, title, name='local_a.json'):
        with open(os.path.join(self.app, 'acct', 'org', name), 'w') as fh:
            json.dump({'sessionId': 'local_' + name, 'cliSessionId': session, 'title': title}, fh)


class PatternTests(Sandbox):
    """The matchers are the protocol: they do not depend on any config."""

    def test_phrases_that_hand_work_back_hit(self):
        mod = self.module()
        for phrase in ('esto queda para ti', 'te toca a ti', 'depende de ti', 'es cosa tuya', 'por tu parte',
                       'el despliegue es tuyo', 'con tu cuenta', 'con tus móviles', 'en tus dispositivos',
                       'cuenta real', 'dispositivos reales', 'necesito que pruebes esto',
                       'hace falta que subas el APK', 'tendrás que probar la app', 'espero tu confirmación',
                       'a la espera de que contestes', 'quedo a la espera', 'en cuanto me confirmes',
                       'cuando me lo digas, sigo con el resto', 'READY TO DEPLOY', 'listo para desplegar',
                       'cuando puedas', 'avísame', 'dime si funciona', '¿quieres que despliegue?',
                       'si quieres, puedo hacerlo', '¿lo hago?', 'pendientes de ti'):
            self.assertTrue(mod.find_matches(phrase), phrase)

    def test_the_stop_verdict_that_hands_work_back_hits_several_fragments(self):
        mod = self.module()
        verdict = ('PREPROD DEPLOYED — TANDA FINAL. Todo integrado y desplegado. '
                   'La publicación real con tu cuenta y en tus teléfonos queda para ti.')
        self.assertGreaterEqual(len(mod.find_matches(verdict)), 3)

    def test_a_normal_closing_does_not_hit(self):
        mod = self.module()
        self.assertEqual(mod.find_matches(CLEAN), [])
        self.assertEqual(mod.find_matches('En espera, no parada: el vigilante me despierta a las 20:40. '
                                          'Nada que pedirte ni que esperar.'), [])

    def test_code_blocks_quotes_and_guillemets_are_not_the_authors_voice(self):
        mod = self.module()
        self.assertEqual(mod.find_matches('Salida:\n```\nqueda para ti\n```\nFin.'), [])
        self.assertEqual(mod.find_matches('Cita:\n> te toca a ti\nFin.'), [])
        self.assertEqual(mod.find_matches('La regla dice «lo que sigue queda para ti» y la cumplo.'), [])
        self.assertTrue(mod.find_matches('**queda** _para ti_'))

    def test_accents_do_not_matter(self):
        mod = self.module()
        for a, b in (('avisame', 'avísame'), ('con tu movil', 'con tu móvil'), ('tendras que probar', 'tendrás que probar')):
            self.assertTrue(mod.find_matches(a) and mod.find_matches(b), a)

    def test_commit_message_questions_are_their_own_category(self):
        mod = self.module()
        for text in ('¿Qué mensaje de commit pongo?', 'elige el mensaje', 'mensaje de commit: elige el que prefieras'):
            self.assertIn('commit-message', [c for c, _f in mod.find_matches(text)], text)

    def test_soft_patterns_only_count_at_stop_and_ask_only_ones_only_in_dialogs(self):
        mod = self.module()
        self.assertTrue(mod.find_matches('¿quieres que despliegue?', 'stop'))
        self.assertFalse(mod.find_matches('¿quieres que despliegue?', 'ask'))
        self.assertFalse(mod.find_matches('saca tú la foto real', 'stop'))
        self.assertEqual(mod.find_matches('saca tú la foto real', 'ask')[0][0], 'ask')

    def test_overlapping_fragments_are_reported_once(self):
        mod = self.module()
        hits = mod.find_matches('esto queda para ti')
        self.assertEqual(len(hits), 1)


class StopTests(Sandbox):
    def test_a_handing_back_message_blocks_once_per_text(self):
        mod = self.module()
        sid = self.session(mod)
        out = self.stop(mod, sid, HANDS_BACK)
        self.assertTrue(self.blocked(out))
        self.assertIn('queda para ti', json.loads(out)['reason'])
        self.assertEqual(self.stop(mod, sid, HANDS_BACK), '')
        self.assertTrue(self.blocked(self.stop(mod, sid, 'Cuando puedas, dime qué cuenta usar.')))

    def test_clean_messages_empty_messages_and_an_active_stop_hook_never_block(self):
        mod = self.module()
        sid = self.session(mod)
        self.assertEqual(self.stop(mod, sid, CLEAN), '')
        self.assertEqual(self.stop(mod, sid, ''), '')
        self.assertEqual(self.stop(mod, sid, HANDS_BACK, stop_hook_active=True), '')

    def test_the_reason_is_spanish_and_points_to_ask_queue_and_the_deploy_rule(self):
        reason = json.loads(self.stop(self.module(), 'sess-r-test', HANDS_BACK))['reason']
        self.assertIn('Tu mensaje final parece devolverle trabajo', reason)
        self.assertIn('~/.claude/rules/despliegue-y-limites-duros.md', reason)
        self.assertIn('~/.claude/scripts/ask-queue add', reason)
        self.assertNotIn('{rule}', reason)

    def test_a_commit_message_question_says_the_session_writes_it(self):
        reason = json.loads(self.stop(self.module(), 'sess-c-test', '¿Qué mensaje de commit prefieres?'))['reason']
        self.assertIn('lo escribe la sesión', reason)

    def test_the_text_is_read_from_the_transcript_tail_and_sidechains_are_ignored(self):
        mod = self.module()
        path = os.path.join(self.tmp, 't.jsonl')

        def write(last, filler=0, sidechain=None):
            with open(path, 'w') as fh:
                for _ in range(filler):
                    fh.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'x' * 900}}) + '\n')
                fh.write(json.dumps({'type': 'assistant', 'message': {'id': 'm1', 'role': 'assistant', 'content': [
                    {'type': 'text', 'text': last}]}}) + '\n')
                if sidechain:
                    fh.write(json.dumps({'type': 'assistant', 'isSidechain': True, 'message': {
                        'id': 'm2', 'role': 'assistant', 'content': [{'type': 'text', 'text': sidechain}]}}) + '\n')

        write(HANDS_BACK, filler=900, sidechain='Todo hecho.')
        self.assertGreater(os.path.getsize(path), 512 * 1024)
        self.assertTrue(self.blocked(self.stop(mod, self.session(mod), transcript_path=path)))
        write('Todo hecho y verificado.', filler=5, sidechain='queda para ti')
        self.assertEqual(self.stop(mod, self.session(mod), transcript_path=path), '')
        self.assertEqual(self.stop(mod, self.session(mod), transcript_path=os.path.join(self.tmp, 'no.jsonl')), '')


class QuestionSessionTests(Sandbox):
    def test_the_default_titles_are_not_judged_on_their_turns(self):
        mod = self.module()
        for i, title in enumerate(('Sesión de preguntas de demo', 'PREGUNTAS DE LA SUPERVISION DE demo',
                                   'Buzón de preguntas')):
            sid = self.session(mod)
            self.write_ficha(sid, title, f'local_{i}.json')
            self.assertEqual(self.stop(mod, sid, HANDS_BACK), '', title)

    def test_an_ordinary_session_and_one_without_a_ficha_are_judged(self):
        mod = self.module()
        sid = self.session(mod)
        self.write_ficha(sid, 'demo · Arreglo de login')
        self.assertTrue(self.blocked(self.stop(mod, sid, HANDS_BACK)))
        self.assertTrue(self.blocked(self.stop(mod, self.session(mod), HANDS_BACK)))

    def test_the_titles_come_from_the_supervision_config(self):
        self.config('supervision', {'questions_session_titles': ['Mailbox of']})
        mod = self.module()
        sid = self.session(mod)
        self.write_ficha(sid, 'Mailbox of demo')
        self.assertEqual(self.stop(mod, sid, HANDS_BACK), '')
        other = self.session(mod)
        self.write_ficha(other, 'Buzón de preguntas', 'local_b.json')  # a default title is no longer one
        self.assertTrue(self.blocked(self.stop(mod, other, HANDS_BACK)))

    def test_the_app_sessions_dir_comes_from_the_supervision_config(self):
        mod = self.module()
        self.assertEqual(mod.app_glob(), os.path.join(self.app, '*', '*', 'local_*.json'))  # the test override
        self.config('supervision', {'app_sessions_dir': '/somewhere/sessions'})
        with mock.patch.dict(os.environ):
            os.environ.pop('HANDOFF_GUARD_APP_GLOB')
            self.assertEqual(load_module().app_glob(), '/somewhere/sessions/*/*/local_*.json')


class RulesChangedTests(Sandbox):
    def setUp(self):
        super().setUp()
        for name in ('despliegue-y-limites-duros.md', 'desatencion-sin-preguntas.md', 'cierre-con-todo-publicado.md',
                     'supervisor-decide-lo-documentado.md', 'custom-rule.md'):
            self.touch_rule(name)

    def test_the_watched_rules_are_the_deploy_rule_and_the_configured_ones(self):
        self.assertEqual(self.module().watched_rules(),
                         ('despliegue-y-limites-duros.md', 'desatencion-sin-preguntas.md',
                          'cierre-con-todo-publicado.md', 'supervisor-decide-lo-documentado.md'))
        self.config('supervision', {'deploy_rule': 'my-deploy.md'})
        self.config('handoff-guard', {'watched_rules': ['custom-rule.md', 'my-deploy.md']})
        self.assertEqual(self.module().watched_rules(), ('my-deploy.md', 'custom-rule.md'))

    def test_a_rule_newer_than_the_session_start_blocks_once_per_change(self):
        mod = self.module()
        sid = self.session(mod)
        time.sleep(0.05)
        rule = self.touch_rule('despliegue-y-limites-duros.md', time.time() + 5)
        out = self.stop(mod, sid, 'Todo hecho.')
        self.assertTrue(self.blocked(out))
        self.assertIn(rule, json.loads(out)['reason'])
        self.assertEqual(self.stop(mod, sid, 'Todo hecho.'), '')
        self.touch_rule('despliegue-y-limites-duros.md', time.time() + 10)
        self.assertTrue(self.blocked(self.stop(mod, sid, 'Todo hecho.')))

    def test_a_session_started_after_the_change_has_seen_it(self):
        mod = self.module()
        self.touch_rule('desatencion-sin-preguntas.md', time.time() - 50)
        self.assertEqual(self.stop(mod, self.session(mod), 'Todo hecho.'), '')

    def test_a_session_unknown_to_the_guard_is_not_blocked(self):
        mod = self.module()
        sid = self.session()  # no SessionStart, no transcript: the start is unknown, so nothing can have changed since
        self.assertEqual(self.stop(mod, sid, 'Todo hecho.'), '')
        self.assertEqual(self.stop(mod, sid, 'Todo hecho.'), '')

    def test_a_configured_rule_is_watched_and_one_that_is_not_listed_is_not(self):
        self.config('handoff-guard', {'watched_rules': ['custom-rule.md']})
        mod = self.module()
        sid = self.session(mod)
        time.sleep(0.05)
        self.touch_rule('cierre-con-todo-publicado.md', time.time() + 5)  # no longer watched
        self.assertEqual(self.stop(mod, sid, 'Todo hecho.'), '')
        self.touch_rule('custom-rule.md', time.time() + 5)
        self.assertTrue(self.blocked(self.stop(mod, sid, 'Todo hecho.')))

    def test_the_handing_back_text_goes_before_the_rule_change(self):
        mod = self.module()
        sid = self.session(mod)
        time.sleep(0.05)
        self.touch_rule('despliegue-y-limites-duros.md', time.time() + 5)
        self.assertIn('queda para ti', json.loads(self.stop(mod, sid, HANDS_BACK))['reason'])
        self.assertTrue(self.blocked(self.stop(mod, sid, 'Todo hecho.')))


class DialogTests(Sandbox):
    PHOTO = [{'header': 'Foto real', 'question': 'Saca tú la foto real y prueba con tu iPhone',
              'options': [{'label': 'Hecho', 'description': 'Ya la he sacado'}, {'label': 'No puedo'}]}]

    def test_a_dialog_that_asks_him_to_test_is_denied_once(self):
        mod = self.module()
        sid = self.session(mod)
        out = self.ask(mod, sid, self.PHOTO)
        self.assertTrue(self.denied(out))
        self.assertIn('Foto real', json.loads(out)['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual(self.ask(mod, sid, self.PHOTO), '')

    def test_a_final_confirmation_passes(self):
        mod = self.module()
        out = self.ask(mod, self.session(mod), [{'header': 'Final', 'question': '¿Quieres modificar algo más?',
                                                 'options': [{'label': 'No, está todo'}, {'label': 'Sí'}]}])
        self.assertEqual(out, '')

    def test_a_commit_message_question_is_denied_and_only_the_offending_question_is_named(self):
        mod = self.module()
        out = self.ask(mod, self.session(mod), [
            {'header': 'Rumbo', 'question': '¿Confirmas el rumbo A?', 'options': [{'label': 'Confirmar'}]},
            {'header': 'Commit', 'question': '¿Qué mensaje de commit pongo?', 'options': [{'label': 'fix: login'}]}])
        reason = json.loads(out)['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('Commit', reason)
        self.assertNotIn('Rumbo', reason)

    def test_the_dialog_reason_names_the_deploy_rule_and_the_examples_of_the_config(self):
        reason = json.loads(self.ask(self.module(), 'sess-d-test', self.PHOTO))['hookSpecificOutput'][
            'permissionDecisionReason']
        self.assertIn('probar con usuarios de prueba, emuladores o navegador, etc.', reason)
        self.assertIn('~/.claude/rules/despliegue-y-limites-duros.md', reason)
        self.assertIn('ask-queue add', reason)

    def test_the_wrap_up_recap_is_checked_like_a_final_message(self):
        mod = self.module()
        sid = self.session(mod)

        def wrap(text):
            return mod.hook_decide(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'mcp__ccd_turn__wrap_up',
                                               'session_id': sid, 'tool_input': {'recap': text}}))

        self.assertTrue(self.denied(wrap(HANDS_BACK)))
        self.assertEqual(wrap(HANDS_BACK), '')
        self.assertEqual(wrap('Desplegado y verificado en el entorno de pruebas.'), '')

    def test_another_tool_is_ignored(self):
        mod = self.module()
        out = mod.hook_decide(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'session_id': 's',
                                          'tool_input': {'command': 'echo queda para ti'}}))
        self.assertEqual(out, '')


class ConfigTests(Sandbox):
    def test_defaults_without_any_config(self):
        mod = self.module()
        self.assertEqual(mod.SUPERVISION['deploy_rule'], 'despliegue-y-limites-duros.md')
        self.assertEqual(mod.CONFIG['watched_rules'], mod.HANDOFF_DEFAULTS['watched_rules'])
        self.assertEqual(mod.question_title_prefixes(),
                         ('sesion de preguntas', 'preguntas de la supervision', 'buzon de preguntas'))

    def test_the_deploy_rule_comes_from_the_supervision_config(self):
        self.config('supervision', {'deploy_rule': 'production-policy.md'})
        mod = self.module()
        self.assertEqual(mod.deploy_rule_path(), '~/.claude/rules/production-policy.md')
        self.assertIn('~/.claude/rules/production-policy.md', json.loads(self.stop(mod, 'sess-x-test', HANDS_BACK))['reason'])

    def test_the_wording_of_the_reasons_comes_from_the_handoff_guard_config(self):
        self.config('handoff-guard', {'stop_policy': 'POLICY {rule}.', 'hard_limits': 'LIMITS', 'ask_examples': 'EXAMPLES'})
        mod = self.module()
        stop = json.loads(self.stop(mod, 'sess-y-test', HANDS_BACK))['reason']
        self.assertIn('POLICY ~/.claude/rules/despliegue-y-limites-duros.md. Si de verdad es un límite duro de esa '
                      'regla (LIMITS), no lo hagas', stop)
        ask = json.loads(self.ask(mod, 'sess-y-test', DialogTests.PHOTO))['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('va a un diálogo (EXAMPLES)', ask)

    def test_a_corrupt_or_mistyped_config_keeps_the_defaults(self):
        self.config('supervision', '{not json')
        self.config('handoff-guard', '{not json')
        mod = self.module()
        self.assertEqual(mod.deploy_rule_path(), '~/.claude/rules/despliegue-y-limites-duros.md')
        self.assertEqual(mod.CONFIG, mod.HANDOFF_DEFAULTS)
        self.config('supervision', {'deploy_rule': '', 'questions_session_titles': [3], 'app_sessions_dir': 5})
        self.config('handoff-guard', {'watched_rules': 'x.md', 'stop_policy': '', 'hard_limits': None})
        mod = self.module()
        self.assertEqual(mod.SUPERVISION, mod.SUPERVISION_DEFAULTS)
        self.assertEqual(mod.CONFIG, mod.HANDOFF_DEFAULTS)

    def test_the_shipped_config_piece_equals_the_defaults(self):
        with open(REPO_ROOT / 'global/config/handoff-guard.json') as fh:
            shipped = json.load(fh)
        self.assertEqual(shipped, self.module().HANDOFF_DEFAULTS)

    def test_the_pattern_list_is_not_configurable(self):
        self.config('handoff-guard', {'patterns': ['x'], 'PATTERN_SPECS': []})
        self.assertTrue(self.module().find_matches('esto queda para ti'))

    def test_without_the_toolkit_library_the_defaults_apply(self):
        # a copy of the script with no lib/ beside it (the config reader cannot be imported)
        alone = os.path.join(self.tmp, 'alone')
        os.makedirs(alone)
        copy = os.path.join(alone, 'handoff-guard')
        shutil.copy(SCRIPT, copy)
        loader = importlib.machinery.SourceFileLoader('hg_alone', copy)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, self.env):
            loader.exec_module(module)
        self.assertEqual(module.SUPERVISION, module.SUPERVISION_DEFAULTS)


class ProcessTests(Sandbox):
    def test_the_hook_fails_open_and_logs_the_traceback(self):
        for raw in ('this is { not json', '', '{}', '[]'):
            done = self.run_cli('hook', stdin=raw)
            self.assertEqual((done.returncode, done.stdout), (0, ''), raw)
        with open(os.path.join(self.state, 'errors.log')) as fh:
            self.assertIn('Traceback', fh.read())

    def test_a_stop_payload_prints_the_block_json(self):
        done = self.run_cli('hook', stdin=json.dumps({'hook_event_name': 'Stop', 'session_id': 'sess-p-test',
                                                      'last_assistant_message': HANDS_BACK}))
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(done.stdout)['decision'], 'block')
        with open(os.path.join(self.state, 'decisions.log')) as fh:
            self.assertIn('block-handoff', fh.read())

    def test_match_prints_category_tab_fragment_and_exits_by_hit(self):
        hit = self.run_cli('match', stdin='esto queda para ti')
        self.assertEqual(hit.returncode, 0)
        self.assertTrue(hit.stdout.startswith('handoff\t') and 'queda para ti' in hit.stdout)
        self.assertEqual(self.run_cli('match', stdin='todo hecho').returncode, 1)
        self.assertEqual(self.run_cli('match', '--ask', stdin='saca tú la foto real').stdout.split('\t')[0], 'ask')
        self.assertEqual(self.run_cli('match', '--ask', stdin='¿quieres que despliegue?').returncode, 1)

    def test_match_runs_directly_as_the_supervisor_lock_provider_does(self):
        done = subprocess.run([SCRIPT, 'match'], input='esto queda para ti', capture_output=True, text=True,
                              env=self.env, timeout=30)
        self.assertEqual(done.returncode, 0)
        self.assertIn('queda para ti', done.stdout.partition('\t')[2])

    def test_usage_error(self):
        self.assertEqual(self.run_cli().returncode, 2)

    def test_the_kill_switches(self):
        mod = self.module()
        sid = self.session(mod)
        self.assertTrue(self.blocked(self.stop(mod, sid, HANDS_BACK)))
        with mock.patch.dict(os.environ, {'HANDOFF_GUARD': 'off'}):
            self.assertEqual(self.stop(mod, sid, 'Cuando puedas, dime.'), '')
            self.assertEqual(self.ask(mod, sid, DialogTests.PHOTO), '')
        flag = os.path.join(self.state, 'disabled')
        open(flag, 'w').close()
        self.assertEqual(self.stop(mod, sid, 'Avísame cuando termines.'), '')
        os.unlink(flag)
        self.assertTrue(self.blocked(self.stop(mod, sid, 'Avísame cuando termines.')))

    def test_nothing_is_written_outside_the_state_dir(self):
        self.run_cli('hook', stdin=json.dumps({'hook_event_name': 'SessionStart', 'session_id': 'sess-h-test'}))
        self.run_cli('hook', stdin=json.dumps({'hook_event_name': 'Stop', 'session_id': 'sess-h-test',
                                               'last_assistant_message': HANDS_BACK}))
        self.assertEqual(os.listdir(self.home), [])
        self.assertTrue(os.path.isfile(os.path.join(self.state, 'seen', 'sess-h-test.json')))

    def test_the_stop_gate_hook_chains_to_the_installed_guard(self):
        scripts = os.path.join(self.home, '.claude', 'scripts')
        os.makedirs(scripts)
        os.symlink(SCRIPT, os.path.join(scripts, 'handoff-guard'))
        payload = json.dumps({'hook_event_name': 'Stop', 'session_id': 'sess-g-test', 'last_assistant_message': HANDS_BACK})
        done = subprocess.run(['bash', STOP_GATE], input=payload, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(done.stdout)['decision'], 'block')
        os.unlink(os.path.join(scripts, 'handoff-guard'))  # the guard is optional: without it the gate is silent
        done = subprocess.run(['bash', STOP_GATE], input=payload, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual((done.returncode, done.stdout), (0, ''))

    def test_the_builtin_self_test_passes(self):
        done = self.run_cli('self-test')
        self.assertEqual(done.returncode, 0, done.stdout[-600:])
        self.assertRegex(done.stdout, r'\d+ cases, 0 failed')


if __name__ == '__main__':
    unittest.main()
