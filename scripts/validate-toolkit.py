#!/usr/bin/env python3
"""Validate the OpenSpec toolkit catalog (.claude/ and .cursor/ trees).

Checks command and skill parity between the two trees, frontmatter validity and
keys, skill names, README coverage, the declared exceptions in
scripts/catalog-exceptions.yaml and the routing contract for model-invocable
skill descriptions. Prints one line per finding plus a summary line, and exits 1
when there is at least one ERROR (warnings never change the exit code).

Usage: python3 scripts/validate-toolkit.py [--root DIR]
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

TREES = ('.claude', '.cursor')
EXCEPTIONS_FILE = 'scripts/catalog-exceptions.yaml'

# Routing contract (design of the OpenSpec change toolkit-catalog-validation, D4 and D5).
# The thresholds were measured on this catalog: true duplicates score 0.57-0.66 and
# distinct skills <= 0.29. Changing them is a reviewed change, never a way to get CI green.
COLLISION_ERROR = 0.50
COLLISION_WARN = 0.30
DESCRIPTION_MAX_CHARS = 1024
ALIAS_MAX_BODY_LINES = 15
TRIGGER_RE = re.compile(r'\b(?:use when|use on|auto-invoke on|triggers on)\b', re.IGNORECASE)
ALIAS_RE = re.compile(r'^Deprecated alias of\s+`?([A-Za-z0-9_-]+)`?')

KEBAB_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
FRONTMATTER_RE = re.compile(r'\A﻿?---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)', re.DOTALL)
INNER_BLOCK_RE = re.compile(r'\A\s*---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)', re.DOTALL)
INNER_KEY_RE = re.compile(r'^(?:name|description)\s*:', re.MULTILINE)
TOKEN_RE = re.compile(r'[a-z0-9áéíóúñ]+')

STOP_WORDS = frozenset("""
about above after again against all also and any are around because been before being below
between both but can cannot could did does doing done down during each either else even every
few for from further had has have having her here hers him his how however into its itself just
least less like may might more most much must near need needs neither nor not now off once only
onto other others otherwise our ours out over own per rather same she should since some such
than that the their theirs them then there these they this those though through thus too toward
under until upon very via was way well were what whatever when whenever where whether which
while who whom whose why will with within without would yet you your yours
use uses used using user users want wants asks says auto invoke triggers trigger
que qué los las del por para con sin una uno unos unas como cómo más mas pero sus este esta esto
estos estas ese esa eso esos esas aquel sobre entre hasta desde cuando cuándo donde dónde muy
todo toda todos todas hay ser son está están estar han hace hacer sea les nos algo cada otro
otra otros otras también solo sólo aquí así tras ante bajo cual cuál cuales quien quién quienes
porque pues sino mismo misma mismos mismas tiene tienen tener era eran fue sido
""".split())

# File kind -> (required keys, optional keys).
FRONTMATTER_KEYS = {
    'skill': ({'name', 'description'}, {'disable-model-invocation', 'license', 'compatibility', 'metadata'}),
    'claude-command': ({'description'}, {'argument-hint'}),
    'cursor-command': ({'description'}, {'name', 'id', 'category', 'argument-hint'}),
    'cursor-rule': ({'description', 'alwaysApply'}, {'globs'}),
}

EXCEPTION_SECTIONS = (
    'claude_only_skills',
    'cursor_only_skills',
    'claude_only_commands',
    'cursor_only_commands',
    'description_divergence',
    'skill_groups',
)
DIVERGENCE_KINDS = ('command', 'skill')


@dataclass(frozen=True)
class Finding:
    severity: str  # ERROR or WARN
    path: str
    rule: str
    message: str

    def line(self) -> str:
        message = re.sub(r'\s*\n\s*', ' ', self.message)
        return f'{self.severity} {self.path}: [{self.rule}] {message}'


@dataclass
class Doc:
    rel: str
    meta: dict | None  # None when the frontmatter is missing or invalid
    body: str

    def description(self):
        return None if self.meta is None else self.meta.get('description')


@dataclass
class Item:
    """A skill (key = path under skills/) or a command (key = file stem)."""
    tree: str
    key: str
    name: str
    doc: Doc


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) > 2 and t not in STOP_WORDS]


def tfidf_vectors(descriptions: list[str]) -> list[dict[str, float]]:
    docs = [tokenize(d) for d in descriptions]
    n = len(docs)
    df = Counter()
    for tokens in docs:
        df.update(set(tokens))
    return [
        {term: count * math.log((1 + n) / (1 + df[term])) for term, count in sorted(Counter(tokens).items())}
        for tokens in docs
    ]


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a[t] * b[t] for t in sorted(a.keys() & b.keys()))
    norm_a = math.sqrt(sum(a[t] ** 2 for t in sorted(a)))
    norm_b = math.sqrt(sum(b[t] ** 2 for t in sorted(b)))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def description_similarities(named: list[tuple[str, str]]) -> list[tuple[str, str, float]]:
    """TF-IDF cosine for every pair of (name, description), names in sorted order."""
    named = sorted(named)
    vectors = tfidf_vectors([description for _, description in named])
    pairs = []
    for i in range(len(named)):
        for j in range(i + 1, len(named)):
            pairs.append((named[i][0], named[j][0], cosine(vectors[i], vectors[j])))
    return pairs


def mentions(text: str, name: str) -> bool:
    """True when `name` appears as a token: `name`, name/, /name or (name/...) - never inside a word."""
    for match in re.finditer(rf'(?<![\w-]){re.escape(name)}(?![\w-])', text):
        before = text[match.start() - 1] if match.start() > 0 else ''
        after = text[match.end()] if match.end() < len(text) else ''
        if before in ('`', '/', '(', '[') or after in ('`', '/'):
            return True
    return False


class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.findings: list[Finding] = []
        self.exceptions: dict[str, dict] = {section: {} for section in EXCEPTION_SECTIONS}

    # -- reporting -------------------------------------------------------------

    def error(self, path: str, rule: str, message: str) -> None:
        self.findings.append(Finding('ERROR', path, rule, message))

    def warn(self, path: str, rule: str, message: str) -> None:
        self.findings.append(Finding('WARN', path, rule, message))

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # -- entry point -----------------------------------------------------------

    def run(self) -> list[Finding]:
        self.load_exceptions()
        skills = {tree: self.discover_skills(tree) for tree in TREES}
        commands = {tree: self.discover_commands(tree) for tree in TREES}
        rules = self.discover_rules()

        self.check_set_parity('command', commands)
        self.check_set_parity('skill', skills)
        self.check_description_parity('command', commands)
        self.check_description_parity('skill', skills)
        self.check_skill_groups_alive()
        for tree in TREES:
            self.check_readme(tree, skills[tree])
            self.check_routing(tree, skills[tree])
            self.check_inner_frontmatter(skills[tree])
        self.check_homonym_rules(rules, skills)
        GlobalTree(self).check()
        self.check_global_skills(skills['.claude'])

        severity_rank = {'ERROR': 0, 'WARN': 1}
        return sorted(set(self.findings), key=lambda f: (severity_rank[f.severity], f.path, f.rule, f.message))

    # -- exceptions ------------------------------------------------------------

    def load_exceptions(self) -> None:
        path = self.root / EXCEPTIONS_FILE
        if not path.is_file():
            return
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
        except yaml.YAMLError as exc:
            self.error(EXCEPTIONS_FILE, 'exceptions', f'not valid YAML: {exc}')
            return
        if data is None:
            return
        if not isinstance(data, dict):
            self.error(EXCEPTIONS_FILE, 'exceptions', 'must be a mapping of sections to lists')
            return
        for section, entries in data.items():
            if section not in EXCEPTION_SECTIONS:
                self.error(EXCEPTIONS_FILE, 'exceptions',
                           f"unknown section '{section}' (allowed: {', '.join(EXCEPTION_SECTIONS)})")
                continue
            if entries is None:
                continue
            if not isinstance(entries, list):
                self.error(EXCEPTIONS_FILE, 'exceptions', f"section '{section}' must be a list")
                continue
            for index, entry in enumerate(entries):
                self.load_exception_entry(section, index, entry)

    def load_exception_entry(self, section: str, index: int, entry) -> None:
        label = f'{section}[{index}]'
        if not isinstance(entry, dict):
            self.error(EXCEPTIONS_FILE, 'exceptions', f'{label} must be a mapping with name and reason')
            return
        allowed = {'name', 'reason', 'kind'} if section == 'description_divergence' else {'name', 'reason'}
        for key in sorted(map(str, entry.keys() - allowed)):
            self.error(EXCEPTIONS_FILE, 'exceptions', f"{label} has unknown key '{key}' (allowed: {', '.join(sorted(allowed))})")
        name = entry.get('name')
        if not isinstance(name, str) or not name.strip():
            self.error(EXCEPTIONS_FILE, 'exceptions', f'{label} has no name')
            return
        reason = entry.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            self.error(EXCEPTIONS_FILE, 'exceptions', f"{label} '{name}' has no reason; every exception must say why")
        key = name
        if section == 'description_divergence':
            kind = entry.get('kind')
            if kind not in DIVERGENCE_KINDS:
                self.error(EXCEPTIONS_FILE, 'exceptions', f"{label} '{name}' needs kind: command or kind: skill")
                return
            key = (kind, name)
        self.exceptions[section][key] = entry

    def dead_exception(self, section: str, name: str, why: str) -> None:
        self.error(EXCEPTIONS_FILE, 'exceptions', f"{section} entry '{name}' matches nothing ({why}); remove the entry")

    # -- discovery and per-file checks -----------------------------------------

    def read_doc(self, path: Path, kind: str) -> Doc:
        rel = self.rel(path)
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            self.error(rel, 'frontmatter', 'file is not valid UTF-8')
            return Doc(rel, None, '')
        match = FRONTMATTER_RE.match(text)
        if not match:
            self.error(rel, 'frontmatter', 'missing frontmatter block (the file must start with a --- line)')
            return Doc(rel, None, text)
        body = text[match.end():]
        try:
            meta = yaml.safe_load(match.group(1) or '')
        except yaml.YAMLError as exc:
            self.error(rel, 'frontmatter', f'frontmatter is not valid YAML: {exc}')
            return Doc(rel, None, body)
        if not isinstance(meta, dict):
            self.error(rel, 'frontmatter', 'frontmatter must be a YAML mapping')
            return Doc(rel, None, body)
        doc = Doc(rel, meta, body)
        self.check_keys(doc, kind)
        return doc

    def check_keys(self, doc: Doc, kind: str) -> None:
        required, optional = FRONTMATTER_KEYS[kind]
        allowed = ', '.join(sorted(required | optional))
        for key in sorted(map(str, doc.meta)):
            if key not in required | optional:
                self.error(doc.rel, 'keys', f"unknown frontmatter key '{key}' for a {kind} (allowed: {allowed})")
        for key in sorted(required):
            if doc.meta.get(key) is None or doc.meta.get(key) == '':
                self.error(doc.rel, 'keys', f"missing required frontmatter key '{key}' for a {kind}")
        description = doc.meta.get('description')
        if description is not None and not isinstance(description, str):
            self.error(doc.rel, 'keys', 'description must be a string')

    def check_kebab(self, rel: str, kind: str, name: str) -> None:
        if not KEBAB_RE.match(name):
            self.error(rel, 'name', f"{kind} name '{name}' is not kebab-case (lowercase letters, digits, single hyphens)")

    def add_skill(self, tree: str, skills: dict, key: str, folder: Path) -> None:
        doc = self.read_doc(folder / 'SKILL.md', 'skill')
        self.check_kebab(doc.rel, 'skill', folder.name)
        if doc.meta is not None and 'name' in doc.meta and doc.meta['name'] != folder.name:
            self.error(doc.rel, 'name', f"name '{doc.meta['name']}' does not match its folder '{folder.name}'")
        skills[key] = Item(tree, key, folder.name, doc)

    def discover_skills(self, tree: str) -> dict[str, Item]:
        base = self.root / tree / 'skills'
        skills: dict[str, Item] = {}
        if not base.is_dir():
            return skills
        groups = self.exceptions['skill_groups']
        for entry in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.')):
            if (entry / 'SKILL.md').is_file():
                self.add_skill(tree, skills, entry.name, entry)
            elif entry.name in groups:
                for sub in sorted(p for p in entry.iterdir() if p.is_dir() and not p.name.startswith('.')):
                    if (sub / 'SKILL.md').is_file():
                        self.add_skill(tree, skills, f'{entry.name}/{sub.name}', sub)
                    else:
                        self.error(self.rel(sub), 'skill-folder', 'folder inside a skill group has no SKILL.md')
            else:
                self.error(self.rel(entry), 'skill-folder',
                           f'folder has no SKILL.md and is not a declared skill group ({EXCEPTIONS_FILE}: skill_groups)')
        return skills

    def discover_commands(self, tree: str) -> dict[str, Item]:
        base = self.root / tree / 'commands'
        kind = 'claude-command' if tree == '.claude' else 'cursor-command'
        commands: dict[str, Item] = {}
        if not base.is_dir():
            return commands
        for path in sorted(base.glob('*.md')):
            doc = self.read_doc(path, kind)
            self.check_kebab(doc.rel, 'command', path.stem)
            commands[path.stem] = Item(tree, path.stem, path.stem, doc)
        return commands

    def discover_rules(self) -> dict[str, Doc]:
        base = self.root / '.cursor' / 'rules'
        if not base.is_dir():
            return {}
        return {path.stem: self.read_doc(path, 'cursor-rule') for path in sorted(base.glob('*.mdc'))}

    # -- cross-tree checks -----------------------------------------------------

    def check_set_parity(self, kind: str, items: dict[str, dict[str, Item]]) -> None:
        claude, cursor = items['.claude'], items['.cursor']
        suffix = '.md' if kind == 'command' else ''
        for present, missing, other in (('.claude', '.cursor', cursor), ('.cursor', '.claude', claude)):
            section = f"{present.lstrip('.')}_only_{kind}s"
            declared = self.exceptions[section]
            here = items[present]
            for key in sorted(here.keys() - other.keys()):
                if key in declared:
                    continue
                self.error(here[key].doc.rel, f'{kind}-parity',
                           f"{kind} '{key}{suffix}' exists in {present} but is missing from {missing} "
                           f"(declare it in {EXCEPTIONS_FILE}: {section} if intentional)")
            for name in sorted(declared):
                if name not in here:
                    self.dead_exception(section, name, f'no {kind} of that name in {present}')
                elif name in other:
                    self.dead_exception(section, name, f'it also exists in {missing}')

    def check_description_parity(self, kind: str, items: dict[str, dict[str, Item]]) -> None:
        claude, cursor = items['.claude'], items['.cursor']
        declared = self.exceptions['description_divergence']
        for key in sorted(claude.keys() & cursor.keys()):
            a, b = claude[key].doc, cursor[key].doc
            if a.meta is None or b.meta is None or a.description() == b.description():
                continue
            if (kind, key) in declared:
                continue
            self.error(a.rel, 'description-parity',
                       f"{kind} '{key}' has a different description in each tree "
                       f"(declare it in {EXCEPTIONS_FILE}: description_divergence if intentional): "
                       f".claude: {a.description()!r} | .cursor: {b.description()!r}")
        for entry_kind, name in sorted(k for k in declared if k[0] == kind):
            if name not in claude or name not in cursor:
                self.dead_exception('description_divergence', name, f'no {kind} of that name in both trees')
                continue
            a, b = claude[name].doc, cursor[name].doc
            if a.meta is not None and b.meta is not None and a.description() == b.description():
                self.dead_exception('description_divergence', name, 'the descriptions are equal')

    def check_skill_groups_alive(self) -> None:
        for name in sorted(self.exceptions['skill_groups']):
            folders = [self.root / tree / 'skills' / name for tree in TREES]
            if not any(f.is_dir() and not (f / 'SKILL.md').is_file() for f in folders):
                self.dead_exception('skill_groups', name, 'no skills folder of that name without a SKILL.md')

    def check_readme(self, tree: str, skills: dict[str, Item]) -> None:
        if not skills:
            return
        readme = self.root / tree / 'skills' / 'README.md'
        rel = self.rel(readme)
        if not readme.is_file():
            self.error(rel, 'readme-coverage', 'skills README is missing')
            return
        text = readme.read_text(encoding='utf-8')
        for key in sorted(skills):
            name = skills[key].name
            if not mentions(text, name):
                self.error(rel, 'readme-coverage',
                           f"skill '{key}' is not mentioned in {rel} (write it as `{name}` or link {name}/SKILL.md)")

    # -- routing contract ------------------------------------------------------

    def check_routing(self, tree: str, skills: dict[str, Item]) -> None:
        names = {item.name for item in skills.values()}
        invocable: list[tuple[str, str]] = []
        rel_of = {}
        for key in sorted(skills):
            doc = skills[key].doc
            description = doc.description()
            if not isinstance(description, str):
                continue
            if len(description) > DESCRIPTION_MAX_CHARS:
                self.error(doc.rel, 'description-length',
                           f'description has {len(description)} characters (max {DESCRIPTION_MAX_CHARS})')
            exempt = doc.meta.get('disable-model-invocation') is True
            alias = ALIAS_RE.match(description)
            if alias:
                self.check_alias(tree, doc, alias.group(1), exempt, names)
            if exempt:
                continue
            if not TRIGGER_RE.search(description):
                self.error(doc.rel, 'trigger-clause',
                           'description has no trigger clause (Use when / Use on / Auto-invoke on / Triggers on)')
            invocable.append((key, description))
            rel_of[key] = doc.rel
        for first, second, score in description_similarities(invocable):
            if score >= COLLISION_ERROR:
                self.error(rel_of[first], 'collision',
                           f"descriptions of '{first}' and '{second}' collide in {tree} "
                           f'(TF-IDF cosine {score:.2f} >= {COLLISION_ERROR:.2f})')
            elif score >= COLLISION_WARN:
                self.warn(rel_of[first], 'collision',
                          f"descriptions of '{first}' and '{second}' are close in {tree} "
                          f'(TF-IDF cosine {score:.2f} >= {COLLISION_WARN:.2f})')

    def check_alias(self, tree: str, doc: Doc, canonical: str, exempt: bool, names: set[str]) -> None:
        if not exempt:
            self.error(doc.rel, 'alias', 'a deprecated alias must set disable-model-invocation: true')
        if canonical not in names:
            self.error(doc.rel, 'alias', f"names '{canonical}', which is not a skill in {tree}")
        lines = [line for line in doc.body.splitlines() if line.strip()]
        if len(lines) > ALIAS_MAX_BODY_LINES:
            self.error(doc.rel, 'alias',
                       f'alias body has {len(lines)} non-blank lines (max {ALIAS_MAX_BODY_LINES}); '
                       f'point to {canonical} instead of carrying a workflow')

    # -- hygiene warnings ------------------------------------------------------

    def check_global_skills(self, catalog: dict[str, Item]) -> None:
        """Skills in global/ obey the routing rules and do not collide with the catalog they install next to."""
        gskills = self.discover_skills(GLOBAL_DIR)
        if not gskills:
            return
        self.check_routing(GLOBAL_DIR, gskills)
        self.check_inner_frontmatter(gskills)
        for key, item in gskills.items():
            if item.name in {c.name for c in catalog.values()}:
                self.error(item.doc.rel, 'global-skill', f"skill '{item.name}' is also in the .claude catalog")
            mine = item.doc.description()
            if not isinstance(mine, str):
                continue
            pairs = [(f'{GLOBAL_DIR}:{key}', mine)] + [(k, c.doc.description()) for k, c in catalog.items()
                                                      if isinstance(c.doc.description(), str)
                                                      and c.doc.meta.get('disable-model-invocation') is not True]
            for first, second, score in description_similarities(pairs):
                if first == f'{GLOBAL_DIR}:{key}' or second == f'{GLOBAL_DIR}:{key}':
                    other = second if first.startswith(GLOBAL_DIR + ':') else first
                    if score >= COLLISION_ERROR:
                        self.error(item.doc.rel, 'collision', f"description collides with '{other}' "
                                   f'(TF-IDF cosine {score:.2f} >= {COLLISION_ERROR:.2f})')

    def check_inner_frontmatter(self, skills: dict[str, Item]) -> None:
        for key in sorted(skills):
            doc = skills[key].doc
            if doc.meta is None:
                continue
            block = INNER_BLOCK_RE.match(doc.body)
            if block and INNER_KEY_RE.search(block.group(1)):
                self.warn(doc.rel, 'inner-frontmatter',
                          'body starts with a second frontmatter-like block (stale name/description); remove it')

    def check_homonym_rules(self, rules: dict[str, Doc], skills: dict[str, dict[str, Item]]) -> None:
        for name in sorted(rules):
            rule = rules[name]
            skill = skills['.cursor'].get(name) or skills['.claude'].get(name)
            if rule.meta is None or skill is None or skill.doc.meta is None:
                continue
            if rule.description() != skill.doc.description():
                self.warn(rule.rel, 'homonym-rule',
                          f"description differs from its homonym skill {skill.doc.rel}: "
                          f"rule {rule.description()!r} | skill {skill.doc.description()!r}")


GLOBAL_DIR = 'global'
GLOBAL_META = ('modules', 'settings', 'contracts', 'config')   # referenced by manifests, not installed as files
CITATION_RE = re.compile(r'~/\.claude/((?:rules|scripts|hooks|skills)/[A-Za-z0-9_.\-/]+)')


class GlobalTree:
    """Checks of global/: manifests, orphans, hook fragments, contracts and cited pieces (task 6.1)."""

    def __init__(self, v: Validator):
        self.v = v
        self.root = v.root
        self.base = v.root / GLOBAL_DIR

    def check(self) -> None:
        if not (self.base / 'modules').is_dir():
            return
        mods = {}
        for path in sorted((self.base / 'modules').glob('*.yaml')):
            rel = self.v.rel(path)
            try:
                data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            except yaml.YAMLError as exc:
                self.v.error(rel, 'global-manifest', f'invalid YAML: {exc}')
                continue
            if data.get('name') != path.stem:
                self.v.error(rel, 'global-manifest', f'name must be {path.stem!r}')
            mods[path.stem] = (rel, data)
        dests = {name: self.dests(rel, data) for name, (rel, data) in mods.items()}
        for name, (rel, data) in mods.items():
            for dep in data.get('depends') or []:
                if dep not in mods:
                    self.v.error(rel, 'global-manifest', f'depends on unknown module {dep!r}')
            for frag in data.get('hooks') or []:
                if not (self.root / frag).is_file():
                    self.v.error(rel, 'global-manifest', f'hook fragment {frag} does not exist')
            for piece in data.get('config') or []:
                if not (self.base / 'config' / f'{piece}.json').is_file():
                    self.v.error(rel, 'global-manifest', f'config piece {piece!r} has no global/config/{piece}.json')
        self.check_orphans(mods)
        self.check_hooks(mods, dests)
        self.check_contracts(mods, dests)
        self.check_citations(mods, dests)

    def dests(self, rel: str, data: dict) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for entry in data.get('files') or []:
            src = self.root / entry.get('src', '')
            dest = entry.get('dest', '')
            if entry.get('src', '').endswith('/'):
                if not src.is_dir():
                    self.v.error(rel, 'global-manifest', f'source directory {entry.get("src")} does not exist')
                    continue
                excludes = [e.rstrip('/') for e in entry.get('exclude') or []]
                for path in sorted(src.rglob('*')):
                    r = path.relative_to(src).as_posix()
                    if path.is_file() and '__pycache__' not in r and not any(r == e or r.startswith(e + '/') for e in excludes):
                        out[f'{dest.rstrip("/")}/{r}'] = path
            elif not src.is_file():
                self.v.error(rel, 'global-manifest', f'source {entry.get("src")} does not exist')
            else:
                out[dest] = src
        return out

    def closure(self, mods: dict, name: str, seen: set | None = None) -> set[str]:
        seen = seen if seen is not None else set()
        if name in seen or name not in mods:
            return seen
        seen.add(name)
        for dep in mods[name][1].get('depends') or []:
            self.closure(mods, dep, seen)
        return seen

    def check_orphans(self, mods: dict) -> None:
        sources = [(self.root / e.get('src', '')) for _, data in mods.values() for e in data.get('files') or []]
        frags = {self.root / f for _, data in mods.values() for f in data.get('hooks') or []}
        pieces = {p for _, data in mods.values() for p in data.get('config') or []}
        for path in sorted(self.base.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            top = path.relative_to(self.base).parts[0]
            rel = self.v.rel(path)
            if top == 'modules' or top == 'contracts':
                continue
            if top == 'settings':
                if path not in frags:
                    self.v.error(rel, 'global-orphan', 'hook fragment not listed by any module')
                continue
            if top == 'config':
                if path.stem not in pieces:
                    self.v.error(rel, 'global-orphan', 'config piece not listed by any module')
                continue
            owners = sum(1 for s in sources if path == s or s in path.parents)
            if owners == 0:
                self.v.error(rel, 'global-orphan', 'file is not installed by any module')
            elif owners > 1:
                self.v.error(rel, 'global-orphan', f'file is installed by {owners} manifest entries')

    def check_hooks(self, mods: dict, dests: dict) -> None:
        for name, (rel, data) in mods.items():
            reach = set().union(*(dests.get(m, {}).keys() for m in self.closure(mods, name)))
            for frag in data.get('hooks') or []:
                path = self.root / frag
                if not path.is_file():
                    continue
                try:
                    block = __import__('json').loads(path.read_text(encoding='utf-8'))
                except ValueError as exc:
                    self.v.error(frag, 'global-hooks', f'invalid JSON: {exc}')
                    continue
                for entries in block.values():
                    for entry in entries or []:
                        for hook in entry.get('hooks') or []:
                            for cited in CITATION_RE.findall(hook.get('command', '')):
                                if cited not in reach:
                                    self.v.error(frag, 'global-hooks', f'command runs ~/.claude/{cited}, which module {name!r} does not install')

    def check_contracts(self, mods: dict, dests: dict) -> None:
        contracts = {}
        for path in sorted((self.base / 'contracts').glob('*.yaml')) if (self.base / 'contracts').is_dir() else []:
            try:
                data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            except yaml.YAMLError as exc:
                self.v.error(self.v.rel(path), 'global-contract', f'invalid YAML: {exc}')
                continue
            contracts[data.get('dest')] = self.v.rel(path)
            if not data.get('probes'):
                self.v.error(self.v.rel(path), 'global-contract', 'contract has no probes')
        installed = {d: m for m, ds in dests.items() for d in ds}
        for dest, rel in contracts.items():
            if dest not in installed:
                self.v.error(rel, 'global-contract', f'contract for {dest}, which no module installs')
        for dest, module in sorted(installed.items()):
            if dest.startswith('hooks/') and dest not in contracts:
                self.v.error(mods[module][0], 'global-contract', f'hook {dest} has no contract in {GLOBAL_DIR}/contracts/')

    def check_citations(self, mods: dict, dests: dict) -> None:
        for name, (rel, data) in mods.items():
            reach = set().union(*(dests.get(m, {}).keys() for m in self.closure(mods, name)))
            provided = set(data.get('project_provided') or [])
            reach_dirs = {d.rsplit('/', 1)[0] for d in reach if d.startswith('skills/')}
            for dest, src in dests.get(name, {}).items():
                if not str(src).startswith(str(self.base)):
                    continue   # the OpenSpec catalog is checked by the catalog rules
                try:
                    text = src.read_text(encoding='utf-8')
                except (OSError, UnicodeDecodeError):
                    continue
                for cited in sorted(set(CITATION_RE.findall(text))):
                    cited = cited.rstrip('.`/')
                    if cited in reach or cited in provided or cited in reach_dirs:
                        continue
                    if any(d.startswith(cited + '/') for d in reach):
                        continue   # a folder (or a glob in it) the module fills, like a skill's or a package's
                    self.v.error(self.v.rel(src), 'global-citation',
                                 f'cites ~/.claude/{cited}, which module {name!r} and its dependencies do not install')


def validate(root: Path) -> list[Finding]:
    return Validator(Path(root).resolve()).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Validate the OpenSpec toolkit catalog.')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent,
                        help='repository root (default: the parent of this script\'s folder)')
    args = parser.parse_args(argv)
    findings = validate(args.root)
    for finding in findings:
        print(finding.line())
    errors = sum(1 for f in findings if f.severity == 'ERROR')
    warnings = len(findings) - errors
    print(f'validate-toolkit: {errors} error(s), {warnings} warning(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
