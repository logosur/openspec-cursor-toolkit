"""Tests for global/hooks/agent-model-gate (PreToolUse gate for subagent models and the advisor cap).

The hook runs as a subprocess with the JSON on stdin, AGENT_MODEL_GATE_STATE and CLAUDE_TOOLKIT_CONFIG_DIR pointing
into a temp dir, so neither the real cache nor the real config is touched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from scripts.toolkit.paths import REPO_ROOT

HOOK = str(REPO_ROOT / 'global/hooks/agent-model-gate')
MARK = '[opus: parser rewrite touches three modules]'
START = 'mcp__ccd_session__start_session'


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='agent-model-gate-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = os.path.join(self.tmp, 'state')
        self.config = os.path.join(self.tmp, 'config')
        os.makedirs(self.config)

    def set_config(self, **values):
        with open(os.path.join(self.config, 'agent-model-gate.json'), 'w') as fh:
            json.dump(values, fh)

    def run_hook(self, stdin):
        env = dict(os.environ, HOME=self.tmp, AGENT_MODEL_GATE_STATE=self.state,
                   CLAUDE_TOOLKIT_CONFIG_DIR=self.config)
        if not isinstance(stdin, str):
            stdin = json.dumps(stdin)
        return subprocess.run([sys.executable, HOOK], input=stdin, capture_output=True, text=True, env=env, timeout=30)

    def agent(self, tool='Agent', session='s1', cwd='/work/proj', **inp):
        return self.run_hook({'tool_name': tool, 'session_id': session, 'cwd': cwd, 'tool_input': inp})

    def advisor(self, session='s1', cwd='/work/proj'):
        return self.run_hook({'tool_name': 'advisor', 'session_id': session, 'cwd': cwd, 'tool_input': {}})

    def start(self, **inp):
        return self.run_hook({'tool_name': START, 'session_id': 's1', 'cwd': '/work/proj', 'tool_input': inp})

    def assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def assert_denied(self, result, *words):
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(data['hookEventName'], 'PreToolUse')
        self.assertEqual(data['permissionDecision'], 'deny')
        for word in words:
            self.assertIn(word, data['permissionDecisionReason'])
        return data['permissionDecisionReason']

    def log(self, name):
        try:
            with open(os.path.join(self.state, name)) as fh:
                return fh.read()
        except OSError:
            return ''

    # ---- Agent

    def test_no_model_is_denied_with_the_fix(self):
        for tool in ('Agent', 'Task'):
            with self.subTest(tool=tool):
                self.assert_denied(self.agent(tool=tool, description='explore', prompt='look'), 'model: "sonnet"', '"haiku"')
        self.assertIn('deny-no-model', self.log('decisions.log'))

    def test_empty_or_inherit_model_counts_as_missing(self):
        for model in ('', '  ', None, 'inherit'):
            with self.subTest(model=model):
                self.assert_denied(self.agent(description='explore', prompt='look', model=model), 'names no model')

    def test_cheap_models_pass(self):
        for model in ('sonnet', 'haiku', 'claude-sonnet-5-5'):
            with self.subTest(model=model):
                self.assert_allowed(self.agent(description='explore', prompt='look', model=model))

    def test_opus_and_fable_without_a_mark_are_denied(self):
        for model in ('opus', 'Opus', 'fable', 'claude-opus-5-5', 'opusplan'):
            with self.subTest(model=model):
                self.assert_denied(self.agent(description='implement', prompt='write it', model=model), '[opus:')
        self.assertIn('deny-expensive', self.log('decisions.log'))

    def test_a_short_or_empty_reason_is_not_a_mark(self):
        for text in ('[opus: hard]', '[opus:    ]', '[opus]', 'opus: a long enough reason'):
            with self.subTest(text=text):
                self.assert_denied(self.agent(description='implement', prompt=text, model='opus'))

    def test_the_mark_in_description_or_prompt_allows_opus_and_fable(self):
        self.assert_allowed(self.agent(description='implement ' + MARK, prompt='write it', model='opus'))
        self.assert_allowed(self.agent(description='implement', prompt='write it ' + MARK, model='fable'))
        self.assert_allowed(self.agent(description='implement', prompt='[OPUS: Hard concurrency bug, two failures]',
                                       model='claude-opus-5-5'))

    def test_the_panel_needs_no_mark(self):
        self.assert_allowed(self.agent(description='Panel member: conservative view', prompt='vote', model='opus'))
        self.assert_denied(self.agent(description='A panel of one', prompt='vote', model='opus'))

    def test_panel_pattern_is_configurable(self):
        self.set_config(panel_pattern='^Jury')
        self.assert_allowed(self.agent(description='Jury member', prompt='vote', model='opus'))
        self.assert_denied(self.agent(description='Panel member', prompt='vote', model='opus'))

    def test_a_broken_panel_pattern_falls_back_to_the_default(self):
        self.set_config(panel_pattern='(')
        self.assert_allowed(self.agent(description='Panel member', prompt='vote', model='opus'))

    def test_a_fork_needs_no_model(self):
        self.assert_allowed(self.agent(subagent_type='fork', description='continue', prompt='go on'))
        self.assert_allowed(self.agent(subagent_type='fork', description='continue', prompt='go on', model='opus'))

    def test_a_named_agent_type_is_not_a_fork(self):
        self.assert_denied(self.agent(subagent_type='Explore', description='find', prompt='where'))

    # ---- start_session

    def test_start_session_with_a_prompt_needs_a_model(self):
        self.assert_denied(self.start(initiation='user_asked', title='t', prompt='do it'), 'session start')
        self.assert_allowed(self.start(initiation='user_asked', title='t', prompt='do it', model='claude-sonnet-5-5'))

    def test_start_session_title_only_offers_and_proposals_are_not_touched(self):
        self.assert_allowed(self.start(initiation='offer', title='t'))
        self.assert_allowed(self.start(initiation='user_asked', proposal_id='p1'))
        self.assert_allowed(self.start(initiation='user_asked', proposal_id='p1', prompt='x'))

    def test_start_session_opus_id_needs_the_mark_in_prompt_or_background(self):
        self.assert_denied(self.start(initiation='user_asked', title='t', prompt='do it', model='claude-opus-5-5'))
        self.assert_allowed(self.start(initiation='user_asked', title='t', prompt='do it ' + MARK,
                                       model='claude-opus-5-5'))
        self.assert_allowed(self.start(initiation='user_asked', title='t', prompt='do it', background=MARK,
                                       model='claude-fable-1'))

    def test_start_session_ignores_the_panel_pattern(self):
        self.assert_denied(self.start(initiation='user_asked', title='Panel', prompt='Panel: vote', model='opus'))

    # ---- advisor

    def test_advisor_is_allowed_below_the_cap_and_denied_above(self):
        for _ in range(4):
            self.assert_allowed(self.advisor())
        reason = self.assert_denied(self.advisor(), 'cap is 4', 'without the advisor')
        self.assertIn('4 time(s)', reason)
        self.assertIn('deny-advisor-cap', self.log('decisions.log'))

    def test_advisor_counts_per_session(self):
        self.set_config(advisor_max_per_day=1)
        self.assert_allowed(self.advisor(session='a'))
        self.assert_denied(self.advisor(session='a'))
        self.assert_allowed(self.advisor(session='b'))

    def test_advisor_cap_zero_denies_every_call(self):
        self.set_config(advisor_max_per_day=0)
        self.assert_denied(self.advisor())

    def test_advisor_counter_is_a_rolling_day(self):
        self.set_config(advisor_max_per_day=1)
        self.assert_allowed(self.advisor())
        path = os.path.join(self.state, 's1.json')
        with open(path, 'w') as fh:
            json.dump({'advisor': [time.time() - 25 * 3600]}, fh)   # older than 24 hours: forgotten
        self.assert_allowed(self.advisor())
        self.assert_denied(self.advisor())

    def test_advisor_with_a_corrupt_counter_starts_again(self):
        os.makedirs(self.state)
        with open(os.path.join(self.state, 's1.json'), 'w') as fh:
            fh.write('{not json')
        self.assert_allowed(self.advisor())

    def test_advisor_session_id_never_leaves_the_state_dir(self):
        self.set_config(advisor_max_per_day=1)
        self.assert_allowed(self.advisor(session='../../escape'))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'escape.json')))
        self.assertTrue(all(os.path.dirname(os.path.join(self.state, n)) == self.state for n in os.listdir(self.state)))

    # ---- austerity, config, exempt folders

    def test_austerity_denies_opus_even_with_the_mark_except_the_panel(self):
        self.set_config(austerity=True)
        self.assert_denied(self.agent(description='implement ' + MARK, prompt='x', model='opus'), 'austerity')
        self.assert_denied(self.start(initiation='user_asked', title='t', prompt='x ' + MARK, model='claude-opus-5-5'),
                           'austerity')
        self.assert_allowed(self.agent(description='Panel member', prompt='vote', model='opus'))
        self.assert_allowed(self.agent(description='explore', prompt='look', model='sonnet'))
        self.assert_denied(self.agent(description='explore', prompt='look'), 'names no model')

    def test_austerity_drops_the_advisor_cap_to_one(self):
        self.set_config(austerity=True, advisor_max_per_day=4)
        self.assert_allowed(self.advisor())
        self.assert_denied(self.advisor(), 'cap is 1')

    def test_switches_turn_the_checks_off(self):
        self.set_config(require_explicit_model=False)
        self.assert_allowed(self.agent(description='explore', prompt='look'))
        self.assert_denied(self.agent(description='x', prompt='y', model='opus'))
        self.set_config(opus_needs_marker=False)
        self.assert_allowed(self.agent(description='x', prompt='y', model='opus'))
        self.set_config(enabled=False)
        self.assert_allowed(self.agent(description='explore', prompt='look'))
        self.assert_allowed(self.advisor())

    def test_exempt_folder_prefixes(self):
        self.set_config(exempt_paths=['/work/scratch'])
        self.assert_allowed(self.agent(cwd='/work/scratch', description='x', prompt='y'))
        self.assert_allowed(self.agent(cwd='/work/scratch/deep/er', description='x', prompt='y'))
        self.assert_denied(self.agent(cwd='/work/scratchpad', description='x', prompt='y'))
        self.assert_denied(self.agent(cwd='/work/proj', description='x', prompt='y'))

    def test_a_wrong_config_value_keeps_the_default(self):
        self.set_config(enabled='no', advisor_max_per_day=-3, panel_pattern='', exempt_paths='/work/proj')
        self.assert_denied(self.agent(description='explore', prompt='look'))
        self.assert_allowed(self.advisor())

    def test_a_corrupt_config_file_keeps_the_defaults(self):
        with open(os.path.join(self.config, 'agent-model-gate.json'), 'w') as fh:
            fh.write('{not json')
        self.assert_denied(self.agent(description='explore', prompt='look'))

    # ---- never breaks anything

    def test_other_tools_pass_silently(self):
        for tool in ('Bash', 'Read', 'mcp__ccd_session__hand_off_to_session', 'SendMessage'):
            with self.subTest(tool=tool):
                self.assert_allowed(self.run_hook({'tool_name': tool, 'tool_input': {'command': 'ls', 'model': 'opus'}}))

    def test_malformed_input_fails_open(self):
        for raw in ('{not json', '', '[]', '"x"', 'null'):
            with self.subTest(raw=raw):
                self.assert_allowed(self.run_hook(raw))
        for payload in ({'tool_name': 'Agent'}, {'tool_name': 'Agent', 'tool_input': 'oops'},
                        {'tool_name': 'Agent', 'tool_input': {'description': 7, 'prompt': ['x'], 'model': 5}},
                        {'tool_name': START, 'tool_input': None}, {'tool_name': 'advisor', 'session_id': 7}):
            with self.subTest(payload=payload):
                result = self.run_hook(payload)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unwritable_state_dir_never_breaks_the_call(self):
        blocker = os.path.join(self.tmp, 'file')
        with open(blocker, 'w') as fh:
            fh.write('x')
        env = dict(os.environ, HOME=self.tmp, AGENT_MODEL_GATE_STATE=os.path.join(blocker, 'sub'),
                   CLAUDE_TOOLKIT_CONFIG_DIR=self.config)
        result = subprocess.run([sys.executable, HOOK], capture_output=True, text=True, env=env, timeout=30,
                                input=json.dumps({'tool_name': 'advisor', 'session_id': 's', 'tool_input': {}}))
        self.assertEqual((result.returncode, result.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main()
