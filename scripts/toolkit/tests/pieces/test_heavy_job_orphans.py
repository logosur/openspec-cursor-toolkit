"""Tests for the job mark, the end-of-job sweep and the orphans of global/scripts/heavy-job.

Real processes in a temporary HEAVY_JOB_DIR: every process a test starts carries a marker in its argv (`exec -a`)
and is killed by PID in tearDown. The machine's own state dir and processes are never touched; the orphan scan only
looks at processes whose HEAVY_JOB_STATE is the test's directory, and the previous-version rule is only switched on
with HEAVY_JOB_LEGACY_ORPHANS=1 for processes the test starts itself.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = str(REPO_ROOT / 'global/scripts/heavy-job')


def marked_pids(marker):
    """Pids of this uid whose argv[0] is `marker`."""
    pids = []
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        try:
            with open(f'/proc/{name}/cmdline', 'rb') as handle:
                argv0 = handle.read().split(b'\0')[0].decode('utf-8', 'replace')
        except OSError:
            continue
        if argv0 == marker:
            pids.append(int(name))
    return pids


def environ(pid):
    with open(f'/proc/{pid}/environ', 'rb') as handle:
        items = handle.read().split(b'\0')
    return dict(i.decode().split('=', 1) for i in items if b'=' in i)


def wait_until(predicate, timeout=20, step=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class OrphanTestCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='heavy-job-orphans-home-')
        self.dir = tempfile.mkdtemp(prefix='heavy-job-orphans-')
        self.marker = f'hjtest-{uuid.uuid4().hex[:10]}'
        self.env = dict(os.environ, HOME=self.home, CLAUDE_TOOLKIT_CONFIG_DIR=os.path.join(self.home, 'config'),
                        HEAVY_JOB_DIR=self.dir, HEAVY_JOB_SLOTS='1', HEAVY_JOB_LIGHT_SLOTS='0', HEAVY_JOB_SCAN='0',
                        HEAVY_JOB_POLL='0.2', HEAVY_JOB_MIN_AVAIL_GIB='0', HEAVY_JOB_SETTLE='0',
                        HEAVY_JOB_REAP_GRACE='2', HEAVY_JOB_DETACHED_DIR=os.path.join(self.home, 'detached'),
                        HEAVY_JOB_DETACH_LAUNCHER='setsid', HEAVY_JOB_INTERVENTIONS_LOG=os.path.join(self.home, 'i.log'),
                        PROJECT_PAUSE_BIN=os.path.join(self.home, 'none'),
                        CLOUD_TESTS_BIN=os.path.join(self.home, 'none'))
        for key in ('HEAVY_JOB_SLOT', 'HEAVY_JOB_LIGHT_SLOT', 'HEAVY_JOB_ID', 'HEAVY_JOB_OWNER', 'HEAVY_JOB_STATE',
                    'HEAVY_JOB_LEGACY_ORPHANS'):
            self.env.pop(key, None)
        self.procs = []

    def tearDown(self):
        for pid in marked_pids(self.marker):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        for proc in self.procs:
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    stream.close()
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def hj(self, *args, env=None, timeout=60):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env=env or self.env, timeout=timeout)

    def spawn(self, *args, env=None):
        proc = subprocess.Popen([sys.executable, SCRIPT, *args], env=env or self.env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        self.procs.append(proc)
        return proc

    def scan_orphans(self, env=None):
        """The orphans `scan` lists among this test's own processes (the machine's are none of its business)."""
        out = self.hj('scan', '--json', env=dict(env or self.env, HEAVY_JOB_SCAN='1'))
        self.assertEqual(out.returncode, 0, out.stderr)
        mine = set(marked_pids(self.marker))
        return [item for item in json.loads(out.stdout) if item.get('job_orphan') and set(item['pids']) & mine]

    def server_cmd(self, program='sleep 300'):
        """A child that starts a detached server which closes its fds (Python's default), then lives `life` s."""
        return [sys.executable, '-c',
                'import subprocess, sys, time\n'
                f'subprocess.Popen(["bash", "-c", "exec -a {self.marker} {program}"], start_new_session=True)\n'
                'time.sleep(float(sys.argv[1]))\n']


class MarkTest(OrphanTestCase):
    def test_mark_in_the_environment_and_the_slot_json(self):
        out = self.hj('run', '--label', 'mark', '--', 'bash', '-c',
                      f'env | grep ^HEAVY_JOB_; sleep 1; cat {self.dir}/slot-0.json')
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = dict(line.split('=', 1) for line in out.stdout.splitlines() if line.startswith('HEAVY_JOB_'))
        self.assertTrue(lines.get('HEAVY_JOB_ID'))
        self.assertRegex(lines.get('HEAVY_JOB_OWNER', ''), r'^\d+:\d+$')
        self.assertEqual(lines.get('HEAVY_JOB_STATE'), os.path.realpath(self.dir))
        info = json.loads(out.stdout[out.stdout.index('{'):])
        self.assertEqual(info.get('job_id'), lines['HEAVY_JOB_ID'])


class SweepTest(OrphanTestCase):
    def test_background_child_is_stopped_when_the_job_ends(self):
        out = self.hj('run', '--label', 'sweep', '--', 'bash', '-c', f'(exec -a {self.marker} sleep 300) & exit 0')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(wait_until(lambda: not marked_pids(self.marker), timeout=5), True)
        self.assertIn(self.marker, out.stderr)
        self.assertIn('parados', out.stderr)

    def test_server_that_closed_its_fds_is_stopped_too(self):
        out = self.hj('run', '--label', 'server', '--', *self.server_cmd(), '0.5')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(wait_until(lambda: not marked_pids(self.marker), timeout=5))

    def test_a_term_that_ignores_sigterm_gets_sigkill(self):
        out = self.hj('run', '--label', 'stubborn', '--', 'bash', '-c',
                      f"(trap '' TERM; exec -a {self.marker} sleep 300) & exit 0")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(wait_until(lambda: not marked_pids(self.marker), timeout=5))

    def test_detached_job_stopped_leaves_nothing(self):
        out = self.hj('run', '--detach', '--label', 'det', '--', 'bash', '-c',
                      f'(exec -a {self.marker} sleep 300) & sleep 300')
        self.assertEqual(out.returncode, 0, out.stderr)
        job_id = out.stdout.split()[0]
        self.assertTrue(wait_until(lambda: marked_pids(self.marker), timeout=20), 'the job never started')
        self.assertEqual(self.hj('stop', job_id).returncode, 0)
        waited = self.hj('wait', job_id, '--timeout', '30')
        self.assertNotEqual(waited.returncode, 124, waited.stderr)
        self.assertTrue(wait_until(lambda: not marked_pids(self.marker), timeout=5))


class OrphanScanTest(OrphanTestCase):
    def kill_wrapper_keep_child(self, life, program='sleep 300'):
        """Start a job, SIGKILL its wrapper (so it cannot sweep), and let the child end by itself after `life` s."""
        wrapper = self.spawn('run', '--label', 'orphaned', '--', *self.server_cmd(program), str(life))
        self.assertTrue(wait_until(lambda: marked_pids(self.marker), timeout=20), 'the server never started')
        os.kill(wrapper.pid, signal.SIGKILL)
        wrapper.wait()
        return marked_pids(self.marker)

    def test_live_job_has_no_orphans(self):
        proc = self.spawn('run', '--label', 'live', '--', *self.server_cmd(), '30')
        self.assertTrue(wait_until(lambda: marked_pids(self.marker), timeout=20))
        self.assertEqual(self.scan_orphans(), [])
        proc.terminate()
        proc.wait(timeout=30)
        self.assertTrue(wait_until(lambda: not marked_pids(self.marker), timeout=5))

    def test_child_still_holding_the_slot_keeps_the_job_alive(self):
        self.kill_wrapper_keep_child(30)
        # the wrapper is dead, but its child inherited the slot lock: the job is alive, its server is not an orphan
        self.assertEqual(self.scan_orphans(), [])

    def test_server_of_a_finished_job_is_an_orphan(self):
        servers = self.kill_wrapper_keep_child(0.5)
        found = wait_until(lambda: self.scan_orphans(), timeout=10)
        self.assertEqual(len(found), 1, found)
        item = found[0]
        self.assertEqual(item['pids'], servers)
        self.assertFalse(item['counted'])           # a sleeping server is small and idle: listed only
        text = self.hj('scan', env=dict(self.env, HEAVY_JOB_SCAN='1')).stdout
        self.assertIn('HUÉRFANO', text)
        self.assertIn(f'kill {servers[0]}', text)

    def test_busy_orphan_counts_in_admission(self):
        self.kill_wrapper_keep_child(0.5, program='python3 -c \\"while True: pass\\"')
        found = wait_until(lambda: [i for i in self.scan_orphans() if i['counted']], timeout=15)
        self.assertEqual(len(found), 1, self.scan_orphans())
        out = self.hj('status', '--json', env=dict(self.env, HEAVY_JOB_SCAN='1'))
        status = json.loads(out.stdout)
        self.assertTrue(any(u.get('job_orphan') == found[0]['job_orphan'] for u in status['unwrapped']))
        self.assertEqual(status['free_effective'], 0)

    def test_another_state_dir_does_not_see_it(self):
        self.kill_wrapper_keep_child(0.5)
        self.assertTrue(wait_until(lambda: self.scan_orphans(), timeout=10))
        other = tempfile.mkdtemp(prefix='heavy-job-orphans-other-')
        self.addCleanup(shutil.rmtree, other, True)
        self.assertEqual(self.scan_orphans(dict(self.env, HEAVY_JOB_DIR=other)), [])


class LegacyOrphanTest(OrphanTestCase):
    def legacy_process(self):
        env = dict(self.env, HEAVY_JOB_SLOT='0', HEAVY_JOB_STATE='', HEAVY_JOB_LABEL='old')
        env.pop('HEAVY_JOB_STATE')
        proc = subprocess.Popen(['bash', '-c', f'exec -a {self.marker} sleep 300'], env=env)
        self.procs.append(proc)
        self.assertTrue(wait_until(lambda: marked_pids(self.marker), timeout=5))
        return proc

    def test_slot_free_means_orphan(self):
        proc = self.legacy_process()
        found = self.scan_orphans(dict(self.env, HEAVY_JOB_LEGACY_ORPHANS='1'))
        self.assertEqual([i['pids'] for i in found], [[proc.pid]])

    def test_slot_held_since_before_the_process_is_not_an_orphan(self):
        holder = self.spawn('run', '--label', 'holder', '--', 'sleep', '60')
        self.assertTrue(wait_until(lambda: os.path.exists(os.path.join(self.dir, 'slot-0.json')), timeout=20))
        time.sleep(1.5)
        self.legacy_process()
        found = self.scan_orphans(dict(self.env, HEAVY_JOB_LEGACY_ORPHANS='1'))
        self.assertEqual(found, [])
        holder.terminate()

    def test_off_without_the_switch_in_a_test_state_dir(self):
        self.legacy_process()
        self.assertEqual(self.scan_orphans(), [])


if __name__ == '__main__':
    unittest.main()
