"""Synthetic homes for the tests and `self-test`: transcripts, subagents, app records, supervision files, git repos.

Everything is written under one temporary root that plays the role of HOME. The shapes written here are the ones the
collector expects (design: evidence map); they pin the format, since the real one is not documented.
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess

from . import config as C

_ids = itertools.count(1)


def iso(ts: float) -> str:
    return C.iso(ts)


class Transcript:
    def __init__(self, path: str, session: str, agent: str | None = None, cwd: str | None = None):
        self.path, self.session, self.agent, self.cwd = path, session, agent, cwd
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def raw(self, line: str) -> 'Transcript':
        with open(self.path, 'a', encoding='utf-8') as fh:
            fh.write(line.rstrip('\n') + '\n')
        return self

    def _line(self, obj: dict) -> 'Transcript':
        obj.setdefault('sessionId', self.session)
        if self.cwd:
            obj.setdefault('cwd', self.cwd)
        return self.raw(json.dumps(obj))

    def user(self, ts, text='hello', origin=None, uuid=None, meta=False, compact=False) -> 'Transcript':
        obj = {'type': 'user', 'uuid': uuid or f'u{next(_ids)}', 'timestamp': iso(ts),
               'message': {'role': 'user', 'content': text}}
        if origin:
            obj['origin'] = {'kind': origin}
        if meta:
            obj['isMeta'] = True
        if compact:
            obj['isCompactSummary'] = True
        return self._line(obj)

    def tool_result(self, ts) -> 'Transcript':
        return self._line({'type': 'user', 'uuid': f'u{next(_ids)}', 'timestamp': iso(ts),
                           'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'ok'}]}})

    def assistant(self, ts, model='model-small', msg_id=None, inp=10, cw5=0, cw1h=0, cr=0, out=20, text=None,
                  tools=(), iterations=None, usage=None, split=True) -> 'Transcript':
        if usage is None:
            usage = {'input_tokens': inp, 'cache_creation_input_tokens': cw5 + cw1h, 'cache_read_input_tokens': cr,
                     'output_tokens': out}
            if split:
                usage['cache_creation'] = {'ephemeral_5m_input_tokens': cw5, 'ephemeral_1h_input_tokens': cw1h}
            if iterations is not None:
                usage['iterations'] = iterations
        content = []
        if text is not None:
            content.append({'type': 'text', 'text': text})
        for name, args in tools:
            content.append({'type': 'tool_use', 'id': f't{next(_ids)}', 'name': name, 'input': args})
        return self._line({'type': 'assistant', 'uuid': f'a{next(_ids)}', 'timestamp': iso(ts),
                           'message': {'id': msg_id or f'msg_{next(_ids)}', 'model': model, 'role': 'assistant',
                                       'content': content, 'usage': usage}})

    def turn(self, ts, text='hello', origin=None, model='model-small', calls=1, out=20, end_text='done',
             ctx=0, cw=0) -> 'Transcript':
        """One turn: a user line and `calls` responses one second apart, the last one ending with `end_text`."""
        self.user(ts, text, origin=origin)
        for i in range(calls):
            self.assistant(ts + 1 + i, model=model, out=out, cr=max(0, ctx - cw - 10), cw5=cw,
                           text=end_text if i == calls - 1 else None)
        return self


class Home:
    def __init__(self, root: str):
        self.root = os.path.realpath(root)
        self.projects = os.path.join(self.root, '.claude', 'projects')
        self.app = os.path.join(self.root, '.config', 'Claude', 'claude-code-sessions')
        self.supervisor = os.path.join(self.root, '.claude', 'supervisor')
        self.state = os.path.join(self.root, '.claude', 'state', 'usage-watch')
        self.config_dir = os.path.join(self.root, '.claude', 'toolkit', 'config')
        self.queue = os.path.join(self.root, '.claude', 'state', 'question-queue')
        self.override = os.path.join(self.root, 'override')
        os.makedirs(self.projects, exist_ok=True)

    def env(self, now=None, base=None) -> dict:
        env = dict(base if base is not None else os.environ)
        for key in ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_HOST_SESSION_ID', 'USAGE_WATCH_NOW'):
            env.pop(key, None)
        env.update(HOME=self.root, CLAUDE_TOOLKIT_CONFIG_DIR=self.config_dir, SUPERVISOR_LOCK_HOME=self.supervisor,
                   ASK_QUEUE_DIR=self.queue, CLAUDE_TOOLKIT_OVERRIDE=self.override,
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        if now is not None:
            env['USAGE_WATCH_NOW'] = iso(now)
        return env

    def config(self, **values) -> str:
        os.makedirs(self.config_dir, exist_ok=True)
        path = os.path.join(self.config_dir, 'usage-watch.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(values, fh)
        return path

    def piece(self, name: str, values: dict) -> str:
        os.makedirs(self.config_dir, exist_ok=True)
        path = os.path.join(self.config_dir, f'{name}.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(values, fh)
        return path

    def transcript(self, session: str, slug='-work-proj', cwd=None) -> Transcript:
        return Transcript(os.path.join(self.projects, slug, f'{session}.jsonl'), session, cwd=cwd)

    def subagent(self, session: str, agent: str, slug='-work-proj', description='', first_prompt='go', ts=None,
                 model='model-small', calls=1) -> Transcript:
        folder = os.path.join(self.projects, slug, session, 'subagents')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f'{agent}.meta.json'), 'w', encoding='utf-8') as fh:
            json.dump({'description': description, 'agentType': 'general-purpose'}, fh)
        tr = Transcript(os.path.join(folder, f'{agent}.jsonl'), session, agent=agent)
        if ts is not None:
            tr.user(ts, first_prompt)
            for i in range(calls):
                tr.assistant(ts + 1 + i, model=model, text='sub done')
        return tr

    def app_record(self, app_id: str, cli_id: str, cwd: str, title='', scheduled=None, model=None) -> str:
        folder = os.path.join(self.app, 'acct', 'org')
        os.makedirs(folder, exist_ok=True)
        rec = {'sessionId': app_id, 'cliSessionId': cli_id, 'cwd': cwd, 'title': title}
        if scheduled:
            rec['scheduledTaskId'] = scheduled
        if model:
            rec['model'] = model
        path = os.path.join(folder, f'{app_id}.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh)
        return path

    def lock(self, key: str, checkout: str, session_id: str, mailbox=None, closer=None, released=False) -> str:
        folder = os.path.join(self.supervisor, 'locks')
        os.makedirs(folder, exist_ok=True)
        rec = {'key': key, 'checkout': checkout, 'session_id': session_id, 'state': 'running'}
        if mailbox:
            rec['mailbox'] = mailbox
        if closer:
            rec['closer'] = closer
        if released:
            rec['released'] = True
        path = os.path.join(folder, f'{key}.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh)
        return path

    def usage_role(self, session_id: str, cli_session_id=None, home_project=None) -> str:
        os.makedirs(self.supervisor, exist_ok=True)
        path = os.path.join(self.supervisor, 'usage-role.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'session_id': session_id, 'cli_session_id': cli_session_id, 'home_project': home_project}, fh)
        return path

    def git_repo(self, name: str) -> str:
        path = os.path.join(self.root, 'code', name)
        os.makedirs(path, exist_ok=True)
        env = self.env()
        subprocess.run(['git', 'init', '-q', path], check=True, env=env)
        subprocess.run(['git', '-C', path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q',
                        '--allow-empty', '-m', 'init'], check=True, env=env)
        return path

    def worktree(self, repo: str, name: str) -> str:
        path = os.path.join(self.root, 'trees', name)
        subprocess.run(['git', '-C', repo, 'worktree', 'add', '-q', '--detach', path], check=True, env=self.env())
        return path
