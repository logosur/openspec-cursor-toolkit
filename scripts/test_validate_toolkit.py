"""Tests for scripts/validate-toolkit.py.

Each test builds a throwaway catalog in a temporary directory, breaks (or keeps)
one rule and checks the findings and the exit code. A new validator rule needs at
least one passing and one failing case here.

Run: python3 -m unittest scripts/test_validate_toolkit.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import random
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent

_spec = importlib.util.spec_from_file_location('validate_toolkit', SCRIPTS / 'validate-toolkit.py')
vt = importlib.util.module_from_spec(_spec)
sys.modules['validate_toolkit'] = vt
_spec.loader.exec_module(vt)

ALPHA = 'Builds release notes from merged pull requests. Use when the user asks for release notes or a changelog.'
GAMMA = 'Audits database indexes for slow queries. Use on /gamma, revisa índices.'
# Measured with this validator: 0.67 against ALPHA (collision) and 0.35 (warning).
ALPHA_TWIN = 'Builds release notes from merged pull requests and tags. Use when the user asks for release notes.'
ALPHA_COUSIN = ('Builds release notes from merged pull requests for the Spanish site. '
                'Use when the user asks for translated copy.')


def skill(name: str, description: str, extra: str = '', body: str = '# Body\n\nDo the thing.\n') -> str:
    return f'---\nname: {name}\ndescription: {json.dumps(description)}\n{extra}---\n\n{body}'


def rule(description: str, extra: str = '') -> str:
    return f'---\ndescription: {json.dumps(description)}\nalwaysApply: false\n{extra}---\n\nRule body.\n'


README = '# Skills\n\n| Folder | Purpose |\n|---|---|\n| `alpha` | Release notes |\n| `beta` | Wrapper |\n| `gamma` | Indexes |\n'


def clean_catalog() -> dict[str, str]:
    files = {
        '.claude/commands/foo.md': '---\ndescription: "Run foo"\nargument-hint: "[x]"\n---\n\nBody.\n',
        '.cursor/commands/foo.md': '---\nname: /foo\nid: foo\ncategory: Workflow\ndescription: "Run foo"\n---\n\nBody.\n',
        '.cursor/rules/alpha.mdc': rule(ALPHA),
    }
    for tree in vt.TREES:
        files[f'{tree}/skills/README.md'] = README
        files[f'{tree}/skills/alpha/SKILL.md'] = skill('alpha', ALPHA)
        files[f'{tree}/skills/beta/SKILL.md'] = skill('beta', 'Wrapper for the beta command', 'disable-model-invocation: true\n')
        files[f'{tree}/skills/gamma/SKILL.md'] = skill('gamma', GAMMA)
    return files


class CatalogTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for rel, text in clean_catalog().items():
            self.write(rel, text)

    def tearDown(self):
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------------

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def append(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.write_text(path.read_text(encoding='utf-8') + text, encoding='utf-8')

    def exceptions(self, text: str) -> None:
        self.write(vt.EXCEPTIONS_FILE, textwrap.dedent(text))

    def add_skill(self, name: str, content: str, trees=vt.TREES, readme: bool = True) -> None:
        for tree in trees:
            self.write(f'{tree}/skills/{name}/SKILL.md', content)
            if readme:
                self.append(f'{tree}/skills/README.md', f'| `{name}` | added |\n')

    def findings(self) -> list:
        return vt.validate(self.root)

    def run_main(self) -> tuple[int, list[str]]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vt.main(['--root', str(self.root)])
        return code, out.getvalue().splitlines()

    def matching(self, severity=None, path=None, rule=None, contains=None) -> list:
        return [
            f for f in self.findings()
            if (severity is None or f.severity == severity)
            and (path is None or f.path == path)
            and (rule is None or f.rule == rule)
            and (contains is None or all(c in f.message for c in ([contains] if isinstance(contains, str) else contains)))
        ]

    def assertFinding(self, severity, path, rule, contains=None):
        found = self.matching(severity, path, rule, contains)
        self.assertTrue(found, f'expected {severity} {path} [{rule}] {contains!r}; got:\n'
                        + '\n'.join(f.line() for f in self.findings()))

    def assertNoRule(self, rule):
        found = self.matching(rule=rule)
        self.assertFalse(found, '\n'.join(f.line() for f in found))

    def assertClean(self):
        self.assertEqual([], [f.line() for f in self.findings()])


class ExitCodeContract(CatalogTestCase):
    def test_clean_catalog_exits_0_with_summary(self):
        code, lines = self.run_main()
        self.assertEqual(0, code)
        self.assertEqual(['validate-toolkit: 0 error(s), 0 warning(s)'], lines)

    def test_two_findings_in_one_run_exit_1(self):
        self.write('.claude/commands/foo.md', '---\ndescription: "Run foo"\nmodel: opus\n---\n\nBody.\n')
        self.write('.cursor/skills/gamma/SKILL.md', skill('gamma-x', GAMMA))
        code, lines = self.run_main()
        self.assertEqual(1, code)
        self.assertTrue(any(l.startswith('ERROR .claude/commands/foo.md: [keys] ') for l in lines), lines)
        self.assertTrue(any(l.startswith('ERROR .cursor/skills/gamma/SKILL.md: [name] ') for l in lines), lines)
        self.assertEqual('validate-toolkit: 2 error(s), 0 warning(s)', lines[-1])

    def test_warnings_only_exit_0_and_listed(self):
        self.write('.claude/skills/alpha/SKILL.md', skill('alpha', ALPHA, body='---\nname: /alpha\nid: alpha\n---\n\n# Body\n'))
        code, lines = self.run_main()
        self.assertEqual(0, code)
        self.assertIn('WARN .claude/skills/alpha/SKILL.md: [inner-frontmatter] ', lines[0])
        self.assertEqual('validate-toolkit: 0 error(s), 1 warning(s)', lines[-1])


class Exceptions(CatalogTestCase):
    def test_dead_claude_only_exception(self):
        self.exceptions("""
            claude_only_skills:
              - name: foo
                reason: Ships as a Cursor rule
        """)
        self.assertFinding('ERROR', vt.EXCEPTIONS_FILE, 'exceptions', ["'foo'", 'remove the entry'])

    def test_exception_that_matches_no_asymmetry_is_dead(self):
        self.exceptions("""
            claude_only_skills:
              - name: alpha
                reason: Ships as a Cursor rule
        """)
        self.assertFinding('ERROR', vt.EXCEPTIONS_FILE, 'exceptions', ["'alpha'", 'also exists in .cursor'])

    def test_exception_without_reason(self):
        self.add_skill('zeta', skill('zeta', 'Zeta helper. Use when zeta is needed.'), trees=('.claude',))
        self.exceptions("""
            claude_only_skills:
              - name: zeta
        """)
        self.assertFinding('ERROR', vt.EXCEPTIONS_FILE, 'exceptions', ["'zeta'", 'no reason'])

    def test_unknown_section(self):
        self.exceptions("""
            ignore_everything:
              - name: alpha
                reason: lazy
        """)
        self.assertFinding('ERROR', vt.EXCEPTIONS_FILE, 'exceptions', 'unknown section')

    def test_real_exceptions_file_is_alive_and_complete(self):
        findings = [f for f in vt.validate(REPO_ROOT) if f.rule == 'exceptions']
        self.assertEqual([], [f.line() for f in findings])


class SetParity(CatalogTestCase):
    def test_command_only_in_claude(self):
        self.write('.claude/commands/bar.md', '---\ndescription: "Run bar"\n---\n\nBody.\n')
        self.assertFinding('ERROR', '.claude/commands/bar.md', 'command-parity', ['bar.md', 'missing from .cursor'])

    def test_declared_claude_only_command(self):
        self.write('.claude/commands/bar.md', '---\ndescription: "Run bar"\n---\n\nBody.\n')
        self.exceptions("""
            claude_only_commands:
              - name: bar
                reason: Claude-specific helper
        """)
        self.assertClean()

    def test_undeclared_skill_asymmetry(self):
        self.add_skill('zeta', skill('zeta', 'Zeta helper. Use when zeta is needed.'), trees=('.cursor',))
        self.assertFinding('ERROR', '.cursor/skills/zeta/SKILL.md', 'skill-parity', ["'zeta'", 'missing from .claude'])

    def test_declared_claude_only_skill(self):
        self.add_skill('zeta', skill('zeta', 'Zeta helper. Use when zeta is needed.'), trees=('.claude',))
        self.exceptions("""
            claude_only_skills:
              - name: zeta
                reason: Cursor ships it as a rule
        """)
        self.assertClean()


class DescriptionParity(CatalogTestCase):
    def test_undeclared_divergence_shows_both_texts(self):
        self.write('.cursor/skills/alpha/SKILL.md', skill('alpha', 'Builds Cursor release notes. Use when asked.'))
        self.assertFinding('ERROR', '.claude/skills/alpha/SKILL.md', 'description-parity',
                           [ALPHA, 'Builds Cursor release notes. Use when asked.'])

    def test_declared_divergence_passes(self):
        self.write('.cursor/skills/alpha/SKILL.md', skill('alpha', 'Builds Cursor release notes. Use when asked.'))
        self.write('.cursor/rules/alpha.mdc', rule('Builds Cursor release notes. Use when asked.'))
        self.exceptions("""
            description_divergence:
              - kind: skill
                name: alpha
                reason: Cursor wording differs on purpose
        """)
        self.assertClean()

    def test_divergence_exception_dead_when_equal(self):
        self.exceptions("""
            description_divergence:
              - kind: command
                name: foo
                reason: used to differ
        """)
        self.assertFinding('ERROR', vt.EXCEPTIONS_FILE, 'exceptions', ["'foo'", 'equal'])


class Frontmatter(CatalogTestCase):
    def test_missing_frontmatter(self):
        self.write('.claude/commands/foo.md', 'Run foo without frontmatter.\n')
        self.assertFinding('ERROR', '.claude/commands/foo.md', 'frontmatter', 'missing frontmatter')

    def test_unparseable_yaml_unquoted_colon(self):
        self.write('.claude/skills/gamma/SKILL.md', '---\nname: gamma\ndescription: Audits indexes: use on /gamma\n---\n\nBody.\n')
        self.assertFinding('ERROR', '.claude/skills/gamma/SKILL.md', 'frontmatter', 'not valid YAML')

    def test_unknown_key_model(self):
        self.write('.claude/skills/gamma/SKILL.md', skill('gamma', GAMMA, 'model: opus\n'))
        self.assertFinding('ERROR', '.claude/skills/gamma/SKILL.md', 'keys', ["'model'", 'allowed: compatibility'])

    def test_rule_missing_always_apply(self):
        self.write('.cursor/rules/alpha.mdc', f'---\ndescription: {json.dumps(ALPHA)}\n---\n\nRule body.\n')
        self.assertFinding('ERROR', '.cursor/rules/alpha.mdc', 'keys', "'alwaysApply'")

    def test_tree_specific_command_keys(self):
        self.write('.claude/commands/foo.md', '---\nname: /foo\ndescription: "Run foo"\n---\n\nBody.\n')
        self.assertFinding('ERROR', '.claude/commands/foo.md', 'keys', "'name'")
        self.assertFalse(self.matching(path='.cursor/commands/foo.md'))


class Names(CatalogTestCase):
    def test_name_drift(self):
        self.write('.claude/skills/gamma/SKILL.md', skill('gamma-report', GAMMA))
        self.assertFinding('ERROR', '.claude/skills/gamma/SKILL.md', 'name', ["'gamma-report'", "'gamma'"])

    def test_non_kebab_command_name(self):
        for tree in vt.TREES:
            self.write(f'{tree}/commands/Foo_Bar.md', (self.root / tree / 'commands/foo.md').read_text())
        self.assertFinding('ERROR', '.claude/commands/Foo_Bar.md', 'name', 'kebab-case')
        self.assertFinding('ERROR', '.cursor/commands/Foo_Bar.md', 'name', 'kebab-case')

    def test_stray_folder(self):
        for tree in vt.TREES:
            (self.root / tree / 'skills' / 'notes').mkdir()
        self.assertFinding('ERROR', '.claude/skills/notes', 'skill-folder', 'not a declared skill group')

    def test_declared_group_validates_nested_skill(self):
        self.exceptions("""
            skill_groups:
              - name: grp
                reason: CLI skills installed as a group
        """)
        self.write('.claude/skills/grp/delta/SKILL.md', skill('delta-x', 'Delta helper. Use when delta is needed.'))
        self.write('.cursor/skills/grp/delta/SKILL.md', skill('delta', 'Delta helper. Use when delta is needed.'))
        for tree in vt.TREES:
            self.append(f'{tree}/skills/README.md', '| [`grp/delta/`](grp/delta/SKILL.md) | nested |\n')
        self.assertFinding('ERROR', '.claude/skills/grp/delta/SKILL.md', 'name', "'delta-x'")
        self.assertEqual(1, len(self.findings()), [f.line() for f in self.findings()])

    def test_undeclared_group_is_a_stray_folder(self):
        self.write('.claude/skills/grp/delta/SKILL.md', skill('delta', 'Delta helper. Use when delta is needed.'))
        self.assertFinding('ERROR', '.claude/skills/grp', 'skill-folder', 'not a declared skill group')


class ReadmeCoverage(CatalogTestCase):
    def test_name_inside_another_word_does_not_count(self):
        self.add_skill('qa', skill('qa', 'Quality report with screenshots. Use on /qa.'), readme=False)
        for tree in vt.TREES:
            self.append(f'{tree}/skills/README.md', 'An aqa folder, a qa-report and plain qa words.\n')
        self.assertFinding('ERROR', '.claude/skills/README.md', 'readme-coverage', "'qa'")
        self.assertFinding('ERROR', '.cursor/skills/README.md', 'readme-coverage', "'qa'")

    def test_backticked_name_counts(self):
        self.add_skill('qa', skill('qa', 'Quality report with screenshots. Use on /qa.'), readme=False)
        for tree in vt.TREES:
            self.append(f'{tree}/skills/README.md', 'See `qa` for reports.\n')
        self.assertNoRule('readme-coverage')

    def test_link_target_counts(self):
        self.assertTrue(vt.mentions('| [Quality](qa/SKILL.md) |', 'qa'))
        self.assertFalse(vt.mentions('| aqa | qa-report |', 'qa'))


class HygieneWarnings(CatalogTestCase):
    def test_stale_inner_frontmatter_is_warn(self):
        body = '---\nname: /alpha\nid: alpha\ncategory: Workflow\n---\n\n# Body\n'
        self.write('.cursor/skills/alpha/SKILL.md', skill('alpha', ALPHA, body=body))
        self.assertFinding('WARN', '.cursor/skills/alpha/SKILL.md', 'inner-frontmatter')
        code, _ = self.run_main()
        self.assertEqual(0, code)

    def test_horizontal_rule_is_not_inner_frontmatter(self):
        self.write('.cursor/skills/alpha/SKILL.md', skill('alpha', ALPHA, body='---\n\n# Body\n\n---\n'))
        self.assertClean()

    def test_homonym_rule_divergence_is_warn(self):
        self.write('.cursor/rules/alpha.mdc', rule('Release notes rule'))
        self.assertFinding('WARN', '.cursor/rules/alpha.mdc', 'homonym-rule', '.cursor/skills/alpha/SKILL.md')

    def test_homonym_falls_back_to_claude_only_skill(self):
        self.add_skill('zeta', skill('zeta', 'Zeta helper. Use when zeta is needed.'), trees=('.claude',))
        self.exceptions("""
            claude_only_skills:
              - name: zeta
                reason: Cursor ships it as a rule
        """)
        self.write('.cursor/rules/zeta.mdc', rule('Zeta rule wording'))
        self.assertFinding('WARN', '.cursor/rules/zeta.mdc', 'homonym-rule', '.claude/skills/zeta/SKILL.md')


class RoutingScope(CatalogTestCase):
    def test_wrapper_exempt_and_invocable_skill_checked(self):
        self.write('.claude/skills/alpha/SKILL.md', skill('alpha', 'Builds release notes'))
        self.write('.cursor/skills/alpha/SKILL.md', skill('alpha', 'Builds release notes'))
        self.write('.cursor/rules/alpha.mdc', rule('Builds release notes'))
        self.assertFinding('ERROR', '.claude/skills/alpha/SKILL.md', 'trigger-clause')
        self.assertFalse(self.matching(path='.claude/skills/beta/SKILL.md'))

    def test_wrapper_still_gets_frontmatter_checks(self):
        self.write('.claude/skills/beta/SKILL.md',
                   skill('beta', 'Wrapper for the beta command', 'disable-model-invocation: true\nmodel: opus\n'))
        self.assertFinding('ERROR', '.claude/skills/beta/SKILL.md', 'keys', "'model'")


class TriggerAndLength(CatalogTestCase):
    def set_gamma(self, description: str) -> None:
        for tree in vt.TREES:
            self.write(f'{tree}/skills/gamma/SKILL.md', skill('gamma', description))

    def test_purpose_only_description(self):
        self.set_gamma('OpenSpec orchestration layer')
        self.assertFinding('ERROR', '.claude/skills/gamma/SKILL.md', 'trigger-clause')
        self.assertFinding('ERROR', '.cursor/skills/gamma/SKILL.md', 'trigger-clause')

    def test_each_trigger_phrase_is_accepted(self):
        for phrase in ('Use when', 'use on', 'AUTO-INVOKE ON', 'Triggers on'):
            with self.subTest(phrase=phrase):
                self.set_gamma(f'Audits database indexes. {phrase} slow queries, revisa índices.')
                self.assertNoRule('trigger-clause')

    def test_1100_character_description(self):
        self.set_gamma(('Audits database indexes. Use when queries are slow. ' + 'x' * 1100)[:1100])
        self.assertFinding('ERROR', '.claude/skills/gamma/SKILL.md', 'description-length', '1100 characters')

    def test_1024_characters_is_allowed(self):
        self.set_gamma(('Audits database indexes. Use when queries are slow. ' + 'x' * 1100)[:1024])
        self.assertNoRule('description-length')


class Collisions(CatalogTestCase):
    def add_delta(self, description: str) -> None:
        self.add_skill('delta', skill('delta', description))

    def test_error_pair(self):
        self.add_delta(ALPHA_TWIN)
        self.assertFinding('ERROR', '.claude/skills/alpha/SKILL.md', 'collision', ["'alpha'", "'delta'", '0.67'])
        self.assertFinding('ERROR', '.cursor/skills/alpha/SKILL.md', 'collision', ["'alpha'", "'delta'"])

    def test_warn_pair_exits_0(self):
        self.add_delta(ALPHA_COUSIN)
        self.assertFinding('WARN', '.claude/skills/alpha/SKILL.md', 'collision', ["'alpha'", "'delta'", '0.35'])
        code, _ = self.run_main()
        self.assertEqual(0, code)

    def test_non_invocable_skill_never_collides(self):
        self.add_delta(ALPHA_TWIN)
        self.add_skill('delta', skill('delta', ALPHA_TWIN, 'disable-model-invocation: true\n'), readme=False)
        self.assertNoRule('collision')

    def test_scores_are_deterministic(self):
        self.add_delta(ALPHA_TWIN)
        first = [f.line() for f in self.findings() if f.rule == 'collision']
        second = [f.line() for f in self.findings() if f.rule == 'collision']
        self.assertEqual(first, second)
        named = [('alpha', ALPHA), ('delta', ALPHA_TWIN), ('gamma', GAMMA), ('cousin', ALPHA_COUSIN)]
        shuffled = named[:]
        random.Random(7).shuffle(shuffled)
        self.assertEqual(vt.description_similarities(named), vt.description_similarities(shuffled))


class Aliases(CatalogTestCase):
    ALIAS = 'Deprecated alias of alpha. Kept so existing references keep resolving; do not invoke.'
    BODY = '# old-alpha (deprecated alias)\n\nRead and follow `alpha/SKILL.md`.\n'

    def test_valid_alias_has_no_finding(self):
        self.add_skill('old-alpha', skill('old-alpha', self.ALIAS, 'disable-model-invocation: true\n', self.BODY))
        self.assertClean()

    def test_invocable_alias(self):
        self.add_skill('old-alpha', skill('old-alpha', self.ALIAS, body=self.BODY))
        self.assertFinding('ERROR', '.claude/skills/old-alpha/SKILL.md', 'alias', 'disable-model-invocation')

    def test_alias_to_missing_skill(self):
        description = self.ALIAS.replace('of alpha', 'of alphas')
        self.add_skill('old-alpha', skill('old-alpha', description, 'disable-model-invocation: true\n', self.BODY))
        self.assertFinding('ERROR', '.claude/skills/old-alpha/SKILL.md', 'alias', "'alphas'")

    def test_alias_that_carries_a_workflow(self):
        body = self.BODY + ''.join(f'{i}. Step {i}\n' for i in range(1, 15))
        self.add_skill('old-alpha', skill('old-alpha', self.ALIAS, 'disable-model-invocation: true\n', body))
        self.assertFinding('ERROR', '.claude/skills/old-alpha/SKILL.md', 'alias', '16 non-blank lines')


if __name__ == '__main__':
    unittest.main()
