"""Tests of global/scripts/ask-queue and global/hooks/ask-queue-prompt, on the repository's pieces.

Every path is redirected into a temp dir (HOME, the queue, the supervisor state, the session registry, the app records,
the transcripts and the toolkit config), and the variables that could point at real state are removed, so the real
queue, locks and sessions are never touched. The prompt hook loads the repository's supervisor-lock.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = str(REPO_ROOT / 'global/scripts/ask-queue')
HOOK = str(REPO_ROOT / 'global/hooks/ask-queue-prompt')
LOCK_SCRIPT = str(REPO_ROOT / 'global/scripts/supervisor-lock')
# variables that could point a piece at the developer's real state or carry the session running the tests
SCRUB_PREFIXES = ('ASK_QUEUE', 'ASK_GATE', 'SUPERVISOR_', 'PROJECT_PAUSE', 'CROSS_PROJECT_GATE_', 'ACCOUNT_SWITCH',
                  'CLOUD_TESTS_', 'CLAUDE_TOOLKIT_', 'CLAUDE_CODE_', 'CLAUDE_SESSION_ID', 'CLAUDE_CONFIG_DIR')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ask-queue-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = os.path.join(self.tmp, 'state')
        self.lock_home = os.path.join(self.tmp, 'sup')  # hermetic: never read the real supervision locks
        home = os.path.join(self.tmp, 'home')
        config = os.path.join(self.tmp, 'toolkit-config')
        os.makedirs(home)
        os.makedirs(config)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB_PREFIXES)}
        self.env.update(HOME=home, CLAUDE_TOOLKIT_CONFIG_DIR=config, ASK_QUEUE_DIR=self.state,
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, SUPERVISOR_LOCK_HOME=self.lock_home,
                        SUPERVISOR_SESSIONS_DIR=os.path.join(self.tmp, 'no-sessions'),
                        SUPERVISOR_APP_SESSIONS_GLOB=os.path.join(self.tmp, 'no-app', '*', '*', 'local_*.json'),
                        SUPERVISOR_PROJECTS_DIR=os.path.join(self.tmp, 'no-projects'),
                        ASK_QUEUE_BIN=SCRIPT, SUPERVISOR_LOCK_BIN=LOCK_SCRIPT)
        for name in ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_HOST_SESSION_ID', 'CLAUDE_SESSION_ID'):
            self.env.pop(name, None)  # hermetic: never record the session running the tests as an origin
        self.env['PROJECT_PAUSE_BIN'] = '/nonexistent/project-pause'  # hermetic: the real paused projects don't count

    def write_lock(self, name, checkout, common_dir=None, heartbeat=None, **extra):
        os.makedirs(os.path.join(self.lock_home, 'locks'), exist_ok=True)
        lock = {'key': name, 'checkout': checkout, 'common_dir': common_dir, 'state': 'running',
                'heartbeat': heartbeat or datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
                'session_id': 'local_x', **extra}
        with open(os.path.join(self.lock_home, 'locks', name + '.json'), 'w') as fh:
            json.dump(lock, fh)

    def mkdir(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        return path

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=self.env)

    def add(self, project, question='¿Pago el plan?', **extra):
        fields = dict(question=question, default='no pagar', why='cuesta dinero', blocks='el despliegue')
        fields.update(extra)
        cmd = ['add', '--project', project]
        for key, value in fields.items():
            cmd += ['--' + key, value]
        r = self.run_cli(*cmd)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def listing(self, *args):
        return json.loads(self.run_cli('list', '--json', *args).stdout)

    def make_repo(self, name):
        path = self.mkdir(name)
        subprocess.run(['git', 'init', '-q', path], check=True)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'i'],
                       cwd=path, check=True, capture_output=True)
        return path


class AskQueueTest(Base):
    def test_add_prints_id_and_stores_all_fields(self):
        proj = self.mkdir('plain')
        qid = self.add(proj, session='sess-1')
        (item,) = self.listing('--project', proj)
        self.assertEqual(item['id'], qid)
        self.assertEqual((item['status'], item['answer']), ('open', None))
        self.assertEqual((item['question'], item['default']), ('¿Pago el plan?', 'no pagar'))
        self.assertEqual((item['why'], item['blocks'], item['session']), ('cuesta dinero', 'el despliegue', 'sess-1'))
        self.assertEqual(item['project'], os.path.realpath(proj))
        self.assertTrue(item['ts'])

    def test_file_name_is_basename_and_sha1_prefix(self):
        self.add(self.mkdir('plain'))
        names = [n for n in os.listdir(self.state) if n.endswith('.jsonl')]
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r'^plain-[0-9a-f]{8}\.jsonl$')

    def test_worktree_maps_to_main_checkout(self):
        repo = self.make_repo('repo')
        wt = os.path.join(self.tmp, 'repo-wt')
        subprocess.run(['git', 'worktree', 'add', '-q', '-b', 'b', wt], cwd=repo, check=True, capture_output=True)
        self.add(wt, 'desde el worktree')
        self.add(repo, 'desde el checkout')
        in_repo = self.listing('--project', repo)
        self.assertEqual({i['question'] for i in in_repo}, {'desde el worktree', 'desde el checkout'})
        self.assertEqual({i['project'] for i in in_repo}, {os.path.realpath(repo)})
        self.assertEqual(len(self.listing('--project', wt)), 2)

    def test_subdirectory_of_repo_uses_the_repo_root(self):
        repo = self.make_repo('repo')
        sub = os.path.join(repo, 'sub')
        os.makedirs(sub)
        self.add(sub)
        self.assertEqual(self.listing('--project', repo)[0]['project'], os.path.realpath(repo))

    def test_projects_are_separate_and_list_without_project_shows_all(self):
        a, b = self.mkdir('a'), self.mkdir('b')
        self.add(a, 'de a')
        self.add(b, 'de b')
        self.assertEqual([i['question'] for i in self.listing('--project', a)], ['de a'])
        self.assertEqual(sorted(i['question'] for i in self.listing()), ['de a', 'de b'])

    def test_dot_named_project_is_visible_to_list_answer_close_and_asked(self):
        # A project folder like ~/.claude gives a queue file named '.claude-<hash>.jsonl'; glob skips dot-files.
        hidden, plain = self.mkdir('.hidden'), self.mkdir('plain')
        first, second, third = self.add(hidden, 'uno'), self.add(hidden, 'dos'), self.add(hidden, 'tres')
        self.add(plain, 'normal')
        names = sorted(n for n in os.listdir(self.state) if n.endswith('.jsonl'))
        self.assertTrue(any(n.startswith('.hidden-') for n in names), names)
        self.assertEqual(sorted(i['question'] for i in self.listing()), ['dos', 'normal', 'tres', 'uno'])
        self.assertEqual(len(self.listing('--open')), 4)
        self.assertEqual(self.run_cli('answer', first, '--text', 'sí').returncode, 0)
        self.assertEqual(self.run_cli('close', second, '--note', 'no hace falta').returncode, 0)
        self.assertEqual(self.run_cli('asked', third, '--to', 'x').returncode, 0)
        by_id = {i['id']: i for i in self.listing()}
        self.assertEqual((by_id[first]['status'], by_id[first]['answer']), ('answered', 'sí'))
        self.assertEqual(by_id[second]['status'], 'closed')
        self.assertEqual(by_id[third]['status'], 'asked')
        # '.lock' files must not be picked up as queue files
        self.assertEqual(len(by_id), 4)

    def test_answer_and_close_change_status_and_open_filter(self):
        proj = self.mkdir('p')
        first, second, third = self.add(proj, 'uno'), self.add(proj, 'dos'), self.add(proj, 'tres')
        self.assertEqual(self.run_cli('answer', first, '--text', 'sí, paga').returncode, 0)
        self.assertEqual(self.run_cli('close', second, '--note', 'ya no hace falta').returncode, 0)
        by_id = {i['id']: i for i in self.listing('--project', proj)}
        self.assertEqual((by_id[first]['status'], by_id[first]['answer']), ('answered', 'sí, paga'))
        self.assertEqual((by_id[second]['status'], by_id[second]['note']), ('closed', 'ya no hace falta'))
        self.assertEqual(by_id[third]['status'], 'open')
        self.assertEqual([i['id'] for i in self.listing('--project', proj, '--open')], [third])

    def test_unknown_id_fails_with_exit_2(self):
        self.add(self.mkdir('p'))
        for cmd in (['answer', 'nope', '--text', 'x'], ['close', 'nope']):
            r = self.run_cli(*cmd)
            self.assertEqual(r.returncode, 2)
            self.assertIn('no item nope', r.stderr)

    def test_add_requires_every_field(self):
        r = self.run_cli('add', '--project', self.tmp, '--question', 'q', '--default', 'd', '--why', 'w')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--blocks', r.stderr)

    def test_text_output(self):
        proj = self.mkdir('p')
        qid = self.add(proj)
        out = self.run_cli('list', '--project', proj).stdout
        for needle in (qid, '¿Pago el plan?', 'no pagar', 'cuesta dinero', 'el despliegue'):
            self.assertIn(needle, out)
        self.assertEqual(self.run_cli('list', '--project', self.mkdir('empty')).stdout.strip(), '(no items)')

    def test_concurrent_adds_lose_nothing(self):
        proj = self.mkdir('p')
        ids = []
        threads = [threading.Thread(target=lambda n=n: ids.append(self.add(proj, f'pregunta {n}'))) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        items = self.listing('--project', proj)
        self.assertEqual(len(items), 8)
        self.assertEqual({i['id'] for i in items}, set(ids))
        self.assertEqual(len(set(ids)), 8)

    def test_add_with_same_key_updates_instead_of_duplicating(self):
        proj = self.mkdir('p')
        first = self.add(proj, 'voz del vídeo', key='voz-portada')
        again = self.add(proj, 'otra redacción distinta', key='voz-portada', default='sin voz')
        self.assertEqual(first, again)
        (item,) = self.listing('--project', proj)
        self.assertEqual((item['question'], item['default'], item['key']), ('otra redacción distinta', 'sin voz', 'voz-portada'))
        self.assertNotEqual(self.add(proj, 'otra', key='otra-clave'), first)
        self.assertEqual(len(self.listing('--project', proj)), 2)

    def test_add_with_same_normalized_text_updates_instead_of_duplicating(self):
        proj = self.mkdir('p')
        first = self.add(proj, '¿Pago el plan Pro?')
        again = self.add(proj, '  pago   el PLAN pro ', why='ahora cuesta más')
        self.assertEqual(first, again)
        (item,) = self.listing('--project', proj)
        self.assertEqual((item['question'], item['why']), ('  pago   el PLAN pro ', 'ahora cuesta más'))
        self.run_cli('asked', first)
        self.assertEqual(self.add(proj, 'Pago el plan pro'), first)  # an asked item still counts
        self.run_cli('answer', first, '--text', 'sí')
        self.assertNotEqual(self.add(proj, '¿Pago el plan Pro?'), first)  # answered: a new question is a new item
        self.assertEqual(len(self.listing('--project', proj)), 2)

    def test_radical_and_cost_round_trip(self):
        repo = self.mkdir('p')
        plain = self.add(repo, 'normal')
        r = self.run_cli('add', '--project', repo, '--question', '¿Elijo la base?', '--default', 'A', '--why', 'w',
                         '--blocks', 'b', '--radical', '--cost', '2 specs, ~6 h de trabajo')
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = r.stdout.strip()
        items = {i['id']: i for i in self.listing('--project', repo)}
        self.assertIs(items[rid]['radical'], True)
        self.assertEqual(items[rid]['cost'], '2 specs, ~6 h de trabajo')
        self.assertNotIn('radical', items[plain])
        self.assertNotIn('cost', items[plain])
        out = self.run_cli('list', '--project', repo).stdout
        self.assertIn('[RADICAL] ¿Elijo la base?', out)
        self.assertIn('cost: 2 specs, ~6 h de trabajo', out)
        self.assertEqual(out.count('[RADICAL]'), 1)
        self.assertEqual(out.count('cost:'), 1)

    def test_list_radical_filter_combines_with_open_and_unasked(self):
        repo = self.mkdir('p')
        self.add(repo, 'normal')
        rid = self.run_cli('add', '--project', repo, '--question', 'radical uno', '--default', 'A', '--why', 'w',
                           '--blocks', 'b', '--radical').stdout.strip()
        rid2 = self.run_cli('add', '--project', repo, '--question', 'radical dos', '--default', 'A', '--why', 'w',
                            '--blocks', 'b', '--radical').stdout.strip()
        self.assertEqual({i['id'] for i in self.listing('--project', repo, '--radical')}, {rid, rid2})
        self.run_cli('answer', rid2, '--text', 'ok')
        self.assertEqual([i['id'] for i in self.listing('--project', repo, '--radical', '--open')], [rid])
        self.run_cli('asked', rid, '--to', 'x')
        self.assertEqual(self.listing('--project', repo, '--radical', '--unasked'), [])
        self.assertEqual([i['id'] for i in self.listing('--project', repo, '--radical', '--open')], [rid])

    def test_duplicate_is_upgraded_to_radical_but_never_downgraded(self):
        repo = self.mkdir('p')
        first = self.add(repo, '¿Misma pregunta?')
        r = self.run_cli('add', '--project', repo, '--question', '¿misma pregunta', '--default', 'no pagar',
                         '--why', 'cuesta dinero', '--blocks', 'el despliegue', '--radical',
                         '--cost', '1 spec, ~3 h')
        self.assertEqual(r.stdout.strip(), first)
        items = self.listing('--project', repo)
        self.assertEqual(len(items), 1)
        self.assertIs(items[0]['radical'], True)
        self.assertEqual(items[0]['cost'], '1 spec, ~3 h')
        again = self.add(repo, '¿Misma pregunta?')
        self.assertEqual(again, first)
        self.assertIs(self.listing('--project', repo)[0]['radical'], True)

    def test_asked_marks_status_and_counts(self):
        proj = self.mkdir('p')
        a, b, done = self.add(proj, 'uno'), self.add(proj, 'dos'), self.add(proj, 'tres')
        self.run_cli('answer', done, '--text', 'ok')
        r = self.run_cli('asked', a, b, done, '--to', 'local_mb')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f'{done} already answered', r.stdout)
        by_id = {i['id']: i for i in self.listing('--project', proj)}
        self.assertEqual((by_id[a]['status'], by_id[a]['asked_to'], by_id[a]['asked_n']), ('asked', 'local_mb', 1))
        self.assertTrue(by_id[a]['asked_ts'])
        self.assertEqual((by_id[done]['status'], by_id[done].get('asked_n')), ('answered', None))
        self.run_cli('asked', a)
        self.assertEqual({i['id']: i for i in self.listing('--project', proj)}[a]['asked_n'], 2)
        self.assertEqual(self.run_cli('asked', 'nope').returncode, 2)

    def test_pending_reports_status_and_answer(self):
        proj = self.mkdir('p')
        o, a, ans, cl = (self.add(proj, t) for t in ('o', 'a', 'ans', 'cl'))
        self.run_cli('asked', a)
        self.run_cli('answer', ans, '--text', 'sí,\ngrábalas')
        self.run_cli('close', cl)
        r = self.run_cli('pending', o, a, ans, cl, 'ghost')
        self.assertEqual(r.returncode, 0)
        rows = [line.split('\t') for line in r.stdout.splitlines()]
        self.assertEqual([row[:2] for row in rows], [[o, 'open'], [a, 'asked'], [ans, 'answered'], [cl, 'closed'],
                                                     ['ghost', 'missing']])
        self.assertEqual(rows[2][3], 'sí, grábalas')
        self.assertRegex(rows[2][2], r'^\d{4}-\d\d-\d\dT')

    def test_list_open_includes_asked_and_unasked_applies_the_reask_threshold(self):
        proj = self.mkdir('p')
        fresh, asked_now, asked_old, done = (self.add(proj, t) for t in ('fresh', 'asked now', 'asked old', 'done'))
        self.run_cli('asked', asked_now, asked_old)
        self.run_cli('answer', done, '--text', 'ok')
        (name,) = [n for n in os.listdir(self.state) if n.endswith('.jsonl')]
        path = os.path.join(self.state, name)
        with open(path) as fh:
            rows = [json.loads(line) for line in fh]
        for row in rows:
            if row['id'] == asked_old:
                row['asked_ts'] = '2020-01-01T00:00:00+00:00'
        with open(path, 'w') as fh:
            fh.writelines(json.dumps(row) + '\n' for row in rows)
        ids = lambda *a: {i['id'] for i in self.listing('--project', proj, *a)}  # noqa: E731
        self.assertEqual(ids('--open'), {fresh, asked_now, asked_old})
        self.assertEqual(ids('--unasked'), {fresh, asked_old})
        r = subprocess.run([sys.executable, SCRIPT, 'list', '--json', '--project', proj, '--unasked'],
                           capture_output=True, text=True, env=dict(self.env, ASK_QUEUE_REASK_H='1000000'))
        self.assertEqual({i['id'] for i in json.loads(r.stdout)}, {fresh})

    def test_answer_and_close_work_from_asked_and_leave_finished_items_alone(self):
        proj = self.mkdir('p')
        a, b = self.add(proj, 'uno'), self.add(proj, 'dos')
        self.run_cli('asked', a, b)
        self.assertEqual(self.run_cli('answer', a, '--text', 'sí').returncode, 0)
        self.assertEqual(self.run_cli('close', b, '--note', 'n').returncode, 0)
        r = self.run_cli('answer', a, '--text', 'no, mejor no')
        self.assertEqual(r.returncode, 0)
        self.assertIn('already answered', r.stderr)
        self.run_cli('close', a)
        by_id = {i['id']: i for i in self.listing('--project', proj)}
        self.assertEqual((by_id[a]['status'], by_id[a]['answer']), ('answered', 'sí'))
        self.assertEqual(by_id[b]['status'], 'closed')

    def test_old_items_without_new_fields_keep_working(self):
        proj = self.mkdir('p')
        qid = self.add(proj, 'vieja')
        (name,) = [n for n in os.listdir(self.state) if n.endswith('.jsonl')]
        old = {'id': 'q-old', 'ts': '2000-01-01T10:00:00+01:00', 'project': os.path.realpath(proj), 'session': '',
               'question': 'Pregunta antigua', 'default': 'd', 'why': 'w', 'blocks': 'b', 'status': 'open', 'answer': None}
        with open(os.path.join(self.state, name), 'a') as fh:
            fh.write(json.dumps(old) + '\n')
        self.assertEqual(self.add(proj, 'pregunta antigua'), 'q-old')
        self.assertEqual(self.run_cli('asked', 'q-old').returncode, 0)
        self.assertEqual(self.run_cli('pending', 'q-old', qid).stdout.split(), ['q-old', 'asked', qid, 'open'])

    def test_corrupt_lines_are_skipped(self):
        proj = self.mkdir('p')
        self.add(proj)
        (name,) = [n for n in os.listdir(self.state) if n.endswith('.jsonl')]
        with open(os.path.join(self.state, name), 'a') as fh:
            fh.write('not json\n')
        self.assertEqual(len(self.listing('--project', proj)), 1)


class AskQueuePromptHookTest(Base):
    def setUp(self):
        super().setUp()
        self.lock_home = os.path.join(self.tmp, 'lock-home')
        self.sessions = self.mkdir('sessions')
        self.env.update(SUPERVISOR_LOCK_HOME=self.lock_home, SUPERVISOR_SESSIONS_DIR=self.sessions,
                        SUPERVISOR_APP_SESSIONS_GLOB=os.path.join(self.tmp, 'app', '*', '*', 'local_*.json'),
                        SUPERVISOR_PROJECTS_DIR=self.mkdir('projects'))
        self.env['ASK_QUEUE_BIN'] = SCRIPT   # the repository's queue, never an installed one
        self.env.pop('ASK_QUEUE_REASK_H', None)
        # an item is only shown in the session that queued it (or the questions session); by default the
        # items of these tests are queued by the session the developer writes in (cli-human)
        self.env['CLAUDE_CODE_SESSION_ID'] = 'cli-human'

    def app_record(self, local, cli, cwd, title, archived=False):
        directory = os.path.join(self.tmp, 'app', 'acct', 'org')
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, local + '.json'), 'w') as fh:
            json.dump({'sessionId': local, 'cliSessionId': cli, 'cwd': cwd, 'title': title, 'isArchived': archived}, fh)

    def human(self, cwd, prompt='hola', session='cli-human', **extra):
        return dict({'hook_event_name': 'UserPromptSubmit', 'cwd': cwd, 'prompt': prompt, 'session_id': session}, **extra)

    def hook(self, cwd, payload=None, **env):
        data = json.dumps(payload if payload is not None else self.human(cwd))
        return subprocess.run([sys.executable, HOOK], input=data, capture_output=True, text=True,
                              env=dict(self.env, **env))

    def log_lines(self):
        try:
            with open(os.path.join(self.state, 'prompt-hook.log')) as fh:
                return [line.rstrip('\n').split('\t') for line in fh]
        except OSError:
            return []

    def session_record(self, name, local, cwd, title='trabajo'):
        with open(os.path.join(self.sessions, name + '.json'), 'w') as fh:
            json.dump({'pid': os.getpid(), 'cwd': cwd, 'sessionId': 'cli-' + name, 'hostSessionId': local,
                       'name': title, 'status': 'busy'}, fh)

    def supervise(self, repo, mailbox=None, ago=10, state='running'):
        """A supervisor lock for `repo` owned by local_owner (CLI session cli-owner), optionally with a mailbox."""
        info = json.loads(subprocess.run([sys.executable, LOCK_SCRIPT, 'project', '--dir', repo, '--json'],
                                         capture_output=True, text=True, env=self.env, check=True).stdout)
        os.makedirs(os.path.join(self.lock_home, 'locks'), exist_ok=True)
        beat = datetime.fromtimestamp(time.time() - ago, timezone.utc).isoformat(timespec='seconds')
        lock = {'key': info['key'], 'project': info['name'], 'session_id': 'local_owner', 'title': 'sup', 'state': state,
                'phase': 'F1', 'round': 1, 'heartbeat': beat}
        if mailbox:
            lock['mailbox'] = mailbox
        with open(os.path.join(self.lock_home, 'locks', info['key'] + '.json'), 'w') as fh:
            json.dump(lock, fh)
        self.session_record('owner', 'local_owner', repo, 'sup')

    def test_empty_queue_prints_nothing(self):
        r = self.hook(self.mkdir('p'))
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertEqual([l[2] for l in self.log_lines()], ['none'])

    def test_open_items_are_listed(self):
        repo = self.make_repo('repo')
        qid = self.add(repo)
        answered = self.add(repo, 'ya contestada')
        self.run_cli('answer', answered, '--text', 'ok')
        r = self.hook(repo)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'UserPromptSubmit')
        ctx = out['additionalContext']
        for needle in ('1 decisión', 'repo', qid, '¿Pago el plan?', 'no pagar', 'cuesta dinero', 'AskUserQuestion',
                       'dialogos-de-preguntas-legibles.md', 'ask-queue answer', f'ask-queue asked {qid} --to cli-human',
                       f'ask-queue:{qid}', 'metadata.source'):
            self.assertIn(needle, ctx)
        self.assertNotIn('ya contestada', ctx)
        self.assertIn('ESTA sesión', ctx)
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:1'])

    def test_worktree_cwd_sees_the_checkout_queue(self):
        repo = self.make_repo('repo')
        wt = os.path.join(self.tmp, 'repo-wt')
        subprocess.run(['git', 'worktree', 'add', '-q', '-b', 'b', wt], cwd=repo, check=True, capture_output=True)
        self.add(repo)
        self.assertIn('additionalContext', self.hook(wt).stdout)

    def test_other_project_is_not_mentioned(self):
        self.add(self.mkdir('a'))
        self.assertEqual(self.hook(self.mkdir('b')).stdout, '')

    def test_fails_open(self):
        for payload in ('not json', '[]', '{"cwd": 5}'):
            r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 0, payload)
        r = self.hook(self.tmp, ASK_QUEUE_BIN='/nonexistent/ask-queue')
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_non_human_prompts_inject_nothing(self):
        repo = self.make_repo('repo')
        self.add(repo)
        prompts = {
            'peer': 'Another Claude session sent a message: haz esto',
            'task': '<task-notification><task-id>x</task-id></task-notification>',
            'continuation': 'This session is being continued from a previous conversation that ran out of context.',
            'background': 'Background (from the session) ...',
            'padded': '\n  [cambio de cuenta] reanuda',
            'empty': '',
            'blank': ' \n\t ',
        }
        for name, prompt in prompts.items():
            r = self.hook(repo, self.human(repo, prompt))
            self.assertEqual((r.returncode, r.stdout), (0, ''), name)
        r = self.hook(repo, self.human(repo, 'hola', origin={'kind': 'peer'}))
        self.assertEqual(r.stdout, '')
        r = self.hook(repo, self.human(repo, 'hola', origin={'kind': 'task-notification'}))
        self.assertEqual(r.stdout, '')
        self.assertIn('additionalContext', self.hook(repo, self.human(repo, 'hola', origin={'kind': 'human'})).stdout)
        self.assertIn('additionalContext', self.hook(repo, self.human(repo, 'hola', origin={'kind': 'humanTurn'}),
                                                     ASK_QUEUE_SEEN_H='0').stdout)  # same session, window off
        decisions = [l[2] for l in self.log_lines()]
        self.assertEqual(decisions[:7], ['skip-not-human:prefix'] * 4 + ['skip-not-human:prefix', 'skip-not-human:empty',
                                                                       'skip-not-human:empty'])
        self.assertEqual(decisions[7:9], ['skip-not-human:origin'] * 2)
        self.assertEqual(decisions[9:], ['inject-own:1'] * 2)

    def seen_file(self, session='cli-human'):
        return os.path.join(self.state, 'prompt-hook-seen', session + '.json')

    def test_same_questions_are_not_reinjected_into_the_same_session(self):
        repo = self.make_repo('repo')
        qid = self.add(repo)
        self.assertIn(qid, self.hook(repo).stdout)
        for _ in range(2):
            r = self.hook(repo)
            self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:1', 'skip-seen:1', 'skip-seen:1'])
        with open(self.seen_file()) as fh:
            record = json.load(fh)
        self.assertEqual(record['ids'], [qid])
        self.assertEqual(len(record['hash']), 40)
        # another session of the same project is NOT told: the question is not its own
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-other')).stdout, '')

    def test_a_new_question_is_injected_with_all_the_unasked(self):
        repo = self.make_repo('repo')
        first = self.add(repo)
        self.hook(repo)
        second = self.add(repo, 'otra pregunta distinta')
        out = self.hook(repo).stdout
        self.assertIn(first, out)
        self.assertIn(second, out)
        self.assertEqual(self.hook(repo).stdout, '')

    def test_a_shrunken_set_is_not_repeated(self):
        repo = self.make_repo('repo')
        first = self.add(repo)
        second = self.add(repo, 'otra pregunta distinta')
        self.hook(repo)
        self.run_cli('answer', first, '--text', 'ok')
        self.assertEqual(self.hook(repo).stdout, '')
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:2', 'skip-seen:1'])

    def test_after_the_window_the_same_questions_are_injected_again(self):
        repo = self.make_repo('repo')
        qid = self.add(repo)
        self.hook(repo)
        with open(self.seen_file()) as fh:
            record = json.load(fh)
        record['ts'] = time.time() - 6 * 3600 - 60
        with open(self.seen_file(), 'w') as fh:
            json.dump(record, fh)
        self.assertIn(qid, self.hook(repo).stdout)
        self.assertEqual(self.hook(repo).stdout, '')
        self.assertIn(qid, self.hook(repo, ASK_QUEUE_SEEN_H='0').stdout)

    def test_non_injected_decisions_do_not_record_and_corrupt_state_is_ignored(self):
        repo = self.make_repo('repo')
        self.assertEqual(self.hook(repo).stdout, '')  # empty queue
        self.assertFalse(os.path.exists(self.seen_file()))
        qid = self.add(repo)
        os.makedirs(os.path.dirname(self.seen_file()))
        with open(self.seen_file(), 'w') as fh:
            fh.write('{broken')
        self.assertIn(qid, self.hook(repo).stdout)
        self.assertEqual(self.hook(repo).stdout, '')

    def test_old_seen_records_are_pruned(self):
        repo = self.make_repo('repo')
        self.add(repo)
        os.makedirs(os.path.dirname(self.seen_file()))
        stale = self.seen_file('cli-ancient')
        with open(stale, 'w') as fh:
            fh.write('{}')
        old = time.time() - 8 * 86400
        os.utime(stale, (old, old))
        self.hook(repo)
        self.assertFalse(os.path.exists(stale))

    def test_asked_items_are_not_listed_again(self):
        repo = self.make_repo('repo')
        qid = self.add(repo)
        other = self.add(repo, 'otra pregunta')
        self.run_cli('asked', qid, '--to', 'local_x')
        ctx = json.loads(self.hook(repo).stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn(other, ctx)
        self.assertNotIn(qid, ctx)
        self.run_cli('asked', other, '--to', 'local_x')
        self.assertEqual(self.hook(repo).stdout, '')
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:1', 'none'])

    def test_asked_long_ago_is_listed_again(self):
        repo = self.make_repo('repo')
        qid = self.add(repo)
        self.run_cli('asked', qid, '--to', 'local_x')
        self.assertEqual(self.hook(repo).stdout, '')
        self.assertIn(qid, self.hook(repo, ASK_QUEUE_REASK_H='0').stdout)

    def test_owner_and_supervised_sessions_get_nothing(self):
        repo = self.make_repo('repo')
        self.add(repo)
        self.supervise(repo, mailbox='local_mb')
        self.session_record('worker', 'local_worker', repo)
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-owner')).stdout, '')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-worker')).stdout, '')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-unknown')).stdout, '')
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-owner', 'skip-supervised', 'skip-supervised'])

    def test_supervised_with_recorded_mailbox_gets_nothing(self):
        repo = self.make_repo('repo')
        self.add(repo)
        self.supervise(repo, mailbox='local_mb')
        self.session_record('worker', 'local_worker', repo)
        r = self.hook(repo, self.human(repo, session='cli-worker'))
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-supervised'])

    def test_supervised_without_mailbox_gets_nothing_either(self):
        repo = self.make_repo('repo')
        self.add(repo)
        self.add(repo, 'una nueva')
        self.supervise(repo, state='paused')
        self.session_record('worker', 'local_worker', repo)
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-worker')).stdout, '')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-unknown')).stdout, '')
        self.assertEqual(self.hook(repo, self.human(repo, 'Another Claude session sent a message: x', session='cli-worker')).stdout, '')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-owner')).stdout, '')
        self.assertEqual([l[2] for l in self.log_lines()],
                         ['skip-supervised', 'skip-supervised', 'skip-not-human:prefix', 'skip-owner'])

    def test_mailbox_gets_nothing_while_the_lock_is_alive(self):
        repo = self.make_repo('repo')
        self.add(repo)
        self.add(repo, 'una nueva')
        self.supervise(repo, mailbox='local_mb')
        self.session_record('mb', 'local_mb', repo, 'Preguntas de la supervisión')
        r = self.hook(repo, self.human(repo, session='cli-mb'))
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-mailbox'])

    def test_inject_free_still_injects_once_the_lock_is_gone(self):
        repo = self.make_repo('repo')
        qid = self.add(repo, session='cli-worker')
        self.supervise(repo, mailbox='local_mb')
        self.session_record('worker', 'local_worker', repo)
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-worker')).stdout, '')
        os.remove(os.path.join(self.lock_home, 'locks', os.listdir(os.path.join(self.lock_home, 'locks'))[0]))
        ctx = json.loads(self.hook(repo, self.human(repo, session='cli-worker')).stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn(qid, ctx)
        self.assertNotIn('buzón', ctx)
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-supervised', 'inject-own:1'])

    def test_stale_lock_means_free(self):
        repo = self.make_repo('repo')
        qid = self.add(repo, session='cli-owner')
        self.supervise(repo, ago=5000)
        self.assertIn(qid, self.hook(repo, self.human(repo, session='cli-owner')).stdout)
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:1'])

    def test_log_line_has_no_prompt_text(self):
        repo = self.make_repo('repo')
        self.add(repo)
        secret = 'texto-privado-del-desarrollador'
        self.hook(repo, self.human(repo, secret, session='abcdefgh-1234'))
        self.hook(repo, self.human(repo, '<task-notification>' + secret, session='abcdefgh-1234'))
        with open(os.path.join(self.state, 'prompt-hook.log')) as fh:
            raw = fh.read()
        self.assertNotIn(secret, raw)
        rows = self.log_lines()
        self.assertEqual([len(r) for r in rows], [3, 3])
        self.assertTrue(all(r[1] == 'abcdefgh' for r in rows))
        datetime.fromisoformat(rows[0][0])

    def test_unloadable_supervisor_lock_falls_back_to_free(self):
        repo = self.make_repo('repo')
        qid = self.add(repo)
        r = self.hook(repo, SUPERVISOR_LOCK_BIN='/nonexistent/supervisor-lock')
        self.assertIn(qid, r.stdout)
        r = self.hook(repo, self.human(repo, 'This session is being continued from a previous conversation, summary follows'), SUPERVISOR_LOCK_BIN='/nonexistent/supervisor-lock')
        self.assertEqual(r.stdout, '')


    # ---- each question only in the session that queued it, or in the project's questions session ----

    def test_another_sessions_items_are_not_injected(self):
        repo = self.make_repo('repo')
        self.add(repo, session='cli-a')
        r = self.hook(repo, self.human(repo, session='cli-b'))
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertFalse(os.path.exists(self.seen_file('cli-b')))
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-foreign:1'])

    def test_only_the_own_items_are_injected(self):
        repo = self.make_repo('repo')
        own = self.add(repo, 'la mía')
        other = self.add(repo, 'la de otra sesión', session='cli-a')
        ctx = json.loads(self.hook(repo).stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn(own, ctx)
        self.assertNotIn(other, ctx)
        self.assertNotIn('la de otra sesión', ctx)
        self.assertNotIn('--unasked', ctx)  # a feature session is not pointed at the whole queue
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:1'])

    def test_items_without_origin_are_not_injected_into_a_feature_session(self):
        repo = self.make_repo('repo')
        env = dict(self.env)
        env.pop('CLAUDE_CODE_SESSION_ID')
        r = subprocess.run([sys.executable, SCRIPT, 'add', '--project', repo, '--question', 'huérfana', '--default', 'd',
                            '--why', 'w', '--blocks', 'b'], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hook(repo).stdout, '')
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-foreign:1'])

    def test_a_subagent_or_a_new_cli_id_of_the_same_app_session_is_the_owner(self):
        repo = self.make_repo('repo')
        qid = self.add(repo, session='local_worker')  # queued with the app id
        self.session_record('worker', 'local_worker', repo)  # the CLI session cli-worker is local_worker
        self.assertIn(qid, self.hook(repo, self.human(repo, session='cli-worker')).stdout)
        self.assertEqual(self.run_cli('answer', qid, '--text', 'ok').returncode, 0)
        # the CLI id changed (a fork, a resume) but the app record still says local_worker
        qid2 = self.add(repo, 'otra', session='cli-old')
        self.app_record('local_worker', 'cli-new', repo, 'trabajo')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-new')).stdout, '')  # cli-old item: not its own
        env_item = subprocess.run([sys.executable, SCRIPT, 'add', '--project', repo, '--question', 'por env',
                                   '--default', 'd', '--why', 'w', '--blocks', 'b'], capture_output=True, text=True,
                                  env=dict(self.env, CLAUDE_CODE_SESSION_ID='cli-old2',
                                           CLAUDE_CODE_HOST_SESSION_ID='local_worker')).stdout.strip()
        out = self.hook(repo, self.human(repo, session='cli-new')).stdout
        self.assertIn(env_item, out)
        self.assertNotIn(qid2, out)
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:1', 'skip-foreign:1', 'inject-own:1'])

    def test_questions_session_gets_every_unasked_item(self):
        repo = self.make_repo('repo')
        a = self.add(repo, 'de la sesión a', session='cli-a')
        b = self.add(repo, 'de la sesión b', session='local_b')
        self.app_record('local_mb', 'cli-mb', repo, 'Preguntas de la supervisión de repo')
        ctx = json.loads(self.hook(repo, self.human(repo, session='cli-mb')).stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn(a, ctx)
        self.assertIn(b, ctx)
        self.assertIn('sesión de preguntas', ctx)
        self.assertIn('--unasked', ctx)
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-questions:2'])

    def test_questions_session_is_found_with_another_projects_lock_alive(self):
        repo = self.make_repo('repo')
        other = self.make_repo('otro')
        qid = self.add(repo, session='cli-a')
        self.supervise(other, mailbox='local_omb')
        self.app_record('local_mb', 'cli-mb', repo, 'Preguntas de la supervisión de repo')
        self.assertIn(qid, self.hook(repo, self.human(repo, session='cli-mb')).stdout)
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-questions:1'])

    def test_archived_or_other_projects_questions_session_gets_only_its_own(self):
        repo = self.make_repo('repo')
        self.add(repo, session='cli-a')
        self.app_record('local_old', 'cli-old', repo, 'Preguntas de la supervisión de repo', archived=True)
        self.app_record('local_z', 'cli-z', repo, 'Preguntas de la supervisión de zeta')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-old')).stdout, '')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-z')).stdout, '')
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-foreign:1', 'skip-foreign:1'])

    def test_questions_session_gets_nothing_while_supervised(self):
        repo = self.make_repo('repo')
        self.add(repo, session='cli-a')
        self.supervise(repo, mailbox='local_mb')
        self.app_record('local_mb', 'cli-mb', repo, 'Preguntas de la supervisión de repo')
        self.assertEqual(self.hook(repo, self.human(repo, session='cli-mb')).stdout, '')
        self.assertEqual([l[2] for l in self.log_lines()], ['skip-mailbox'])

    def test_without_supervisor_lock_module_only_the_cli_id_matches(self):
        repo = self.make_repo('repo')
        own = self.add(repo)
        self.add(repo, 'de otra', session='cli-a')
        self.app_record('local_mb', 'cli-human', repo, 'Preguntas de la supervisión de repo')
        out = self.hook(repo, SUPERVISOR_LOCK_BIN='/nonexistent/supervisor-lock').stdout
        self.assertIn(own, out)
        self.assertNotIn('de otra', out)
        self.assertEqual([l[2] for l in self.log_lines()], ['inject-own:1'])


class OriginRecordTest(Base):
    """`add` records the origin session (it read the never-set CLAUDE_SESSION_ID before)."""

    def item(self, qid):
        (found,) = [i for i in self.listing() if i['id'] == qid]
        return found

    def test_origin_comes_from_the_claude_code_env(self):
        proj = self.mkdir('p')
        self.env.update(CLAUDE_CODE_SESSION_ID='cli-1', CLAUDE_CODE_HOST_SESSION_ID='local_1')
        item = self.item(self.add(proj))
        self.assertEqual((item['session'], item['host_session']), ('cli-1', 'local_1'))

    def test_old_env_name_is_a_fallback_and_nothing_means_empty(self):
        proj = self.mkdir('p')
        item = self.item(self.add(proj))
        self.assertEqual((item['session'], item['host_session']), ('', ''))
        self.env['CLAUDE_SESSION_ID'] = 'cli-legacy'
        item = self.item(self.add(proj, 'otra'))
        self.assertEqual(item['session'], 'cli-legacy')

    def test_explicit_session_wins(self):
        proj = self.mkdir('p')
        self.env.update(CLAUDE_CODE_SESSION_ID='cli-1', CLAUDE_CODE_HOST_SESSION_ID='local_1')
        item = self.item(self.add(proj, 'a', session='local_9'))
        self.assertEqual((item['session'], item['host_session']), ('', 'local_9'))
        item = self.item(self.add(proj, 'b', session='local_1'))
        self.assertEqual((item['session'], item['host_session']), ('cli-1', 'local_1'))
        item = self.item(self.add(proj, 'c', session='cli-9'))
        self.assertEqual((item['session'], item['host_session']), ('cli-9', ''))

    def test_an_item_without_origin_takes_the_session_that_adds_it_again(self):
        proj = self.mkdir('p')
        qid = self.add(proj, key='k')
        self.assertEqual(self.item(qid)['session'], '')
        self.env.update(CLAUDE_CODE_SESSION_ID='cli-1', CLAUDE_CODE_HOST_SESSION_ID='local_1')
        self.assertEqual(self.add(proj, key='k'), qid)
        self.assertEqual((self.item(qid)['session'], self.item(qid)['host_session']), ('cli-1', 'local_1'))
        self.env.update(CLAUDE_CODE_SESSION_ID='cli-2', CLAUDE_CODE_HOST_SESSION_ID='local_2')
        self.add(proj, key='k')
        self.assertEqual(self.item(qid)['session'], 'cli-1')  # an origin is never overwritten

    def test_answer_records_who_answered(self):
        proj = self.mkdir('p')
        qid = self.add(proj)
        self.env.update(CLAUDE_CODE_SESSION_ID='cli-1', CLAUDE_CODE_HOST_SESSION_ID='local_1')
        self.assertEqual(self.run_cli('answer', qid, '--text', 'sí').returncode, 0)
        self.assertEqual(self.item(qid)['answered_by'], 'local_1')


class SupervisedProjectRootTest(Base):
    """A repo nested in a supervised workspace queues under the workspace."""

    def root_of(self, directory):
        r = self.run_cli('list', '--project', directory, '--json')
        self.assertEqual(r.returncode, 0, r.stderr)
        qid = self.add(directory)
        (item,) = [i for i in self.listing() if i['id'] == qid]
        return item['project']

    def workspace(self):
        ws = self.mkdir('team space - main')
        os.makedirs(os.path.join(ws, 'sub'))
        repo = os.path.join(ws, 'final-project')
        subprocess.run(['git', 'init', '-q', repo], check=True)
        return os.path.realpath(ws), os.path.realpath(repo)

    def test_nested_repo_uses_workspace_lock_checkout(self):
        ws, repo = self.workspace()
        self.write_lock('ws-1', ws)
        self.assertEqual(self.root_of(repo), ws)
        self.assertEqual(self.root_of(os.path.join(repo, '..', 'sub')), ws)

    def test_without_lock_nested_repo_keeps_its_own_root(self):
        ws, repo = self.workspace()
        self.assertEqual(self.root_of(repo), repo)

    def test_released_lock_is_ignored(self):
        ws, repo = self.workspace()
        self.write_lock('ws-1', ws, released='2000-01-09T10:00:00+01:00')
        self.assertEqual(self.root_of(repo), repo)

    def test_quiet_lock_still_names_the_project(self):
        ws, repo = self.workspace()
        old = (datetime.now(timezone.utc).astimezone() - timedelta(hours=30)).isoformat(timespec='seconds')
        self.write_lock('ws-1', ws, heartbeat=old)
        self.assertEqual(self.root_of(repo), ws)

    def test_git_lock_matches_its_checkout_and_worktree_not_nested_repo(self):
        repo = self.make_repo('proj')
        repo = os.path.realpath(repo)
        self.write_lock('git-1', repo, common_dir=os.path.join(repo, '.git'))
        wt = os.path.join(self.tmp, 'wt')
        subprocess.run(['git', '-C', repo, 'worktree', 'add', '-q', '-b', 'b', wt], check=True, capture_output=True)
        self.assertEqual(self.root_of(wt), repo)
        nested = os.path.join(repo, 'inner')
        subprocess.run(['git', 'init', '-q', nested], check=True)
        self.assertEqual(self.root_of(nested), os.path.realpath(nested))

    def test_deepest_workspace_lock_wins_and_corrupt_lock_files_are_skipped(self):
        ws, repo = self.workspace()
        inner_ws = os.path.join(ws, 'sub')
        self.write_lock('ws-1', ws)
        self.write_lock('ws-2', inner_ws)
        os.makedirs(os.path.join(self.lock_home, 'locks'), exist_ok=True)
        with open(os.path.join(self.lock_home, 'locks', 'bad.json'), 'w') as fh:
            fh.write('{not json')
        self.assertEqual(self.root_of(inner_ws), inner_ws)
        self.assertEqual(self.root_of(repo), ws)



def hours_ago(hours):
    return (datetime.now(timezone.utc).astimezone() - timedelta(hours=hours)).isoformat(timespec='seconds')


class BlockingDueTest(Base):
    """`list --due` and the partial batch window: open, not radical, with an order or blocking real work for
    ask_due_after_h hours; one batch per project per ask_partial_batch_window_h unless a due item carries an order."""

    def queue_file(self):
        (name,) = [n for n in os.listdir(self.state) if n.endswith('.jsonl')]
        return os.path.join(self.state, name)

    def edit(self, qid, **fields):
        path = self.queue_file()
        with open(path) as fh:
            rows = [json.loads(line) for line in fh]
        for row in rows:
            if row['id'] == qid:
                row.update(fields)
        with open(path, 'w') as fh:
            fh.writelines(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)

    def due(self, *args):
        r = self.run_cli('list', '--due', '--json', *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {i['id']: i for i in json.loads(r.stdout)}

    def due_text(self, *args):
        r = self.run_cli('list', '--due', *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def config(self, **values):
        with open(os.path.join(self.env['CLAUDE_TOOLKIT_CONFIG_DIR'], 'supervision.json'), 'w') as fh:
            json.dump(values, fh)

    def test_an_order_makes_an_item_due_at_once(self):
        proj = self.mkdir('p')
        qid = self.add(proj, blocks='la candidatura', order='hazlo primero')
        plain = self.add(proj, 'otra')
        got = self.due('--project', proj)
        self.assertEqual(set(got), {qid})
        self.assertEqual((got[qid]['due_reason'], got[qid]['order'], got[qid]['age_h']), ('order', 'hazlo primero', 0.0))
        self.assertNotIn(plain, got)

    def test_real_work_blocked_longer_than_the_threshold_is_due_and_a_younger_item_is_not(self):
        proj = self.mkdir('p')
        old, young = self.add(proj, 'vieja', blocks='el envío'), self.add(proj, 'joven', blocks='el envío')
        self.edit(old, ts=hours_ago(25))
        self.edit(young, ts=hours_ago(23))
        got = self.due('--project', proj)
        self.assertEqual(set(got), {old})
        self.assertEqual(got[old]['due_reason'], 'blocks')
        self.assertGreaterEqual(got[old]['age_h'], 25)

    def test_an_item_that_blocks_nothing_is_never_due(self):
        proj = self.mkdir('p')
        ids = [self.add(proj, f'q{n}', blocks=text)
               for n, text in enumerate(('Nada', 'nada: solo su archivado', 'Ninguno', 'NINGUNA', 'ningún trabajo',
                                         'Nothing', 'none', '', '  ...  '))]
        for qid in ids:
            self.edit(qid, ts=hours_ago(100))
        self.assertEqual(self.due('--project', proj), {})
        real = self.add(proj, 'real', blocks='nadar en la piscina')  # only the whole first word counts
        self.edit(real, ts=hours_ago(100))
        self.assertEqual(set(self.due('--project', proj)), {real})

    def test_asked_answered_closed_and_radical_items_are_not_due(self):
        proj = self.mkdir('p')
        asked, answered, closed = (self.add(proj, t, order='ya') for t in ('a', 'b', 'c'))
        radical = self.run_cli('add', '--project', proj, '--question', 'r', '--default', 'd', '--why', 'w',
                               '--blocks', 'todo', '--radical', '--order', 'ya').stdout.strip()
        self.run_cli('asked', asked)
        self.run_cli('answer', answered, '--text', 'sí')
        self.run_cli('close', closed)
        for qid in (asked, answered, closed, radical):
            self.edit(qid, ts=hours_ago(100))
        self.assertEqual(self.due('--project', proj), {})

    def test_items_without_the_new_field_follow_the_age_rule_and_keep_working(self):
        proj = self.mkdir('p')
        self.add(proj, 'nueva')
        old = {'id': 'q-old', 'ts': '2000-01-01T10:00:00+01:00', 'project': os.path.realpath(proj), 'session': '',
               'question': 'Antigua', 'default': 'd', 'why': 'w', 'blocks': 'el despliegue', 'status': 'open',
               'answer': None}
        with open(self.queue_file(), 'a') as fh:
            fh.write(json.dumps(old) + '\n')
        self.assertEqual(set(self.due('--project', proj)), {'q-old'})
        self.assertEqual(self.run_cli('pending', 'q-old').stdout.split(), ['q-old', 'open'])

    def test_a_blank_order_is_refused_and_writes_nothing(self):
        proj = self.mkdir('p')
        r = self.run_cli('add', '--project', proj, '--question', 'q', '--default', 'd', '--why', 'w', '--blocks', 'b',
                         '--order', '   ')
        self.assertEqual(r.returncode, 2)
        self.assertIn('--order', r.stderr)
        self.assertEqual(self.listing('--project', proj), [])

    def test_a_later_plain_add_keeps_the_order_and_a_new_order_replaces_it(self):
        proj = self.mkdir('p')
        qid = self.add(proj, order='hazlo ya')
        self.assertEqual(self.add(proj), qid)
        (item,) = self.listing('--project', proj)
        self.assertEqual(item['order'], 'hazlo ya')
        self.assertEqual(self.add(proj, order='  antes que nada  '), qid)
        (item,) = self.listing('--project', proj)
        self.assertEqual(item['order'], 'antes que nada')

    def test_the_window_counts_from_the_last_non_radical_item_asked(self):
        proj = self.mkdir('p')
        name = os.path.basename(proj)
        first, second, presented = (self.add(proj, t, blocks='la tarea') for t in ('uno', 'dos', 'tres'))
        for qid in (first, second, presented):
            self.edit(qid, ts=hours_ago(30))
        self.run_cli('asked', presented)
        self.edit(presented, asked_ts=hours_ago(13))
        out = self.due_text('--project', proj)
        self.assertIn(f'partial batch {name}: due now (2)', out)
        self.assertIn(first, out)
        self.edit(presented, asked_ts=hours_ago(2))
        out = self.due_text('--project', proj)
        self.assertIn(first, out)  # still listed: only the batch waits
        self.assertRegex(out, rf'partial batch {name}: window closed until \d{{4}}-\d\d-\d\dT.* \(last asked ')
        self.assertNotIn('due now', out)

    def test_a_due_order_opens_a_closed_window(self):
        proj = self.mkdir('p')
        name = os.path.basename(proj)
        presented = self.add(proj, 'presentada')
        self.run_cli('asked', presented)
        old = self.add(proj, 'vieja', blocks='la tarea')
        self.edit(old, ts=hours_ago(30))
        self.assertIn('window closed until', self.due_text('--project', proj))
        self.add(proj, 'ordenada', order='primero esto')
        self.assertIn(f'partial batch {name}: due now (2)', self.due_text('--project', proj))

    def test_a_radical_asked_recently_does_not_close_the_window(self):
        proj = self.mkdir('p')
        name = os.path.basename(proj)
        radical = self.run_cli('add', '--project', proj, '--question', 'r', '--default', 'd', '--why', 'w',
                               '--blocks', 'todo', '--radical').stdout.strip()
        self.run_cli('asked', radical)
        old = self.add(proj, 'vieja', blocks='la tarea')
        self.edit(old, ts=hours_ago(30))
        self.assertIn(f'partial batch {name}: due now (1)', self.due_text('--project', proj))

    def test_thresholds_come_from_the_supervision_piece_and_a_wrong_value_keeps_the_default(self):
        proj = self.mkdir('p')
        qid = self.add(proj, blocks='la tarea')
        self.edit(qid, ts=hours_ago(3))
        self.assertEqual(self.due('--project', proj), {})
        self.config(ask_due_after_h=2)
        self.assertEqual(set(self.due('--project', proj)), {qid})
        for bad in ('soon', -1, True, None, [2]):
            with self.subTest(bad=bad):
                self.config(ask_due_after_h=bad)
                self.assertEqual(self.due('--project', proj), {})
        self.config(ask_due_after_h=0, ask_partial_batch_window_h=0)
        presented = self.add(proj, 'presentada')
        self.run_cli('asked', presented)
        self.assertIn('due now', self.due_text('--project', proj))

    def test_the_shipped_config_piece_carries_the_defaults(self):
        with open(REPO_ROOT / 'global/config/supervision.json', encoding='utf-8') as fh:
            shipped = json.load(fh)
        self.assertEqual((shipped['ask_due_after_h'], shipped['ask_partial_batch_window_h']), (24, 12))

    def test_without_due_items_it_says_so_and_lists_every_project_otherwise(self):
        self.assertEqual(self.due_text().strip(), '(no items)')
        a, b = self.mkdir('a'), self.mkdir('b')
        qa, qb = self.add(a, order='x'), self.add(b, order='y')
        self.add(b, 'sin orden')
        self.assertEqual(set(self.due()), {qa, qb})
        out = self.due_text()
        self.assertIn('partial batch a: due now (1)', out)
        self.assertIn('partial batch b: due now (1)', out)

    def test_the_prompt_hook_injects_an_ordered_item_as_any_other_without_a_supervisor(self):
        repo = self.make_repo('repo')
        self.env.update(CLAUDE_CODE_SESSION_ID='cli-human', SUPERVISOR_LOCK_BIN=LOCK_SCRIPT)
        qid = self.add(repo, order='hazlo ya')
        payload = {'hook_event_name': 'UserPromptSubmit', 'cwd': repo, 'prompt': 'hola', 'session_id': 'cli-human'}
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                           env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(qid, json.loads(r.stdout)['hookSpecificOutput']['additionalContext'])

if __name__ == '__main__':
    unittest.main()
