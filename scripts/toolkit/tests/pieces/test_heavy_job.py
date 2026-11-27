"""Tests for global/scripts/heavy-job (the machine-wide semaphore for heavy dev jobs).

Every slot test uses a temporary HEAVY_JOB_DIR and HEAVY_JOB_SLOTS=1, so the real /run/user/<uid>/heavy-job is
never touched. HEAVY_JOB_SCAN=0 keeps the real heavy jobs of the machine out of the slot arithmetic; only the
scan tests enable it.
"""
import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = str(REPO_ROOT / 'global/scripts/heavy-job')


def load_module():
    loader = importlib.machinery.SourceFileLoader('heavy_job', SCRIPT)
    spec = importlib.util.spec_from_loader('heavy_job', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


SANDBOX = tempfile.mkdtemp(prefix='heavy-job-home-')
SANDBOX_ENV = {'HOME': SANDBOX, 'CLAUDE_TOOLKIT_CONFIG_DIR': os.path.join(SANDBOX, 'config'),
               'HEAVY_JOB_INTERVENTIONS_LOG': os.path.join(SANDBOX, 'interventions.log'),
               'PROJECT_PAUSE_BIN': os.path.join(SANDBOX, 'none'), 'CLOUD_TESTS_BIN': os.path.join(SANDBOX, 'none')}
with mock.patch.dict(os.environ, SANDBOX_ENV):
    HJ = load_module()


def setUpModule():
    patcher = mock.patch.dict(os.environ, SANDBOX_ENV)
    patcher.start()
    unittest.addModuleCleanup(shutil.rmtree, SANDBOX, True)
    unittest.addModuleCleanup(patcher.stop)

DOCKER_QEMU = ['/usr/bin/qemu-system-x86_64', '-accel', 'kvm', '-cpu', 'host', '-machine', 'q35', '-m', '4096',
               '-kernel', '/opt/docker-desktop/linuxkit/kernel']
GRADLE_DAEMON = ['/usr/lib/jvm/java-17-openjdk-amd64/bin/java', '--add-opens=java.base/java.util=ALL-UNNAMED',
                 '-Xmx2048m', '-Dfile.encoding=UTF-8', '-cp', '/home/user/.gradle/wrapper/dists/gradle-8.10/lib/'
                 'gradle-launcher-8.10.jar', '-javaagent:/x/gradle-instrumentation-agent-8.10.jar',
                 'org.gradle.launcher.daemon.bootstrap.GradleDaemon', '8.10']
GRADLE_CLIENT = ['/usr/lib/jvm/java-17-openjdk-amd64/bin/java', '-Xmx64m', '-Xms64m',
                 '-Dorg.gradle.appname=gradlew', '-classpath', '/x/gradle/wrapper/gradle-wrapper.jar',
                 'org.gradle.wrapper.GradleWrapperMain', ':app:assembleDebug']
GRADLE_CLIENT_STOP = GRADLE_CLIENT[:-1] + ['--stop']
MAESTRO_JAVA = ['java', '-cp', '/home/user/.maestro/lib/*', 'maestro.cli.AppKt', 'test', 'flows/a.yaml']

# (command line, expected kind or None for light)
CLASSIFY_CASES = [
    # heavy
    ('cd /x && ./gradlew :app:assembleRelease -PreactNativeArchitectures=x86_64', 'build'),
    ('./gradlew test', 'build'),
    ('gradle build', 'build'),
    ('nohup ./gradlew assembleDebug > /tmp/log 2>&1 &', 'build'),
    ('npm ci', 'install'),
    ('npm ci 2>&1 | tail -5', 'install'),
    ('npm --prefix app ci', 'install'),
    ('npm install', 'install'),
    ('npm i', 'install'),
    ('pnpm install', 'install'),
    ('yarn install', 'install'),
    ('yarn', 'install'),
    ('sudo -u builder npm ci', 'install'),
    ('node /usr/lib/node_modules/npm/bin/npm-cli.js ci', 'install'),
    ('bash -c "npm ci && npm test"', 'install'),
    ('tools/worktree-slot.sh exec npm ci', 'install'),
    ('heavy-job run -- npm ci', 'install'),
    ('npm test', 'tests'),
    ('npm t', 'tests'),
    ('npm run test', 'tests'),
    ('npm run test:changed', 'tests'),
    ('npm run e2e', 'tests'),
    ('npx jest', 'tests'),
    ('npx vitest run', 'tests'),
    ('pytest', 'tests'),
    ('time pytest', 'tests'),
    ('python3 -m pytest', 'tests'),
    ('.venv/bin/python -m pytest -n auto', 'tests'),
    ('uv run pytest', 'tests'),
    ('phpunit', 'tests'),
    ('ddev exec vendor/bin/phpunit', 'tests'),
    ('docker compose exec web npm test', 'tests'),
    ('docker exec -it web vendor/bin/phpunit', 'tests'),
    ('cat <<EOF\nnpm ci\nEOF\npytest', 'tests'),
    ('npx playwright test', 'e2e'),
    ('FOO=1 xvfb-run -a npx playwright test', 'e2e'),
    ('timeout 600 nice -n 10 e2e/run.sh emulator-5554 tour', 'e2e'),
    ('bash e2e/run.sh emulator-5554', 'e2e'),
    ('maestro test flows/login.yaml', 'e2e'),
    ('ddev e2e', 'e2e'),
    ('docker run --rm mcr.microsoft.com/playwright:v1.63.0-noble sh -c "npm test"', 'e2e'),
    ('ddev exec -d /var/www/html "npm ci && npm test"', 'install'),
    ('$ANDROID_HOME/emulator/emulator -avd test_avd -no-window -gpu host -port 5554', 'emulator'),
    ('/home/user/Android/Sdk/emulator/qemu/linux-x86_64/qemu-system-x86_64 -m 2048 -netdelay none', 'emulator'),
    # video renders
    ('make video VIDEO=guia-vote ARGS=--compose-music', 'render'),
    ('cd videos && make videos', 'render'),
    ('ffmpeg -v error -y -i out/frames.mp4 -c:v libx264 -crf 20 out/guia.mp4', 'render'),
    ('ffmpeg -f image2pipe -i - out/video.webm', 'render'),
    ('npx remotion render src/index.ts Main out.mp4', 'render'),
    ('ffmpeg -i in.mp4 -frames:v 1 poster.jpg', None),
    ('ffmpeg -y -i voice.wav voice.mp3', None),
    ('ffmpeg -version', None),
    ('make videos-doctor', None),
    ('make video-status', None),
    ('whisper audio.mp3 --model large-v3', 'ml'),
    ('faster-whisper audio.wav', 'ml'),
    ('whisperx --diarize talk.wav', 'ml'),
    ('whisper-ctranslate2 talk.wav --model small', 'ml'),
    ('torchrun --nproc_per_node 2 train.py', 'ml'),
    ('accelerate launch train.py', 'ml'),
    ('python3 -m whisper talk.mp3', 'ml'),
    ('cd x && .venv/bin/python -m faster_whisper talk.mp3', 'ml'),
    ('python -m whisperx talk.mp3', 'ml'),
    ('python -m torch.distributed.run --nproc_per_node 2 t.py', 'ml'),
    ('uv run whisper talk.mp3', 'ml'),
    ('nohup timeout 900 whisper talk.mp3 > /tmp/w.log 2>&1 &', 'ml'),
    ('python /x/.venv/bin/whisperx talk.wav', 'ml'),
    ('make ci', 'gate'),
    ('tools/worktree-slot.sh make ci', 'gate'),
    ('make test-e2e-critical', 'gate'),
    ('make -C app -j 4 check', 'gate'),
    ('make -j8 test-unit', 'gate'),
    ('if true; then make smoke; fi', 'gate'),
    # light
    ('./gradlew --stop', None),
    ('./gradlew --version', None),
    ('grep -n "npm ci" Makefile', None),
    ('git commit -m "run pytest"', None),
    ('git commit -m "make ci" && git push', None),
    ('echo pytest', None),
    ('echo "npm ci" > notes.txt', None),
    ('cat file | grep pytest', None),
    ('# npm ci', None),
    ('cat > f <<\'EOF\'\nnpm ci\nEOF', None),
    ('pytest tests/test_x.py -q', None),
    ('pytest a.py::test_x', None),
    ('pytest -k foo', None),
    ('npm run test:plan', None),
    ('npm run test:selector', None),
    ('npm run build', None),
    ('npm install lodash', None),
    ('npx jest __tests__/ui/a.test.tsx', None),
    ('npx playwright install', None),
    ('phpunit tests/FooTest.php', None),
    # explicit targets hidden behind a shell expansion
    ('for f in tests/Unit/*Test.php; do vendor/bin/phpunit $f; done', 'tests'),  # glob of unknown files: a series
    ('vendor/bin/phpunit "$f"', None),
    ('vendor/bin/phpunit ${TARGET}', None),
    ('vendor/bin/phpunit $(ls tests/Unit/Forum/*Test.php)', None),
    ('r(){ XDEBUG_MODE=off vendor/bin/phpunit $1; }; r tests/Unit/FooTest.php', None),
    ('pytest $f -q', None),
    ('XDEBUG_MODE=off tools/worktree-slot.sh exec vendor/bin/phpunit --group REQ-VOT-17', None),
    ('vendor/bin/phpunit --group=REQ-FOR-03 tests/Unit/Forum', None),
    ('vendor/bin/phpunit --list-tests', None),
    ('vendor/bin/phpunit --list-groups', None),
    ('pytest --collect-only -q', None),
    ('uv run pytest --co -q', None),
    ('npx vitest run -t "adds a user"', None),
    ('npx jest --testNamePattern foo', None),
    ('npx jest --findRelatedTests src/a.ts', None),
    ('npx playwright test --grep @smoke', None),
    ('npx playwright test e2e/login.spec.ts', None),
    ('npx playwright test e2e/login.spec.ts:42', None),
    ('npx playwright test --list', None),
    # stays heavy: forwarded arguments prove nothing, a runner with options only is a whole suite
    ('vendor/bin/phpunit "$@"', 'tests'),
    ('pytest $*', 'tests'),
    ('vendor/bin/phpunit --testsuite unit', 'tests'),
    ('vendor/bin/phpunit --exclude-group slow', 'tests'),
    ('uv run pytest -q -x', 'tests'),
    ('npx playwright test --project chromium', 'e2e'),
    ('ddev exec vendor/bin/phpunit --filter Foo', None),
    ('ddev exec ls', None),
    ('make test-lock-status', None),
    ('make test-plan', None),
    ('make ci-status', None),
    ('make -n ci', None),
    ('make lint', None),
    ('emulator -list-avds', None),
    ('adb devices', None),
    ('docker ps', None),
    ('docker run --rm alpine echo hi', None),
    ('cd /x', None),
    ('ls -la', None),
    ('python3 script.py', None),
    ('whisper --help', None),
    ('torchrun --version', None),
    ('accelerate config', None),
    ('echo whisper talk.mp3', None),
    ('grep -n whisperx requirements.txt', None),
    ('pip install openai-whisper', None),
    ('FOO=1', None),
]


class SmallTestTargetTest(unittest.TestCase):
    """Directories with at most MAX_LIGHT_TEST_FILES test files are a light run; anything bigger or uninspectable is a suite."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='heavy-job-targets-')
        self.addCleanup(shutil.rmtree, self.root, True)

    def touch(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as handle:
            handle.write('')
        return path

    def populate(self, directory, count, pattern='Test{}Test.php'):
        for i in range(count):
            self.touch(directory, pattern.format(i))

    def kind(self, command, cwd=None):
        result = HJ.classify_command(command, cwd=cwd or self.root)
        return result[0] if result else None

    def test_small_directory_is_light_for_each_runner(self):
        self.populate('tests/Unit/Assistant', 3)
        self.populate('py_tests', 2, 'test_{}.py')
        self.populate('web/__tests__', 2, 'a{}.test.ts')
        self.populate('e2e', 1, 'a{}.spec.ts')
        for command in ('vendor/bin/phpunit tests/Unit/Assistant', 'bin/phpunit tests/Unit/Assistant/',
                        'pytest py_tests', 'uv run pytest -q py_tests', 'npx vitest run web/__tests__',
                        'npx jest web', 'npx playwright test e2e',
                        'XDEBUG_MODE=off tools/worktree-slot.sh exec vendor/bin/phpunit tests/Unit/Assistant'):
            with self.subTest(command=command):
                self.assertIsNone(self.kind(command))

    def test_directory_limit_is_five_files(self):
        self.populate('tests/Unit/Five', 5)
        self.populate('tests/Unit/Six', 6)
        self.assertIsNone(self.kind('phpunit tests/Unit/Five'))
        self.assertEqual(self.kind('phpunit tests/Unit/Six'), 'tests')
        self.assertEqual(self.kind('phpunit tests/Unit'), 'tests')       # 5 + 6 together
        self.assertEqual(self.kind('phpunit tests/Unit/Five tests/Unit/Six'), 'tests')

    def test_counts_every_test_file_pattern_recursively(self):
        for rel in ('d/test_a.py', 'd/b_test.py', 'd/sub/CTest.php', 'd/sub/x.test.ts', 'd/sub/deep/y.spec.js'):
            self.touch(rel)
        self.assertEqual(HJ._count_test_files(os.path.join(self.root, 'd')), 5)
        self.touch('d/sub/deep/z.spec.js')
        self.assertGreater(HJ._count_test_files(os.path.join(self.root, 'd')), 5)

    def test_ignores_vendor_node_modules_and_git(self):
        self.populate('pkg/tests', 2)
        for skipped in ('node_modules', 'vendor', '.git'):
            self.populate(os.path.join('pkg', skipped), 20)
        self.assertEqual(HJ._count_test_files(os.path.join(self.root, 'pkg')), 2)
        self.assertIsNone(self.kind('phpunit pkg'))

    def test_helper_files_do_not_count(self):
        for i in range(30):
            self.touch('tests/Unit/Helpers', f'Helper{i}.php')
        self.touch('tests/Unit/Helpers/OneTest.php')
        self.assertIsNone(self.kind('phpunit tests/Unit/Helpers'))

    def test_uninspectable_directory_stays_heavy(self):
        self.assertEqual(self.kind('phpunit tests/Unit/Missing'), 'tests')
        self.assertEqual(self.kind('pytest no/such/dir'), 'tests')
        os.makedirs(os.path.join(self.root, 'empty'))
        self.assertEqual(self.kind('phpunit empty'), 'tests')            # nothing to run is not a reason to skip the gate
        locked = os.path.join(self.root, 'locked')
        self.populate('locked', 1)
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        if os.access(locked, os.R_OK):
            self.skipTest('running as a user that ignores permissions')
        self.assertEqual(self.kind('phpunit locked'), 'tests')

    def test_cd_in_the_line_and_the_cwd_argument_decide_where_to_count(self):
        self.populate('proj/tests/Unit/Small', 2)
        self.populate('other/tests/Unit/Small', 9)
        proj = os.path.join(self.root, 'proj')
        self.assertIsNone(self.kind('phpunit tests/Unit/Small', cwd=proj))
        self.assertEqual(self.kind('phpunit tests/Unit/Small', cwd=os.path.join(self.root, 'other')), 'tests')
        self.assertIsNone(self.kind(f'cd {proj} && phpunit tests/Unit/Small', cwd=os.path.join(self.root, 'other')))
        self.assertEqual(self.kind(f'cd {os.path.join(self.root, "other")} && phpunit tests/Unit/Small', cwd=proj),
                         'tests')
        self.assertEqual(self.kind('cd proj && cd .. && phpunit tests/Unit/Small'), 'tests')     # no such dir at the root

    def test_cwd_does_not_leak_between_calls(self):
        self.populate('proj/tests/Unit/Small', 2)
        self.assertIsNone(self.kind('phpunit tests/Unit/Small', cwd=os.path.join(self.root, 'proj')))
        self.assertIsNone(HJ.classifier._CWD)
        self.assertIsNone(self.kind(f'cd {os.path.join(self.root, "proj")} && ls'))
        self.assertIsNone(HJ.classifier._CWD)

    def test_glob_operands_are_expanded(self):
        self.populate('tests/Unit/A', 2)
        self.populate('tests/Unit/B', 2)
        self.assertIsNone(self.kind('phpunit tests/Unit/A*'))
        self.assertIsNone(self.kind('phpunit tests/Unit/*'))                  # 4 files in total
        self.populate('tests/Unit/C', 3)
        self.assertEqual(self.kind('phpunit tests/Unit/*'), 'tests')
        self.assertEqual(self.kind('phpunit tests/Nothing/*'), 'tests')

    def test_filters_and_files_win_over_big_directories(self):
        self.populate('tests/Unit/Big', 40)
        self.assertIsNone(self.kind('phpunit --filter Foo tests/Unit/Big'))
        self.assertIsNone(self.kind('phpunit --group g tests/Unit/Big'))
        self.assertIsNone(self.kind('phpunit tests/Unit/Big/Test1Test.php'))
        self.assertEqual(self.kind('phpunit tests/Unit/Big'), 'tests')
        self.assertEqual(self.kind('phpunit -c phpunit.xml.dist tests/Unit/Big'), 'tests')

    def test_gate_entry_point_takes_the_cwd(self):
        self.populate('tests/Unit/Small', 2)
        self.assertIsNone(HJ.classify_outside_semaphore('phpunit tests/Unit/Small', self.root))
        self.assertEqual(HJ.classify_outside_semaphore('heavy-job status && phpunit tests/Unit/Nope', self.root)[0],
                         'tests')

    def test_denied_commands_of_2026_11_07_are_light(self):
        """Real denials (shortened) that only ever targeted a few files."""
        self.populate('tests/Unit/Messaging', 3)
        cases = [
            'cd {r} && for f in tests/Unit/Messaging/*Test.php; do XDEBUG_MODE=off tools/worktree-slot.sh exec vendor/bin/phpunit $f 2>&1 | tail -3; done',
            'cd {r} && XDEBUG_MODE=off tools/worktree-slot.sh exec vendor/bin/phpunit tests/Unit/Messaging 2>&1 | tail -8',
            'XDEBUG_MODE=off tools/worktree-slot.sh exec vendor/bin/phpunit $(ls tests/Unit/Messaging/*Test.php | head -2)',
            'cd {r} && for r in REQ-VOT-17 REQ-VOT-18; do XDEBUG_MODE=off timeout 600 tools/worktree-slot.sh exec vendor/bin/phpunit --group $r 2>&1 | tail -6; done',
            'cd {r} && XDEBUG_MODE=off tools/worktree-slot.sh exec vendor/bin/phpunit --group REQ-FOR-03 tests/Unit/Forum',
            'cd {r} && pytest --collect-only -q 2>&1 | tail -3',
        ]
        for command in cases:
            with self.subTest(command=command):
                self.assertIsNone(self.kind(command.format(r=self.root)))



class ClassifierTest(unittest.TestCase):
    def test_table_size(self):
        self.assertGreaterEqual(len(CLASSIFY_CASES), 40)
        self.assertGreaterEqual(sum(1 for _, kind in CLASSIFY_CASES if kind == 'ml'), 10)

    def test_command_table(self):
        for command, kind in CLASSIFY_CASES:
            with self.subTest(command=command):
                result = HJ.classify_command(command)
                self.assertEqual(result[0] if result else None, kind, result)
                if result:
                    self.assertTrue(result[1])

    def test_outside_semaphore(self):
        cases = [
            ('heavy-job run -- npm ci', None),
            ('~/.claude/scripts/heavy-job run --kind gate -- make ci', None),
            ('cd /x && VAR=1 nohup timeout 60 heavy-job hold --kind emulator -- emulator -avd x &', None),
            ('bash -c "heavy-job run -- npm ci"', None),
            ('heavy-job run -- bash -c "npm ci && npm test"', None),
            ('heavy-job status', None),
            ('grep -n heavy-job README.md', None),
            ('heavy-job run -- npm ci && npm test', 'tests'),
            ('heavy-job run -- npm ci; npm ci', 'install'),
            ('heavy-job status && ./gradlew assembleDebug', 'build'),
            ('heavy-job run --kind ml -- whisper a.mp3', None),
            ('heavy-job run --kind ml -- whisper a.mp3 && whisper b.mp3', 'ml'),
            ('echo heavy-job; npm ci', 'install'),
            ('make -C /tmp/heavy-job-probe ci', 'gate'),
            ('bash -c "heavy-job run -- npm ci; npm test"', 'tests'),
            ('npm ci', 'install'),
        ]
        for command, kind in cases:
            with self.subTest(command=command):
                result = HJ.classify_outside_semaphore(command)
                self.assertEqual(result[0] if result else None, kind, result)

    def test_argv_cases(self):
        cases = [
            (DOCKER_QEMU, None),
            (GRADLE_DAEMON, None),
            (GRADLE_CLIENT, 'build'),
            (GRADLE_CLIENT_STOP, None),
            (MAESTRO_JAVA, 'e2e'),
            (['node', '/usr/lib/node_modules/npm/bin/npm-cli.js', 'ci'], 'install'),
            (['node', '/x/node_modules/jest/bin/jest.js'], 'tests'),
            (['node', '/x/node_modules/jest/bin/jest.js', 'src/a.test.ts'], None),
            (['node', '/x/node_modules/playwright/cli.js', 'test'], 'e2e'),
            (['node', '/x/node_modules/playwright/cli.js', 'run-mcp-server'], None),
            (['python', '/x/.venv/bin/pytest', '-x'], 'tests'),
            (['php', 'vendor/bin/phpunit'], 'tests'),
            (['npm', 'exec', '@upstash/context7-mcp@latest'], None),
            (['pytest'], 'tests'),
            ([], None),
        ]
        for argv, kind in cases:
            with self.subTest(argv=argv):
                result = HJ.classify_argv(argv)
                self.assertEqual(result[0] if result else None, kind, result)

    def test_unbalanced_quote_falls_back(self):
        result = HJ.classify_command('echo "oops; npm ci')
        self.assertIsNotNone(result)  # plain split fallback still sees npm ci

    def test_cli_classify(self):
        def run(*args, stdin=None):
            return subprocess.run([sys.executable, SCRIPT, 'classify', *args], capture_output=True, text=True,
                                  input=stdin)

        heavy = run('--', 'cd x && make ci')
        self.assertEqual(heavy.returncode, 0)
        self.assertIn('gate', heavy.stdout)
        light = run('--', 'ls')
        self.assertEqual(light.returncode, 1)
        data = json.loads(run('--json', '--', 'npm ci').stdout)
        self.assertEqual((data['heavy'], data['kind']), (True, 'install'))
        self.assertEqual(run('--stdin', stdin='npm test\n').returncode, 0)
        self.assertEqual(run('--stdin', stdin='ls\n').returncode, 1)
        self.assertEqual(run().returncode, 2)


VITEST_WORKER = ['/usr/bin/node', '--conditions', 'node', '/x/node_modules/vitest/dist/workers/forks.js']
VITEST_MAIN = ['node', '/x/node_modules/vitest/vitest.mjs', 'run']


class OrphanWorkerTest(unittest.TestCase):
    def kind(self, argv, parent):
        result = HJ.orphan_test_worker(argv, parent)
        return result[0] if result else None

    def test_live_runner_parent_is_not_an_orphan(self):
        self.assertIsNone(self.kind(VITEST_WORKER, VITEST_MAIN))
        self.assertIsNone(self.kind(VITEST_WORKER, ['node', '/x/node_modules/.bin/vitest']))
        self.assertIsNone(self.kind(['node', '/x/node_modules/vitest/dist/child.js'], ['node', '/x/VITEST/cli.js']))
        self.assertIsNone(self.kind(['node', '/x/node_modules/jest-worker/build/workers/processChild.js'],
                                    ['node', '/x/node_modules/jest/bin/jest.js']))
        self.assertIsNone(self.kind(['node', '/x/node_modules/playwright/lib/common/process.js'],
                                    ['node', '/x/node_modules/playwright/cli.js', 'test']))

    def test_gone_runner_parent_is_an_orphan(self):
        for parent in (['/usr/lib/systemd/systemd', '--user'], ['/sbin/init'], ['bash'], ['node', '/x/other.js'],
                       None, []):
            with self.subTest(parent=parent):
                result = HJ.orphan_test_worker(VITEST_WORKER, parent)
                self.assertEqual(result[0], 'tests')
                self.assertIn('vitest', result[1])

    def test_worker_patterns(self):
        cases = [
            (['node', '/x/node_modules/vitest/dist/workers/vmForks.js'], 'vitest'),
            (['node', '/x/node_modules/vitest/dist/worker.js'], 'vitest'),
            (['node', '/x/node_modules/vitest/dist/child.js'], 'vitest'),
            (['node', '/x/node_modules/.pnpm/vitest@3/node_modules/vitest/dist/workers/forks.js'], 'vitest'),
            (['node', '/x/node_modules/jest-worker/build/workers/processChild.js'], 'jest'),
            (['node', '/x/node_modules/jest-worker/build/workers/threadChild.js'], 'jest'),
            (['node', '/x/node_modules/jest-worker/build/processChild.js'], 'jest'),
            (['node', '/x/node_modules/playwright/lib/common/process.js'], 'playwright'),
            (['node', '/x/node_modules/playwright/lib/worker/workerProcessEntry.js'], 'playwright'),
        ]
        for argv, runner in cases:
            with self.subTest(argv=argv):
                result = HJ.orphan_test_worker(argv, ['/usr/lib/systemd/systemd', '--user'])
                self.assertIsNotNone(result)
                self.assertIn(runner, result[1])

    def test_not_a_worker(self):
        for argv in (VITEST_MAIN, ['node', '/x/node_modules/vitest/dist/cli.js'], ['node', 'server.js'],
                     ['python3', 'vitest_notes.py'], ['grep', 'vitest/dist/workers/forks.jsx'], ['node'], []):
            with self.subTest(argv=argv):
                self.assertIsNone(HJ.orphan_test_worker(argv, None))

    def test_metro_workers_are_not_orphans_of_a_live_bundler(self):
        argv = ['node', '/x/node_modules/jest-worker/build/workers/processChild.js']
        self.assertIsNone(self.kind(argv, ['node', '/x/node_modules/metro/src/cli.js', 'serve']))
        self.assertIsNone(self.kind(argv, ['node', '/x/node_modules/react-native/cli.js', 'start']))


class SlotCountTest(unittest.TestCase):
    def test_resolution_order(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, '.config', 'heavy-job'))
            base = {'HOME': home}
            with mock.patch.dict(os.environ, base, clear=False):
                os.environ.pop('HEAVY_JOB_SLOTS', None)
                with mock.patch.dict(HJ.CONFIG, default_slots=2):
                    self.assertEqual(HJ.slot_count(), 2)
                with mock.patch.dict(HJ.CONFIG, default_slots=4):
                    self.assertEqual(HJ.slot_count(), 4)
                    with open(os.path.join(home, '.config', 'heavy-job', 'slots'), 'w') as handle:
                        handle.write('3\nignored\n')
                    self.assertEqual(HJ.slot_count(), 3)
                    os.environ['HEAVY_JOB_SLOTS'] = '5'
                    self.assertEqual(HJ.slot_count(), 5)
                    os.environ['HEAVY_JOB_SLOTS'] = 'nonsense'
                    self.assertEqual(HJ.slot_count(), 3)


class SlotTestCase(unittest.TestCase):
    """Base: temporary slot dir, one slot, scan off, fast polling; kills the leftovers."""
    slots = '1'
    scan = '0'

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='heavy-job-test-')
        self.env = dict(os.environ, HEAVY_JOB_DIR=self.dir, HEAVY_JOB_SLOTS=self.slots, HEAVY_JOB_SCAN=self.scan,
                        HEAVY_JOB_POLL='0.2', HEAVY_JOB_MIN_AVAIL_GIB='0', HEAVY_JOB_SETTLE='0',
                        HEAVY_JOB_SCAN_SCOPE=os.path.basename(self.dir))  # the machine's real jobs stay out of the scan
        self.env.pop('HEAVY_JOB_SLOT', None)
        self.procs = []

    def tearDown(self):
        for proc in self.procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    stream.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def hj(self, *args, timeout=30):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=self.env,
                              timeout=timeout)

    def spawn(self, *args, env=None):
        proc = subprocess.Popen([sys.executable, SCRIPT, *args], env=env or self.env, start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(proc)
        return proc

    def wait_for_json(self, slot=0, timeout=10):
        path = os.path.join(self.dir, f'slot-{slot}.json')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with open(path) as handle:
                    return json.load(handle)
            except (OSError, ValueError):
                time.sleep(0.05)
        self.fail(f'{path} never appeared')

    def status(self):
        out = self.hj('status', '--json')
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)


class SlotTest(SlotTestCase):
    def test_second_job_starts_after_first_ends(self):
        end_file = os.path.join(self.dir, 'a-end')
        first = self.spawn('run', '--label', 'A', '--', sys.executable, '-c',
                           f'import time; time.sleep(2); open({end_file!r}, "w").write(repr(time.time()))')
        self.wait_for_json()
        second = self.hj('run', '--label', 'B', '--', sys.executable, '-c', 'import time; print(time.time())')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('sin hueco libre', second.stderr)
        self.assertIn('"A"', second.stderr)  # says who occupies the slot
        started_b = float(second.stdout.strip())
        first.wait(timeout=10)
        with open(end_file) as handle:
            ended_a = float(handle.read())
        self.assertGreaterEqual(started_b, ended_a)

    def test_no_wait_exits_75_when_busy(self):
        self.spawn('run', '--label', 'busy', '--', 'sleep', '5')
        self.wait_for_json()
        result = self.hj('run', '--no-wait', '--', 'true')
        self.assertEqual(result.returncode, 75)
        self.assertIn('busy', result.stderr)

    def test_max_wait_exits_75(self):
        self.spawn('run', '--', 'sleep', '5')
        self.wait_for_json()
        started = time.monotonic()
        result = self.hj('run', '--max-wait', '1', '--', 'true')
        self.assertEqual(result.returncode, 75)
        self.assertLess(time.monotonic() - started, 4)

    def test_default_wait_has_no_limit(self):
        self.assertEqual(HJ.DEFAULT_MAX_WAIT, 0)
        args = HJ.build_parser().parse_args(['run'])
        self.assertEqual(args.max_wait, 0)
        self.assertEqual(HJ.build_parser().parse_args(['hold']).max_wait, 0)
        self.assertEqual(HJ.build_parser().parse_args(['run', '--max-wait', '7']).max_wait, 7)

    def test_waiter_without_max_wait_keeps_waiting_and_then_runs(self):
        holder = self.spawn('run', '--', 'sleep', '3')
        self.wait_for_json()
        started = time.monotonic()
        for extra in ((), ('--max-wait', '0')):
            result = self.hj('run', *extra, '--', 'true')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('espero', result.stderr)
            self.assertGreaterEqual(time.monotonic() - started, 2)
            holder = self.spawn('run', '--', 'sleep', '2')
            self.wait_for_json()
            started = time.monotonic()

    def test_wait_for_turn_accepts_none_as_unlimited(self):
        holder = self.spawn('run', '--', 'sleep', '2')
        self.wait_for_json()
        with mock.patch.dict(os.environ, self.env):
            started = time.monotonic()
            fds, slots, directory, weight = HJ.acquire(1, None, False)
            for handle in fds:
                os.close(handle)
            self.assertGreaterEqual(time.monotonic() - started, 1)

    def test_no_wait_still_exits_75_and_max_wait_still_limits(self):
        self.spawn('run', '--', 'sleep', '6')
        self.wait_for_json()
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 75)
        started = time.monotonic()
        result = self.hj('run', '--max-wait', '1', '--', 'true')
        self.assertEqual(result.returncode, 75)
        self.assertIn('han pasado', result.stderr)
        self.assertLess(time.monotonic() - started, 4)

    def test_unlimited_waiters_keep_fifo_order(self):
        holder = self.spawn('run', '--', 'sleep', '2')
        self.wait_for_json()
        first = self.spawn('run', '--label', 'first', '--', 'sh', '-c', 'echo first; sleep 1')
        time.sleep(1.0)
        second = self.spawn('run', '--label', 'second', '--', 'sh', '-c', 'echo second')
        time.sleep(1.0)
        out1, _ = first.communicate(timeout=20)
        out2, _ = second.communicate(timeout=20)
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertIn('first', out1)
        self.assertIn('second', out2)

    def test_run_propagates_exit_code_env_and_cleans_json(self):
        result = self.hj('run', '--', 'sh', '-c', 'exit 7')
        self.assertEqual(result.returncode, 7)
        out = self.hj('run', '--label', 'lbl', '--', 'sh', '-c', 'echo "$HEAVY_JOB_SLOT $HEAVY_JOB_LABEL"')
        self.assertEqual(out.stdout.strip(), '0 lbl')
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'slot-0.json')))
        self.assertEqual(self.hj('run', '--', 'definitely-not-a-command-xyz').returncode, 127)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.hj('run').returncode, 2)
        self.assertEqual(self.hj('run', 'true').returncode, 2)
        self.assertEqual(self.hj('bogus').returncode, 2)

    def test_json_describes_holder(self):
        repo = os.path.join(self.dir, 'myrepo')
        os.makedirs(repo)
        subprocess.run(['git', 'init', '-q', repo], check=True)
        proc = subprocess.Popen([sys.executable, SCRIPT, 'run', '--kind', 'tests', '--label', 'L1', '--', 'sleep',
                                 '5'], env=self.env, cwd=repo, start_new_session=True)
        self.procs.append(proc)
        info = self.wait_for_json()
        self.assertEqual((info['kind'], info['label'], info['project']), ('tests', 'L1', 'myrepo'))
        self.assertEqual(info['argv'], ['sleep', '5'])
        self.assertEqual(os.path.realpath(info['cwd']), os.path.realpath(repo))
        self.assertTrue(info['started'])
        self.assertNotEqual(info['pid'], proc.pid)  # the child's pid, not the wrapper's
        self.assertEqual(info['wrapper_pid'], proc.pid)

    def test_sigterm_is_forwarded_to_child(self):
        proc = self.spawn('run', '--', 'sleep', '30')
        child = self.wait_for_json()['pid']
        os.kill(proc.pid, signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 128 + signal.SIGTERM)
        time.sleep(0.2)
        self.assertFalse(os.path.exists(f'/proc/{child}') and 'sleep' in open(f'/proc/{child}/cmdline').read())

    def test_slot_survives_wrapper_sigkill(self):
        proc = self.spawn('run', '--', 'sleep', '30')
        child = self.wait_for_json()['pid']
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 75)
        os.kill(child, signal.SIGKILL)
        for _ in range(50):
            if self.hj('run', '--no-wait', '--', 'true').returncode == 0:
                break
            time.sleep(0.1)
        else:
            self.fail('slot was not released after the child died')

    def test_hold_keeps_slot_until_process_dies(self):
        proc = self.spawn('hold', '--label', 'emu', '--', 'sleep', '30')
        info = self.wait_for_json()
        self.assertEqual(info['pid'], proc.pid)  # exec keeps the pid
        self.assertEqual(info['mode'], 'hold')
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 75)
        status = self.status()
        self.assertTrue(status['slots'][0]['held'])
        self.assertEqual(status['slots'][0]['holder']['pid'], proc.pid)
        self.assertEqual(status['stale'], [])
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
        result = self.hj('run', '--no-wait', '--', 'true')
        self.assertEqual(result.returncode, 0, result.stderr)  # freed at once

    def test_status_detects_stale_json(self):
        proc = self.spawn('hold', '--', 'sleep', '30')
        self.wait_for_json()
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()  # hold cannot clean its json after exec: the lock is free but the json is left behind
        status = self.status()
        self.assertFalse(status['slots'][0]['held'])
        self.assertIsNone(status['slots'][0]['holder'])
        self.assertEqual([item['slot'] for item in status['stale']], [0])
        self.assertEqual(status['free_effective'], 1)
        text = self.hj('status').stdout
        self.assertIn('libre', text)
        self.assertIn('json obsoleto', text)
        self.assertIn('Memoria disponible', text)
        self.assertIn('Carga', text)

    def test_status_reports_memory_and_load(self):
        status = self.status()
        self.assertEqual(status['slot_count'], 1)
        self.assertIsNotNone(status['mem_available_kib'])
        self.assertIsNotNone(status['swap_used_kib'])
        self.assertEqual(len(status['load']), 3)


class DetachTest(SlotTestCase):
    """`run --detach`: the job waits and runs outside the launching process (setsid launcher in tests)."""

    def setUp(self):
        super().setUp()
        self.ddir = os.path.join(self.dir, 'detached')
        self.env.update(HEAVY_JOB_DETACHED_DIR=self.ddir, HEAVY_JOB_DETACH_LAUNCHER='setsid')

    def tearDown(self):
        for name in (os.listdir(self.ddir) if os.path.isdir(self.ddir) else []):
            try:
                with open(os.path.join(self.ddir, name, 'runner.json')) as handle:
                    os.killpg(json.load(handle)['pid'], signal.SIGKILL)
            except (OSError, ValueError, KeyError):
                pass
        super().tearDown()

    def detach(self, *cmd, label='D', extra=()):
        out = self.hj('run', '--detach', '--label', label, *extra, '--', *cmd)
        self.assertEqual(out.returncode, 0, out.stderr)
        job_id = out.stdout.strip().splitlines()[0]
        self.assertRegex(job_id, r'^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$')
        return job_id

    def test_returns_at_once_and_wait_gives_code_and_output(self):
        started = time.monotonic()
        job_id = self.detach(sys.executable, '-c', 'import time,sys; time.sleep(1); print("hecho"); sys.exit(3)')
        self.assertLess(time.monotonic() - started, 5)
        out = self.hj('wait', job_id)
        self.assertEqual(out.returncode, 3, out.stderr)
        self.assertIn('hecho', out.stdout)
        self.assertIn('código 3', self.hj('jobs').stdout)
        self.assertIn('hecho', self.hj('logs', job_id).stdout)

    def test_environment_reaches_the_job_and_leaves_the_disk(self):
        self.env['HEAVY_JOB_TEST_MARK'] = 'marca-123'
        job_id = self.detach(sys.executable, '-c', 'import os; print(os.environ.get("HEAVY_JOB_TEST_MARK"))')
        out = self.hj('wait', job_id)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('marca-123', out.stdout)
        with open(os.path.join(self.ddir, job_id, 'job.json')) as handle:
            job = json.load(handle)
        self.assertNotIn('env', job)
        self.assertEqual(job['id'], job_id)

    def test_survives_the_death_of_the_launching_session(self):
        # a stand-in for the session: a shell in its own process group that launches the job and is then killed
        session = subprocess.Popen(
            ['bash', '-c', f'{shlex.quote(sys.executable)} {shlex.quote(SCRIPT)} run --detach --label cut -- '
                           f'{shlex.quote(sys.executable)} -c "import time; time.sleep(2); print(\'sobrevive\')"; sleep 60'],
            env=self.env, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.procs.append(session)
        job_id = session.stdout.readline().strip()
        os.killpg(session.pid, signal.SIGKILL)
        out = self.hj('wait', job_id)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('sobrevive', out.stdout)

    def test_queued_behind_a_busy_slot_and_named_in_status(self):
        # the slot stays busy until the test lets go of it: a holder that ends on a timer can end, on a slow machine,
        # before the checks that need the detached job still queued
        release = os.path.join(self.dir, 'release-holder')
        self.spawn('run', '--label', 'ocupa', '--', sys.executable, '-c',
                   f'import os, time\nwhile not os.path.exists({release!r}): time.sleep(0.05)')
        self.wait_for_json()
        job_id = self.detach(sys.executable, '-c', 'print("tras la cola")', label='en cola')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not self.status()['queue']:
            time.sleep(0.1)
        queue = self.status()['queue']
        self.assertEqual([e.get('detached') for e in queue], [job_id])
        self.assertIn(f'desacoplado {job_id}', self.hj('status').stdout)
        self.assertEqual(self.hj('wait', job_id, '--timeout', '0.5').returncode, HJ.WAIT_TIMED_OUT)
        open(release, 'w').close()
        out = self.hj('wait', job_id)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('tras la cola', out.stdout)

    def test_stop_ends_the_job_and_frees_the_slot(self):
        job_id = self.detach('sleep', '30')
        info = self.wait_for_json()
        self.assertEqual(info.get('detached'), job_id)
        self.assertEqual(self.hj('stop', job_id).returncode, 0)
        out = self.hj('wait', job_id)
        self.assertEqual(out.returncode, 128 + signal.SIGTERM, out.stderr)
        self.assertFalse(any(e['held'] for e in self.status()['slots']))
        self.assertEqual(self.hj('stop', job_id).returncode, 1)

    def test_a_runner_killed_hard_is_reported_dead_and_its_slot_freed(self):
        job_id = self.detach('sleep', '30')
        self.wait_for_json()
        with open(os.path.join(self.ddir, job_id, 'runner.json')) as handle:
            os.killpg(json.load(handle)['pid'], signal.SIGKILL)
        out = self.hj('wait', job_id)
        self.assertEqual(out.returncode, HJ.DETACHED_DIED, out.stderr)
        self.assertFalse(any(e['held'] for e in self.status()['slots']))

    def test_keeps_cwd_and_environment_and_a_private_job_file(self):
        work = tempfile.mkdtemp(dir=self.dir)
        env = dict(self.env, PROBE_VAR='valor-del-lanzador')
        out = subprocess.run([sys.executable, SCRIPT, 'run', '--detach', '--', sys.executable, '-c',
                              'import os; print(os.getcwd()); print(os.environ["PROBE_VAR"])'],
                             capture_output=True, text=True, env=env, cwd=work, timeout=30)
        job_id = out.stdout.strip().splitlines()[0]
        waited = self.hj('wait', job_id)
        self.assertEqual(waited.returncode, 0, waited.stderr)
        self.assertIn(os.path.realpath(work), waited.stdout)
        self.assertIn('valor-del-lanzador', waited.stdout)
        self.assertEqual(os.stat(os.path.join(self.ddir, job_id, 'job.json')).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.join(self.ddir, job_id)).st_mode & 0o777, 0o700)

    def test_bad_ids_and_hold_detach_are_refused(self):
        self.assertEqual(self.hj('wait', '../../etc').returncode, 2)
        self.assertEqual(self.hj('wait', '20990101-000000-abcdef').returncode, 2)
        self.assertEqual(self.hj('hold', '--detach', '--', 'true').returncode, 2)


class TwoSlotTest(SlotTestCase):
    slots = '2'

    def test_two_jobs_run_in_parallel_third_waits(self):
        self.spawn('run', '--', 'sleep', '5')
        self.wait_for_json(0)
        self.spawn('run', '--', 'sleep', '5')
        self.wait_for_json(1)
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 75)
        self.assertEqual(self.status()['free_effective'], 0)


class AdmissionPureTest(unittest.TestCase):
    """admission_block and the threshold/settle resolution; no processes involved."""
    GIB = 1048576

    def test_nothing_else_running_is_always_admitted(self):
        self.assertIsNone(HJ.admission_block(1, [], 0, 100, 2.5, 45, 1000.0))

    def test_memory_rule_scales_with_weight(self):
        holder = [{'pid': 7, 'started_ts': 100.0}]
        self.assertIsNone(HJ.admission_block(1, holder, 1, 3 * self.GIB, 2.5, 0, 1000.0))
        block = HJ.admission_block(2, holder, 1, 3 * self.GIB, 2.5, 0, 1000.0)
        self.assertEqual(block['reason'], 'memory')
        self.assertIn('3.0 GiB', block['text'])
        self.assertIn('5.0 GiB', block['text'])
        self.assertIsNone(HJ.admission_block(2, holder, 1, 5 * self.GIB, 2.5, 0, 1000.0))

    def test_threshold_zero_disables_memory_rule(self):
        self.assertIsNone(HJ.admission_block(1, [{'pid': 7, 'started_ts': 1.0}], 1, 1, 0, 0, 1000.0))

    def test_settle_names_the_pid_and_the_time_left(self):
        block = HJ.admission_block(1, [{'pid': 4242, 'started_ts': 990.0}], 1, 99 * self.GIB, 2.5, 45, 1000.0)
        self.assertEqual(block['reason'], 'settle')
        self.assertAlmostEqual(block['wait'], 35.0)
        self.assertIn('4242', block['text'])
        self.assertIn('35 s', block['text'])
        self.assertIsNone(HJ.admission_block(1, [{'pid': 4242, 'started_ts': 900.0}], 1, 99 * self.GIB, 2.5, 45,
                                             1000.0))

    def test_settle_takes_the_newest_holder_and_comes_before_memory(self):
        holders = [{'pid': 1, 'started_ts': 990.0}, {'pid': 2, 'started_ts': 998.0}]
        block = HJ.admission_block(1, holders, 2, 0, 2.5, 45, 1000.0)
        self.assertEqual((block['reason'], round(block['wait'])), ('settle', 43))
        self.assertIn('2', block['text'])

    def test_unwrapped_job_counts_as_another_job_for_memory(self):
        block = HJ.admission_block(1, [], 1, 1 * self.GIB, 2.5, 45, 1000.0)
        self.assertEqual(block['reason'], 'memory')

    def test_threshold_resolution_order(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, '.config', 'heavy-job'))
            with mock.patch.dict(os.environ, {'HOME': home}, clear=False):
                os.environ.pop('HEAVY_JOB_MIN_AVAIL_GIB', None)
                self.assertEqual(HJ.min_avail_gib(), 2.5)
                with open(os.path.join(home, '.config', 'heavy-job', 'min-available-gib'), 'w') as handle:
                    handle.write('3.5\nignored\n')
                self.assertEqual(HJ.min_avail_gib(), 3.5)
                os.environ['HEAVY_JOB_MIN_AVAIL_GIB'] = '1'
                self.assertEqual(HJ.min_avail_gib(), 1.0)
                os.environ['HEAVY_JOB_MIN_AVAIL_GIB'] = '0'
                self.assertEqual(HJ.min_avail_gib(), 0.0)
                os.environ['HEAVY_JOB_MIN_AVAIL_GIB'] = 'nonsense'
                self.assertEqual(HJ.min_avail_gib(), 3.5)

    def test_settle_resolution(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('HEAVY_JOB_SETTLE', None)
            self.assertEqual(HJ.settle_seconds(), 45.0)
            os.environ['HEAVY_JOB_SETTLE'] = '2'
            self.assertEqual(HJ.settle_seconds(), 2.0)
            os.environ['HEAVY_JOB_SETTLE'] = 'x'
            self.assertEqual(HJ.settle_seconds(), 45.0)


class AdmissionTest(SlotTestCase):
    slots = '3'

    def set_meminfo(self, gib_available):
        path = os.path.join(self.dir, 'meminfo')
        with open(path, 'w') as handle:
            handle.write(f'MemTotal:       15000000 kB\nMemAvailable:   {int(gib_available * 1048576)} kB\n'
                         'SwapTotal:      16000000 kB\nSwapFree:        6000000 kB\n')
        self.env['HEAVY_JOB_MEMINFO'] = path

    def test_low_memory_blocks_while_another_job_runs(self):
        self.set_meminfo(1.0)
        self.env['HEAVY_JOB_MIN_AVAIL_GIB'] = '2.5'
        self.spawn('run', '--label', 'first', '--', 'sleep', '30')
        self.wait_for_json(0)
        result = self.hj('run', '--no-wait', '--', 'true')
        self.assertEqual(result.returncode, 75)
        self.assertIn('memoria disponible 1.0 GiB', result.stderr)
        self.assertIn('2.5 GiB', result.stderr)
        self.assertIn('first', result.stderr)

    def test_low_memory_does_not_block_when_nothing_heavy_runs(self):
        self.set_meminfo(1.0)
        self.env['HEAVY_JOB_MIN_AVAIL_GIB'] = '2.5'
        result = self.hj('run', '--no-wait', '--', 'sh', '-c', 'echo ran')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'ran')
        self.assertIn('aviso', result.stderr)
        self.assertIn('memoria disponible 1.0 GiB', result.stderr)

    def test_enough_memory_admits_the_second_job(self):
        self.set_meminfo(4.0)
        self.env['HEAVY_JOB_MIN_AVAIL_GIB'] = '2.5'
        self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(0)
        result = self.hj('run', '--no-wait', '--', 'true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_waiting_job_starts_when_memory_recovers(self):
        self.set_meminfo(1.0)
        self.env['HEAVY_JOB_MIN_AVAIL_GIB'] = '2.5'
        self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(0)
        waiter = self.spawn('run', '--', 'sh', '-c', 'echo ran')
        time.sleep(1.0)
        self.assertIsNone(waiter.poll())
        self.set_meminfo(4.0)
        out, err = waiter.communicate(timeout=10)
        self.assertEqual(out.strip(), 'ran')
        self.assertIn('hay hueco, pero memoria disponible', err)
        self.assertIn('adelante', err)

    def test_weight_two_needs_twice_the_threshold(self):
        self.set_meminfo(3.0)
        self.env['HEAVY_JOB_MIN_AVAIL_GIB'] = '2'
        self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(0)
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 0)  # 3.0 >= 2 x 1
        heavy = self.hj('run', '--no-wait', '--kind', 'ml', '--', 'true')  # weight 2: 3.0 < 2 x 2
        self.assertEqual(heavy.returncode, 75)
        self.assertIn('4.0 GiB', heavy.stderr)
        self.assertIn('peso 2', heavy.stderr)
        self.set_meminfo(4.5)
        self.assertEqual(self.hj('run', '--no-wait', '--kind', 'ml', '--', 'true').returncode, 0)

    def test_settle_makes_the_second_job_wait_about_that_long(self):
        self.env['HEAVY_JOB_SETTLE'] = '2'
        self.spawn('run', '--label', 'first', '--', 'sleep', '30')
        self.wait_for_json(0)
        started = time.monotonic()
        result = self.hj('run', '--', 'sh', '-c', 'echo ran')
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLess(elapsed, 5.0)
        self.assertIn('arrancó hace', result.stderr)
        self.assertIn('espero', result.stderr)

    def test_settle_message_with_no_wait(self):
        self.env['HEAVY_JOB_SETTLE'] = '30'
        proc = self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(0)
        result = self.hj('run', '--no-wait', '--', 'true')
        self.assertEqual(result.returncode, 75)
        self.assertIn('arrancó hace', result.stderr)
        self.assertIn('espero', result.stderr)
        self.assertIn('pausa de 30 s', result.stderr)
        self.assertNotEqual(proc.pid, 0)

    def test_settle_ignored_when_nothing_else_runs(self):
        self.env['HEAVY_JOB_SETTLE'] = '30'
        started = time.monotonic()
        self.assertEqual(self.hj('run', '--', 'true').returncode, 0)
        self.assertLess(time.monotonic() - started, 5)

    def test_old_holder_does_not_trigger_settle(self):
        self.env['HEAVY_JOB_SETTLE'] = '1'
        self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(0)
        time.sleep(1.3)
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 0)

    def test_status_reports_admission(self):
        self.set_meminfo(1.0)
        self.env['HEAVY_JOB_MIN_AVAIL_GIB'] = '2.5'
        status = self.status()
        self.assertEqual((status['min_avail_gib'], status['settle_s']), (2.5, 0.0))
        self.assertTrue(status['admission']['admitted'])  # nothing else running
        text = self.hj('status').stdout
        self.assertIn('umbral de memoria 2.5 GiB', text)
        self.assertIn('se admitiría', text)
        self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(0)
        status = self.status()
        self.assertFalse(status['admission']['admitted'])
        self.assertEqual(status['admission']['reason'], 'memory')
        self.assertIn('NO se admitiría: memoria disponible 1.0 GiB', self.hj('status').stdout)
        self.env['HEAVY_JOB_MIN_AVAIL_GIB'] = '0'
        self.assertTrue(self.status()['admission']['admitted'])
        self.assertIn('desactivado', self.hj('status').stdout)

    def test_status_reports_settle(self):
        self.env['HEAVY_JOB_SETTLE'] = '30'
        self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(0)
        admission = self.status()['admission']
        self.assertEqual(admission['reason'], 'settle')
        self.assertIn('espero', admission['text'])
        self.assertIn('NO se admitiría', self.hj('status').stdout)

    def test_status_reports_full_slots(self):
        self.spawn('run', '--weight', '3', '--', 'sleep', '30')
        self.wait_for_json(2)
        admission = self.status()['admission']
        self.assertEqual((admission['admitted'], admission['reason']), (False, 'slots'))


class WeightTest(SlotTestCase):
    slots = '3'

    def test_probe_slots_is_all_or_nothing(self):
        with tempfile.TemporaryDirectory(prefix='probe-test-') as directory:
            fds, slots, held = HJ.probe_slots(directory, 3, 2)
            self.assertEqual((slots, held), ([0, 1], []))
            other = HJ.probe_slots(directory, 3, 2)  # only slot 2 is free: nothing is kept
            self.assertEqual(other, ([], [], [0, 1]))
            self.assertEqual(HJ.probe_slots(directory, 3, 1)[1], [2])
            for handle in fds:
                os.close(handle)

    def test_weight_two_blocks_another_weight_two_while_weight_one_runs(self):
        big = self.spawn('hold', '--weight', '2', '--label', 'big', '--', 'sleep', '30')
        self.wait_for_json(0)
        self.assertEqual(self.hj('run', '--no-wait', '--weight', '2', '--', 'true').returncode, 75)  # 1 free slot
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 0)  # a weight-1 job fits
        small = self.spawn('run', '--label', 'small', '--', 'sleep', '30')
        self.wait_for_json(2)
        blocked = self.hj('run', '--no-wait', '--weight', '2', '--', 'true')
        self.assertEqual(blocked.returncode, 75)
        self.assertIn('necesito 2', blocked.stderr)
        self.assertIn('big', blocked.stderr)
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 75)  # full now
        self.assertIsNotNone(big.pid)
        self.assertIsNotNone(small.pid)

    def test_weight_two_waits_for_two_slots_and_takes_both(self):
        self.spawn('run', '--', 'sleep', '2')
        self.wait_for_json(0)
        self.spawn('run', '--', 'sleep', '30')
        self.wait_for_json(1)
        started = time.monotonic()
        out = self.hj('run', '--weight', '2', '--', 'sh', '-c', 'echo "$HEAVY_JOB_SLOT"')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), '0,2')  # slot 0 was freed by the 2 s job, slot 1 stays held
        self.assertGreaterEqual(time.monotonic() - started, 0.5)  # it had to wait for the 2 s job

    def test_multi_slot_job_json_status_and_cleanup(self):
        proc = self.spawn('run', '--weight', '2', '--label', 'duo', '--', 'sleep', '30')
        self.wait_for_json(0)
        infos = [self.wait_for_json(i) for i in (0, 1)]
        for info in infos:
            self.assertEqual((info['slots'], info['weight'], info['label']), ([0, 1], 2, 'duo'))
        self.assertEqual(infos[0]['pid'], infos[1]['pid'])
        status = self.status()
        self.assertEqual(len(status['jobs']), 1)  # one job, shown once
        self.assertEqual(status['free_effective'], 1)
        text = self.hj('status').stdout
        self.assertEqual(text.count('"duo"'), 1)
        self.assertIn('peso 2', text)
        self.assertIn('mismo trabajo', text)
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
        time.sleep(0.2)
        for i in (0, 1):
            self.assertFalse(os.path.exists(os.path.join(self.dir, f'slot-{i}.json')))

    def test_hold_weight_two_keeps_both_slots(self):
        proc = self.spawn('hold', '--weight', '2', '--', 'sleep', '30')
        self.wait_for_json(0)
        self.assertEqual(self.wait_for_json(1)['pid'], proc.pid)
        status = self.status()
        self.assertTrue(status['slots'][0]['held'] and status['slots'][1]['held'])
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
        self.assertEqual(self.hj('run', '--no-wait', '--weight', '3', '--', 'true').returncode, 0)

    def test_kind_ml_defaults_to_weight_two(self):
        out = self.hj('run', '--kind', 'ml', '--', 'sh', '-c', 'echo "$HEAVY_JOB_SLOT"')
        self.assertEqual(out.stdout.strip(), '0,1')
        one = self.hj('run', '--kind', 'ml', '--weight', '1', '--', 'sh', '-c', 'echo "$HEAVY_JOB_SLOT"')
        self.assertEqual(one.stdout.strip(), '0')
        classified = self.hj('run', '--', 'sh', '-c', 'echo "$HEAVY_JOB_SLOT"')
        self.assertEqual(classified.stdout.strip(), '0')
        holder = self.spawn('run', '--kind', 'ml', '--', 'sleep', '30')
        self.assertEqual(self.wait_for_json(0)['weight'], 2)
        self.assertIsNotNone(holder.pid)

    def test_weight_above_slot_count_is_clamped(self):
        env = dict(self.env, HEAVY_JOB_SLOTS='2')
        out = subprocess.run([sys.executable, SCRIPT, 'run', '--weight', '5', '--', 'sh', '-c',
                              'echo "$HEAVY_JOB_SLOT"'], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), '0,1')
        self.assertIn('peso 5', out.stderr)
        self.assertIn('2 huecos', out.stderr)

    def test_invalid_weight_is_a_usage_error(self):
        for value in ('0', '-1', 'x', '1.5'):
            with self.subTest(value=value):
                self.assertEqual(self.hj('run', '--weight', value, '--', 'true').returncode, 2)


class ScanTest(SlotTestCase):
    scan = '1'

    def start_fake_pytest(self, env):
        proc = subprocess.Popen(['bash', '-c', 'exec -a pytest sleep 20'], env=env, start_new_session=True)
        self.procs.append(proc)
        time.sleep(0.3)
        return proc

    def scan_pids(self):
        out = self.hj('scan', '--json')
        self.assertEqual(out.returncode, 0, out.stderr)
        return {item['pid']: item for item in json.loads(out.stdout)}

    def test_unwrapped_heavy_process_is_reported(self):
        proc = self.start_fake_pytest(self.env)
        found = self.scan_pids()
        self.assertIn(proc.pid, found)
        self.assertEqual(found[proc.pid]['kind'], 'tests')

    def test_wrapped_process_is_not_reported(self):
        env = dict(self.env, HEAVY_JOB_SLOT='1')
        proc = self.start_fake_pytest(env)
        self.assertNotIn(proc.pid, self.scan_pids())

    def test_unwrapped_job_counts_against_slots(self):
        self.start_fake_pytest(self.env)
        blocked = self.hj('run', '--no-wait', '--', 'true')
        self.assertEqual(blocked.returncode, 75)
        self.assertIn('sin envolver', blocked.stderr)
        status = self.status()
        self.assertEqual(status['free_effective'], 0)
        self.assertTrue(any(item['kind'] == 'tests' for item in status['unwrapped']))
        free = subprocess.run([sys.executable, SCRIPT, 'run', '--no-wait', '--', 'true'], capture_output=True,
                              text=True, env=dict(self.env, HEAVY_JOB_SCAN='0'))
        self.assertEqual(free.returncode, 0, free.stderr)

    def start_fake_emulator(self, cwd, env=None):
        proc = subprocess.Popen(['bash', '-c', 'exec -a emulator python3 -c "import time; time.sleep(30)" -avd t -port 5599'],
                                env=env or self.env, cwd=cwd, start_new_session=True)
        self.procs.append(proc)
        time.sleep(0.4)
        return proc

    def test_emulator_in_the_folder_of_a_slot_holder_is_its_own_not_a_second_job(self):
        # an emulator restarted by hand next to a smoke job that held a slot and used it was counted
        # twice; the free slot looked taken and the queue (a pre-production deploy first) stalled.
        work = tempfile.mkdtemp(prefix='hj-cover-', dir=self.dir)
        other = tempfile.mkdtemp(prefix='hj-other-', dir=self.dir)
        env2 = dict(self.env, HEAVY_JOB_SLOTS='2')
        holder = subprocess.Popen([sys.executable, SCRIPT, 'run', '--kind', 'e2e', '--label', 'smoke', '--', 'sleep', '30'],
                                  env=env2, cwd=work, start_new_session=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        self.procs.append(holder)
        self.wait_for_json(0)
        mine = self.start_fake_emulator(work, env2)
        stranger = self.start_fake_emulator(other, env2)
        out = subprocess.run([sys.executable, SCRIPT, 'status', '--json'], capture_output=True, text=True, env=env2)
        status = json.loads(out.stdout)
        items = {u['pid']: u for u in status['unwrapped']}
        self.assertEqual(items[mine.pid].get('covered_by'), 0, items.get(mine.pid))
        self.assertNotIn('covered_by', items[stranger.pid])
        held = sum(1 for slot in status['slots'] if slot['held'])
        counted = sum(1 for u in status['unwrapped'] if 'covered_by' not in u and u.get('pool', 'cpu') == 'cpu')
        self.assertEqual(status['free_effective'], max(0, 2 - held - counted))
        text = subprocess.run([sys.executable, SCRIPT, 'status'], capture_output=True, text=True, env=env2).stdout
        self.assertIn('no ocupa otro hueco', text)

    def test_only_top_most_process_of_a_tree_counts(self):
        env = self.env
        # pytest (bash) -> forks -> pytest (sleep): both match, only the parent is a job of its own
        parent = subprocess.Popen(['bash', '-c', 'exec -a pytest bash -c "(exec -a pytest sleep 20) & wait"'],
                                  env=env, start_new_session=True)
        self.procs.append(parent)
        time.sleep(0.5)
        children = [int(n) for n in os.listdir('/proc') if n.isdigit() and HJ._parent_pid(int(n)) == parent.pid]
        self.assertTrue(children, 'the fake job has no child process')
        found = self.scan_pids()
        self.assertIn(parent.pid, found)
        for child in children:
            self.assertNotIn(child, found)

    def test_wrapped_job_is_not_double_counted(self):
        # a real wrapped job: slot held, nothing "unwrapped" for it. The job is launched with the scan off so that
        # heavy processes the machine happens to run (a real orphaned worker, say) cannot keep it waiting, and
        # the assertion looks only at this job's own process tree for the same reason.
        job = self.spawn('run', '--', 'bash', '-c', 'exec -a pytest sleep 20', env=dict(self.env, HEAVY_JOB_SCAN='0'))
        info = self.wait_for_json()
        time.sleep(0.3)
        status = self.status()
        mine = {job.pid, info['pid']}
        self.assertEqual([item for item in status['unwrapped'] if mine & {item['pid'], item['ppid']}], [])
        self.assertTrue(status['slots'][0]['held'])

    def start_fake_model(self, with_lib=True):
        """A python process of ~80 MiB RSS that maps a file called .../torch/lib/libtorch_cpu.so."""
        base = tempfile.mkdtemp(prefix='ml-test-')
        self.addCleanup(shutil.rmtree, base, True)
        lib_dir = os.path.join(base, 'torch', 'lib' if with_lib else 'other')
        os.makedirs(lib_dir)
        lib = os.path.join(lib_dir, 'libtorch_cpu.so' if with_lib else 'libplain.so')
        with open(lib, 'wb') as handle:
            handle.write(b'\0' * 8192)
        code = ('import mmap, time\n'
                f'f = open({lib!r}, "rb")\n'
                'm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)\n'
                'm[0]\n'
                'data = bytearray(b"x" * (80 << 20))\n'
                'time.sleep(120)\n')
        env = dict(self.env, HEAVY_JOB_ML_MIN_RSS_MIB='50')
        proc = subprocess.Popen([sys.executable, '-c', code], env=env, start_new_session=True)
        self.procs.append(proc)
        time.sleep(0.8)
        return proc

    def test_big_process_with_ml_runtime_counts_as_one_ml_job(self):
        proc = self.start_fake_model()
        out = self.hj('scan', '--json')
        found = {item['pid']: item for item in json.loads(out.stdout)}
        self.assertNotIn(proc.pid, found)  # the default threshold (1.5 GiB) is far above 80 MiB
        self.env['HEAVY_JOB_ML_MIN_RSS_MIB'] = '50'
        found = {item['pid']: item for item in json.loads(self.hj('scan', '--json').stdout)}
        self.assertEqual(found[proc.pid]['kind'], 'ml')
        self.assertFalse(found[proc.pid].get('orphan'))
        blocked = self.hj('run', '--no-wait', '--', 'true')  # one slot, taken by the unwrapped model
        self.assertEqual(blocked.returncode, 75)
        self.assertIn('[ml]', blocked.stderr)
        status = self.status()
        self.assertEqual(status['free_effective'], 0)  # weight 1: it takes one slot, not two

    def test_ml_scan_ignores_big_processes_without_ml_libraries(self):
        proc = self.start_fake_model(with_lib=False)
        self.env['HEAVY_JOB_ML_MIN_RSS_MIB'] = '50'
        found = {item['pid'] for item in json.loads(self.hj('scan', '--json').stdout)}
        self.assertNotIn(proc.pid, found)

    def test_orphaned_test_worker_is_reported_and_blocks_a_slot(self):
        base = tempfile.mkdtemp(prefix='orphan-test-')  # the scan skips paths that mention heavy-job
        self.addCleanup(shutil.rmtree, base, True)
        worker_dir = os.path.join(base, 'node_modules', 'vitest', 'dist', 'workers')
        os.makedirs(worker_dir)
        worker = os.path.join(worker_dir, 'forks.js')
        with open(worker, 'w') as handle:
            handle.write('import time\ntime.sleep(120)\n')  # python script with a .js name
        pid_file = os.path.join(base, 'pid')
        launcher = (
            'import os, sys\n'
            'if os.fork() == 0:\n'
            '    os.setsid()\n'
            '    if os.fork() == 0:\n'
            f'        open({pid_file!r}, "w").write(str(os.getpid()))\n'
            f'        os.execv(sys.executable, [sys.executable, {worker!r}])\n'
            '    os._exit(0)\n'
            'os.wait()\n')
        subprocess.run([sys.executable, '-c', launcher], env=self.env, check=True, timeout=10)
        for _ in range(50):
            if os.path.exists(pid_file) and os.path.getsize(pid_file):
                break
            time.sleep(0.1)
        with open(pid_file) as handle:
            pid = int(handle.read())
        self.addCleanup(self.kill_quietly, pid)
        time.sleep(0.3)
        found = self.scan_pids()
        self.assertIn(pid, found)
        item = found[pid]
        self.assertTrue(item['orphan'])
        self.assertEqual(item['kind'], 'tests')
        self.assertIn(pid, item['pids'])
        self.assertGreater(item['rss_kib'], 0)
        self.assertIsNotNone(item['cpu_pct'])
        text = self.hj('scan').stdout
        self.assertIn('HUÉRFANO', text)
        self.assertIn(f'kill {pid}', text)
        blocked = self.hj('run', '--no-wait', '--', 'true')
        self.assertEqual(blocked.returncode, 75)
        self.assertIn('HUÉRFANO', blocked.stderr)
        self.assertIn('nadie recoge', blocked.stderr.lower())
        self.assertIn(f'kill {pid}', blocked.stderr)
        status = self.hj('status').stdout
        self.assertIn('HUÉRFANO', status)

    @staticmethod
    def kill_quietly(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

class QueueTest(SlotTestCase):
    """First come, first served: a waiting job is never overtaken by one that arrived later."""
    slots = '2'

    def queue_dir(self):
        return os.path.join(self.dir, 'queue')

    @staticmethod
    def read(path):
        with open(path) as handle:
            return handle.read()

    def wait_registered(self, proc=None):
        """Give a freshly spawned waiter time to start and take its place in the queue."""
        time.sleep(1.0)
        if proc is not None:
            self.assertIsNone(proc.poll(), 'the waiter ended instead of waiting')

    def stamp_script(self, path):
        """A job that writes `<start> <end>` (epoch seconds) to `path` after running for a moment."""
        return ('import time; a = time.time(); time.sleep(0.5); '
                f'open({path!r}, "w").write(f"{{a}} {{time.time()}}")')

    def test_weight_two_waiter_is_not_overtaken_by_a_later_weight_one(self):
        holder = self.spawn('run', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        big_file = os.path.join(self.dir, 'big')
        late_file = os.path.join(self.dir, 'late')
        big = self.spawn('run', '--kind', 'ml', '--label', 'big', '--', sys.executable, '-c',
                         self.stamp_script(big_file))
        self.wait_registered(big)
        late = self.spawn('run', '--label', 'late', '--', sys.executable, '-c', self.stamp_script(late_file))
        time.sleep(1.5)  # one slot is free the whole time, and it is not for the later job
        self.assertIsNone(late.poll())
        self.assertFalse(os.path.exists(late_file), 'the later weight-1 job overtook the waiting weight-2 job')
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'slot-1.json')))
        os.killpg(holder.pid, signal.SIGTERM)  # the second slot frees up: the weight-2 job goes first
        big.wait(timeout=20)
        late.wait(timeout=20)
        big_start, big_end = map(float, self.read(big_file).split())
        late_start, _late_end = map(float, self.read(late_file).split())
        self.assertLess(big_start, late_start)
        self.assertGreaterEqual(late_start, big_end - 0.01)  # it needed the slots the big job held

    def test_waiters_start_in_arrival_order(self):
        holder = self.spawn('run', '--weight', '2', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        order_file = os.path.join(self.dir, 'order')
        waiters = []
        for label in ('w1', 'w2', 'w3', 'w4'):
            waiters.append(self.spawn('run', '--label', label, '--', 'sh', '-c', f'echo {label} >> {order_file}'))
            time.sleep(0.4)
        os.killpg(holder.pid, signal.SIGTERM)
        for proc in waiters:
            proc.wait(timeout=30)
        self.assertEqual(self.read(order_file).split(), ['w1', 'w2', 'w3', 'w4'])

    def test_no_wait_exits_75_when_an_older_waiter_exists(self):
        self.spawn('run', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        big = self.spawn('run', '--weight', '2', '--label', 'big-waiter', '--', 'true')
        self.wait_registered(big)
        result = self.hj('run', '--no-wait', '--', 'true')  # slot 1 is free, but the weight-2 job was first
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn('big-waiter', result.stderr)
        self.assertIn('esper', result.stderr)

    def test_no_wait_still_runs_when_nobody_waits_and_there_is_room(self):
        self.spawn('run', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        self.assertEqual(self.hj('run', '--no-wait', '--', 'true').returncode, 0)

    def test_dead_tickets_are_pruned_and_never_block(self):
        os.makedirs(self.queue_dir())
        ghost = os.path.join(self.queue_dir(), '00000000000000000001-999999.ticket')
        with open(ghost, 'w') as handle:
            json.dump({'pid': 999999, 'weight': 2, 'label': 'ghost'}, handle)  # nobody holds its lock: dead
        result = self.hj('run', '--no-wait', '--weight', '1', '--', 'true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(ghost), 'the ticket of a dead waiter was not pruned')

    def test_waiter_killed_with_sigkill_does_not_block_the_queue(self):
        holder = self.spawn('run', '--weight', '2', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        doomed = self.spawn('run', '--weight', '2', '--label', 'doomed', '--', 'true')
        self.wait_registered(doomed)
        survivor = self.spawn('run', '--label', 'survivor', '--', 'true')
        self.wait_registered(survivor)
        os.kill(doomed.pid, signal.SIGKILL)
        doomed.wait()
        os.killpg(holder.pid, signal.SIGTERM)
        self.assertEqual(survivor.wait(timeout=20), 0)

    def test_status_shows_the_queue_in_order(self):
        self.spawn('run', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        first = self.spawn('run', '--weight', '2', '--label', 'first-in-line', '--', 'true')
        self.wait_registered(first)
        second = self.spawn('run', '--label', 'second-in-line', '--', 'true')
        self.wait_registered(second)
        status = self.status()
        self.assertEqual([item['label'] for item in status['queue']], ['first-in-line', 'second-in-line'])
        self.assertEqual([item['position'] for item in status['queue']], [1, 2])
        self.assertEqual(status['queue'][0]['weight'], 2)
        self.assertEqual(status['queue'][0]['pid'], first.pid)
        self.assertFalse(status['admission']['admitted'])
        self.assertEqual(status['admission']['reason'], 'queue')
        text = self.hj('status').stdout
        self.assertLess(text.index('first-in-line'), text.index('second-in-line'))

    def test_status_without_waiters_has_an_empty_queue(self):
        status = self.status()
        self.assertEqual(status['queue'], [])
        self.assertTrue(status['admission']['admitted'])

    def test_waiter_that_gives_up_leaves_the_queue(self):
        self.spawn('run', '--weight', '2', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        result = self.hj('run', '--max-wait', '1', '--label', 'impatient', '--', 'true')
        self.assertEqual(result.returncode, 75)
        self.assertEqual(self.status()['queue'], [])
        leftovers = [name for name in os.listdir(self.queue_dir())] if os.path.isdir(self.queue_dir()) else []
        self.assertEqual(leftovers, [])

    def test_hold_also_waits_its_turn(self):
        holder = self.spawn('run', '--label', 'holder', '--', 'sleep', '30')
        self.wait_for_json(0)
        big = self.spawn('hold', '--weight', '2', '--label', 'big-hold', '--', 'sleep', '30')
        self.wait_registered(big)
        late = self.spawn('run', '--label', 'late', '--', 'sleep', '30')
        time.sleep(1.5)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'slot-1.json')))
        os.killpg(holder.pid, signal.SIGTERM)
        info = self.wait_for_json(1)
        self.assertEqual((info['label'], info['weight']), ('big-hold', 2))
        self.assertIsNone(late.poll())


class PoolRoutingTest(unittest.TestCase):
    """Which pool a job takes: the command decides, the declared kind only for opaque commands."""

    CASES = [
        # (argv, declared kind, pool)
        (['npm', 'ci'], 'install', 'light'),
        (['npm', 'ci'], None, 'light'),
        (['npm', 'ci'], 'gate', 'light'),
        (['bash', '-lc', 'cd /home/user/frontend && npx tsc -b'], 'gate', 'light'),
        (['bash', '-lc', 'cd /home/user/frontend && npx tsc -b; echo tsc-exit=$?'], 'gate', 'light'),
        (['bash', '-lc', 'cd /home/user/frontend && npx tsc -b 2>&1 | head -40'], 'gate', 'light'),
        (['bash', '-c', 'npm ci 2>&1 | tail -5 | grep -v warn'], None, 'light'),
        (['bash', '-c', 'ls src | xargs npx tsc'], 'typecheck', 'light'),
        (['bash', '-c', 'ls src | xargs npx tsc'], 'gate', 'cpu'),
        (['npx', 'eslint', 'src'], None, 'light'),
        (['npm', 'run', 'lint'], 'gate', 'light'),
        (['pnpm', 'typecheck'], None, 'light'),
        (['make', 'typecheck'], None, 'light'),
        (['vendor/bin/phpstan', 'analyse'], 'gate', 'cpu'),     # parallel workers on every core: not light
        (['bash', '-c', 'npm ci && npx tsc -b'], None, 'light'),
        # anything that compiles apps or runs tests stays in the cpu pool, whatever --kind says
        (['tools/worktree-slot.sh', 'make', 'ci'], 'gate', 'cpu'),
        (['make', 'check'], 'lint', 'cpu'),
        (['bash', '-c', 'npm ci && npm test'], 'install', 'cpu'),
        (['./gradlew', 'assembleDebug'], 'install', 'cpu'),
        (['bash', '-c', 'npx tsc -b && npx vitest run'], 'typecheck', 'cpu'),
        (['emulator', '-avd', 'pixel'], 'light', 'cpu'),
        # opaque commands: light only when the caller declares a light kind
        (['bash', '/tmp/scratch/job4.sh'], 'e2e', 'cpu'),
        (['bash', '/tmp/scratch/trr-gates.sh', '/w'], 'gate', 'cpu'),
        (['bash', '/tmp/scratch/release.sh'], 'suite', 'cpu'),
        (['bash', '/tmp/scratch/deps.sh'], None, 'cpu'),
        (['bash', '/tmp/scratch/deps.sh'], 'install', 'light'),
        (['bash', '/tmp/scratch/whatever.sh'], 'light', 'light'),
        (['sh', '-c', 'echo hi'], None, 'cpu'),
        (['npx', 'tsc', '-b', '--watch'], None, 'light'),
        (['python3', '-c', 'print(1)'], 'lint', 'light'),
        (['python3', '-c', 'print(1)'], None, 'cpu'),
    ]

    def test_cases(self):
        for argv, kind, pool in self.CASES:
            with self.subTest(argv=argv, kind=kind):
                self.assertEqual(HJ.pool_for(argv, kind)[0], pool)

    def test_reason_names_the_tool(self):
        pool, why = HJ.pool_for(['bash', '-lc', 'cd /x && npx tsc -b'], 'gate')
        self.assertEqual(pool, 'light')
        self.assertIn('tsc', why)
        self.assertIn('ni compila apps ni corre tests', why)
        self.assertIn('gate', HJ.pool_for(['make', 'ci'], 'lint')[1])

    def test_kind_without_declaration(self):
        self.assertEqual(HJ.light_kind_of(['npx', 'tsc', '-b']), 'typecheck')
        self.assertEqual(HJ.light_kind_of(['npm', 'run', 'typecheck']), 'typecheck')
        self.assertEqual(HJ.light_kind_of(['npx', 'eslint', '.']), 'lint')
        self.assertEqual(HJ.light_kind_of(['npm', 'ci']), 'install')
        self.assertIsNone(HJ.light_kind_of(['sh', '-c', 'echo hi']))

    def test_light_pool_config(self):
        with mock.patch.dict(os.environ, {'HEAVY_JOB_LIGHT_SLOTS': '5', 'HEAVY_JOB_LIGHT_MIN_AVAIL_GIB': '0.5',
                                          'HEAVY_JOB_LIGHT_SETTLE': '3'}):
            self.assertEqual(HJ.light_slot_count(), 5)
            self.assertEqual(HJ.light_min_avail_gib(), 0.5)
            self.assertEqual(HJ.light_settle_seconds(), 3)
        with mock.patch.dict(os.environ, {'HEAVY_JOB_LIGHT_SLOTS': 'x'}):
            self.assertIn(HJ.light_slot_count(), (HJ.DEFAULT_LIGHT_SLOTS,
                                                  int(HJ._config_number('-', 'light-slots', -1))))

    def test_cli_classify_says_the_pool(self):
        out = subprocess.run([sys.executable, SCRIPT, 'classify', '--json', '--', 'npm ci'], capture_output=True,
                             text=True)
        self.assertEqual(json.loads(out.stdout)['pool'], 'light')
        out = subprocess.run([sys.executable, SCRIPT, 'classify', '--', 'cd x && npx tsc -b'], capture_output=True,
                             text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn('no hace falta heavy-job', out.stdout)
        self.assertIn('resto', out.stdout)


class LightPoolTest(SlotTestCase):
    """The light pool runs beside the cpu pool: own slots, own queue, shared memory admission."""
    slots = '1'

    def setUp(self):
        super().setUp()
        self.env.update(HEAVY_JOB_LIGHT_SLOTS='1', HEAVY_JOB_LIGHT_MIN_AVAIL_GIB='0', HEAVY_JOB_LIGHT_SETTLE='0')
        self.bin = tempfile.mkdtemp(prefix='heavy-job-bin-')
        self.addCleanup(shutil.rmtree, self.bin, True)
        tsc = os.path.join(self.bin, 'tsc')       # a stand-in for TypeScript: prints what it got and sleeps
        with open(tsc, 'w') as handle:
            handle.write('#!/bin/sh\necho "light=${HEAVY_JOB_LIGHT_SLOT:-} cpu=${HEAVY_JOB_SLOT:-} '
                         'pool=${HEAVY_JOB_POOL:-}"\nsleep "${TSC_SLEEP:-0}"\n')
        os.chmod(tsc, 0o755)
        self.env['PATH'] = self.bin + os.pathsep + self.env['PATH']

    def wait_for_light_json(self, slot=0, timeout=10):
        path = os.path.join(self.dir, 'light', f'slot-{slot}.json')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with open(path) as handle:
                    return json.load(handle)
            except (OSError, ValueError):
                time.sleep(0.05)
        self.fail(f'{path} never appeared')

    def test_light_job_runs_while_cpu_pool_is_full_and_queued(self):
        self.spawn('run', '--label', 'suite', '--', 'sleep', '30')
        self.wait_for_json(0)
        waiter = self.spawn('run', '--label', 'second suite', '--', 'true')    # queued in the cpu pool
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self.status()['queue']:
            time.sleep(0.1)
        self.assertEqual(len(self.status()['queue']), 1)
        started = time.monotonic()
        out = self.hj('run', '--kind', 'gate', '--label', 'tsc', '--', 'tsc', '-b')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn('light=1 cpu= pool=light', out.stdout)     # shown as slot 1: after the single cpu slot
        self.assertIn('aunque diga --kind gate', out.stderr)
        self.assertIsNone(waiter.poll())

    def test_light_queue_is_its_own_fifo(self):
        holder = self.spawn('run', '--', 'tsc', '-b', env=dict(self.env, TSC_SLEEP='30'))
        info = self.wait_for_light_json(0)
        self.assertEqual((info['pool'], info['shown_slots'], info['kind']), ('light', [1], 'typecheck'))
        blocked = self.hj('run', '--no-wait', '--kind', 'install', '--', 'true')
        self.assertEqual(blocked.returncode, 75)
        self.assertIn('compilar', self.hj('status').stdout)
        free_cpu = self.hj('run', '--no-wait', '--', 'true')      # the cpu pool is untouched
        self.assertEqual(free_cpu.returncode, 0, free_cpu.stderr)
        holder.kill()

    def test_status_shows_both_pools(self):
        self.spawn('run', '--label', 'deps', '--kind', 'install', '--', 'sleep', '30')
        self.wait_for_light_json(0)
        data = self.status()
        self.assertEqual(data['slot_count'], 1)
        self.assertFalse(data['slots'][0]['held'])
        self.assertEqual(data['light']['slot_count'], 1)
        self.assertTrue(data['light']['slots'][0]['held'])
        self.assertEqual(data['light']['slots'][0]['holder']['label'], 'deps')
        self.assertEqual(data['light']['free_effective'], 0)
        self.assertFalse(data['light']['admission']['admitted'])
        self.assertTrue(data['admission']['admitted'])
        text = self.hj('status').stdout
        self.assertIn('hueco 1 (resto): OCUPADO por', text)
        self.assertIn('Huecos del resto: 1', text)
        self.assertIn('Un trabajo del resto de peso 1 ahora: NO se admitiría', text)
        self.assertIn('Un trabajo de peso 1 ahora: se admitiría', text)

    def test_memory_rule_counts_the_other_pool(self):
        path = os.path.join(self.dir, 'meminfo')
        with open(path, 'w') as handle:
            handle.write(f'MemTotal: 15000000 kB\nMemAvailable: {1048576} kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n')
        self.env.update(HEAVY_JOB_MEMINFO=path, HEAVY_JOB_LIGHT_MIN_AVAIL_GIB='1.5', HEAVY_JOB_MIN_AVAIL_GIB='2.5')
        alone = self.hj('run', '--no-wait', '--kind', 'install', '--', 'true')   # nothing else runs: admitted
        self.assertEqual(alone.returncode, 0, alone.stderr)
        self.spawn('run', '--label', 'suite', '--', 'sleep', '30')                  # a cpu job now runs
        self.wait_for_json(0)
        blocked = self.hj('run', '--no-wait', '--kind', 'install', '--', 'true')
        self.assertEqual(blocked.returncode, 75)
        self.assertIn('memoria disponible 1.0 GiB', blocked.stderr)
        self.assertIn('1.5 GiB', blocked.stderr)

    def test_light_jobs_never_hold_back_the_cpu_queue(self):
        """A running light job is not "another heavy job" for a cpu job: no memory rule, no settle."""
        path = os.path.join(self.dir, 'meminfo')
        with open(path, 'w') as handle:
            handle.write(f'MemTotal: 15000000 kB\nMemAvailable: {1048576} kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n')
        self.env.update(HEAVY_JOB_MEMINFO=path, HEAVY_JOB_MIN_AVAIL_GIB='2.5', HEAVY_JOB_SETTLE='30')
        self.spawn('run', '--label', 'deps', '--kind', 'install', '--', 'sleep', '30')
        self.wait_for_light_json(0)
        heavy = self.hj('run', '--no-wait', '--weight', '1', '--', 'true')
        self.assertEqual(heavy.returncode, 0, heavy.stderr)
        self.assertTrue(self.status()['admission']['admitted'])

    def test_settle_counts_the_other_pool(self):
        self.env['HEAVY_JOB_LIGHT_SETTLE'] = '30'
        self.spawn('run', '--label', 'suite', '--', 'sleep', '30')
        self.wait_for_json(0)
        blocked = self.hj('run', '--no-wait', '--kind', 'install', '--', 'true')
        self.assertEqual(blocked.returncode, 75)
        self.assertIn('pausa de 30 s', blocked.stderr)

    def test_light_pool_off_sends_everything_to_cpu(self):
        self.env['HEAVY_JOB_LIGHT_SLOTS'] = '0'
        out = self.hj('run', '--kind', 'install', '--', 'tsc')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('light= cpu=0 pool=cpu', out.stdout)
        self.assertIsNone(self.status()['light'])

    def test_hold_in_light_pool(self):
        self.spawn('hold', '--kind', 'install', '--label', 'held', '--', 'sleep', '30')
        info = self.wait_for_light_json(0)
        self.assertEqual((info['pool'], info['mode']), ('light', 'hold'))
        deadline = time.monotonic() + 5
        environ = []
        while time.monotonic() < deadline:      # the json is written just before the exec
            with open(f'/proc/{info["pid"]}/environ', 'rb') as handle:
                environ = handle.read().split(b'\0')
            with open(f'/proc/{info["pid"]}/comm') as handle:
                if handle.read().strip() == 'sleep' and len(environ) > 1:
                    break
            time.sleep(0.05)
        self.assertIn(b'HEAVY_JOB_LIGHT_SLOT=1', environ)
        self.assertFalse(any(item.startswith(b'HEAVY_JOB_SLOT=') for item in environ))


class LightPoolScanTest(SlotTestCase):
    scan = '1'

    def start_fake(self, name, args, env):
        """A shell script called `name`, run as `sh <dir>/<name> <args>`: the scan sees `<name> <args>`."""
        base = tempfile.mkdtemp(prefix='hj-fake-')  # a path with `heavy-job` in it is skipped by the scan
        self.addCleanup(shutil.rmtree, base, True)
        path = os.path.join(base, name)
        with open(path, 'w') as handle:
            handle.write('sleep 20\n')
        proc = subprocess.Popen(['sh', path, *args], env=env, start_new_session=True)
        self.procs.append(proc)
        time.sleep(0.4)
        return proc

    def scan_pids(self):
        out = self.hj('scan', '--json')
        self.assertEqual(out.returncode, 0, out.stderr)
        return {item['pid']: item for item in json.loads(out.stdout)}

    def test_light_slot_covers_an_install_but_not_a_suite(self):
        env = dict(self.env, HEAVY_JOB_LIGHT_SLOT='1')
        install = self.start_fake('npm', ['ci'], env)
        suite = self.start_fake('pytest', ['no-such-dir'], env)   # uninspectable target: a suite
        found = self.scan_pids()
        self.assertNotIn(install.pid, found)
        self.assertIn(suite.pid, found)
        self.assertEqual(found[suite.pid]['kind'], 'tests')

    def test_unwrapped_install_takes_a_light_slot_not_a_cpu_one(self):
        self.env['HEAVY_JOB_LIGHT_SLOTS'] = '1'
        self.start_fake('npm', ['ci'], self.env)
        status = self.status()
        self.assertEqual(status['free_effective'], 1)
        self.assertEqual(status['light']['free_effective'], 0)
        self.assertTrue(any(u['pool'] == 'light' for u in status['unwrapped']))


class PausedProjectPriorityTest(unittest.TestCase):
    """A job of a project the developer paused waits behind every job of an active project."""

    def ahead(self, mine_cwd, mine_ts, items):
        queue = [{'ts': ts, 'pid': 100 + i, 'path': f'/q/{i}', 'info': {'cwd': cwd}}
                 for i, (cwd, ts) in enumerate(items)]
        queue.append({'ts': mine_ts, 'pid': os.getpid(), 'path': '/q/me', 'info': {'cwd': mine_cwd}})
        ticket = {'path': '/q/me', 'ts': mine_ts, 'info': {'cwd': mine_cwd}, 'fd': -1}
        with mock.patch.object(HJ, 'read_queue', return_value=queue), \
                mock.patch.object(HJ, 'paused_cwd', side_effect=lambda cwd: str(cwd).startswith('/paused')):
            return sorted(item['info']['cwd'] for item in HJ.waiters_ahead('/x', ticket))

    def test_an_active_job_goes_before_earlier_paused_jobs(self):
        self.assertEqual(self.ahead('/active/b', 50, [('/paused/a', 10), ('/active/a', 20)]), ['/active/a'])

    def test_a_paused_job_waits_for_later_active_jobs(self):
        self.assertEqual(self.ahead('/paused/b', 50, [('/paused/a', 10), ('/active/a', 90), ('/paused/c', 99)]),
                         ['/active/a', '/paused/a'])

    def test_without_pauses_it_is_first_come_first_served(self):
        self.assertEqual(self.ahead('/active/c', 50, [('/active/a', 10), ('/active/b', 90)]), ['/active/a'])

    def test_paused_cwd_is_false_for_an_unpaused_or_empty_path(self):
        self.assertFalse(HJ.paused_cwd(''))
        self.assertFalse(HJ.paused_cwd(tempfile.gettempdir()))

    def test_status_lists_the_queue_in_turn_order_and_marks_paused_jobs(self):
        queue = [{'position': n, 'pid': 100 + n, 'info': {'cwd': cwd, 'label': cwd}}
                 for n, cwd in enumerate(['/paused/a', '/active/a', '/paused/b', '/active/b'], 1)]
        with mock.patch.object(HJ, 'paused_cwd', side_effect=lambda cwd: str(cwd).startswith('/paused')):
            entries = HJ.queue_in_turn_order(queue)
        self.assertEqual([(e['position'], e['label']) for e in entries],
                         [(1, '/active/a'), (2, '/active/b'), (3, '/paused/a'), (4, '/paused/b')])
        self.assertIn('proyecto en pausa', HJ.queue_line(entries[2]))
        self.assertNotIn('pausa', HJ.queue_line(entries[0]))


if __name__ == '__main__':
    unittest.main()
