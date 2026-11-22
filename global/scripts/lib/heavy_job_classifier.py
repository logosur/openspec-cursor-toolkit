"""Classifier of heavy development commands, shared by heavy-job and heavy-job-gate.

Is this command line heavy, of which kind, and which pool does it take? It only reads the command and, to count the
test files a runner targets, the directory named in it: no state, no /proc, no config.
"""
import fnmatch
import glob
import os
import re
import shlex

MAX_DEPTH = 8
# Two pools (see "Pools" in the heavy-job docstring). The cpu pool keeps the historical files.
CPU_POOL = 'cpu'
LIGHT_POOL = 'light'
LIGHT_KINDS = {'install', 'typecheck', 'lint', 'light'}
# Single-process (or very fast) tools only. phpstan and psalm spawn parallel workers on every core by default and
# were not measured, so they stay in the cpu pool.
TYPECHECK_TOOLS = {'tsc', 'vue-tsc', 'tsgo', 'mypy', 'pyright'}
LIGHT_TOOLS = TYPECHECK_TOOLS | {'eslint', 'prettier', 'stylelint', 'biome', 'oxlint', 'phpcs', 'phpcbf',
                                 'php-cs-fixer', 'ruff', 'flake8', 'pylint', 'black', 'isort', 'shellcheck'}
LIGHT_SCRIPT_RE = re.compile(r'^(typecheck|type-check|types|tsc|lint|lint:[a-z0-9:-]+|format|format:check|'
                             r'prettier|eslint|stylelint)$')
LIGHT_MAKE_RE = re.compile(r'^(lint|lint-[a-z0-9-]+|typecheck|type-check|types|format|fmt)$')
# Simple commands that do nothing heavy by themselves: `bash -lc "cd x && npx tsc -b 2>&1 | head -40; echo rc=$?"`
# is still tsc. Text filters count (`tsc ... | head -40` is a light job); programs that
# run other programs (xargs, find -exec, interpreters) do not.
TRIVIAL_PROGS = {'cd', 'echo', 'printf', 'true', 'false', ':', 'test', '[', '[[', 'export', 'set', 'exit',
                 'pwd', 'date', 'tee', 'head', 'tail', 'grep', 'egrep', 'fgrep', 'rg', 'sed', 'awk', 'cat', 'wc',
                 'sort', 'uniq', 'cut', 'tr', 'column'}


# --------------------------------------------------------------------------------------------------------
# Classifier (pure functions, no I/O)
# --------------------------------------------------------------------------------------------------------

PUNCT = set('();<>|&')
ASSIGN_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=')
KEYWORDS = {'then', 'do', 'else', 'elif', 'if', 'while', 'until', '!', '{', '}', 'fi', 'done'}
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ash'}
SCRIPT_EXTS = ('.js', '.mjs', '.cjs', '.py', '.phar')
KNOWN_TOOLS = {'npm', 'npx', 'yarn', 'pnpm', 'pnpx', 'jest', 'vitest', 'playwright', 'pytest', 'py.test',
               'phpunit', 'gradle', 'gradlew', 'heavy-job'}
TEST_SCRIPT_RE = re.compile(r'^(test|e2e|ci)(:|$)')
NOT_HEAVY_SCRIPTS = {'test:plan', 'test:selector'}
MAKE_HEAVY_RE = re.compile(r'^(ci|ci-checks|check|test|smoke|test-[a-z0-9-]+|[a-z0-9-]*e2e[a-z0-9-]*'
                           r'|app-android-(build|test)|pwa-e2e)$')
MAKE_NOT_HEAVY = {'test-plan', 'test-group', 'test-phpunit-filter', 'test-lock-status'}
# video renders (browser frames piped to ffmpeg) take several cores
MAKE_RENDER_RE = re.compile(r'^(videos?|renders?|videos?-(render|all|build)|render-videos?)$')
FFMPEG_INFO_OPTS = {'-version', '--version', '-h', '-help', '--help', '-formats', '-codecs', '-encoders', '-decoders',
                    '-filters', '-protocols', '-buildconf', '-pix_fmts', '-devices', '-muxers', '-demuxers'}
FFMPEG_VIDEO_OPTS = {'-vcodec', '-vf', '-filter:v', '-filter_complex', '-lavfi', '-r', '-s', '-pix_fmt', '-crf',
                     '-preset', '-b:v', '-framerate'}
FFMPEG_VALUE_OPTS = {'-i', '-f', '-c', '-codec', '-c:a', '-codec:a', '-acodec', '-b:a', '-ar', '-ac', '-t', '-ss',
                     '-to', '-map', '-metadata', '-loglevel', '-v', '-threads', '-movflags', '-af', '-filter:a',
                     '-vcodec', '-vf', '-filter:v', '-filter_complex', '-lavfi', '-r', '-s', '-pix_fmt', '-crf',
                     '-preset', '-b:v', '-framerate', '-c:v', '-codec:v', '-frames:v', '-vframes', '-frames'}
VIDEO_EXTS = ('.mp4', '.webm', '.mov', '.mkv', '.avi', '.gif', '.m4v', '.ts')
MAKE_NOT_HEAVY_SUFFIX = ('-status', '-list', '-selftest')
GRADLE_MAINS = ('org.gradle.wrapper.GradleWrapperMain', 'org.gradle.launcher.GradleMain')
GRADLE_VALUE_OPTS = {'-p', '--project-dir', '-g', '--gradle-user-dir', '-b', '--build-file', '-c',
                     '--settings-file', '-I', '--init-script', '-x', '--exclude-task', '--max-workers',
                     '--include-build', '--console', '--warning-mode'}
NPM_VALUE_OPTS = {'--prefix', '-C', '--workspace', '-w', '--registry', '--cache', '--userconfig', '--loglevel',
                  '--filter', '-F', '--dir', '--cwd'}
PM_EXEC_VALUE_OPTS = {'-p', '--package', '--registry', '--cache', '--userconfig', '-w', '--workspace', '--prefix',
                      '--from', '--with', '--python'}
JEST_VALUE_OPTS = {'--config', '-c', '--rootDir', '--roots', '--project', '--reporters', '--reporter',
                   '--outputFile', '--root', '-r'}
PATH_EXTS = ('.ts', '.tsx', '.js', '.mjs')
# A runner that targets a few test files is light.
# Filters narrow a run to a subset; --collect-only and friends execute nothing.
PYTEST_VALUE_OPTS = {'-p', '-c', '-o', '-m', '-n', '--rootdir', '--maxfail', '--tb', '--junitxml', '--cov',
                     '--cov-report', '--durations', '--basetemp', '--import-mode', '--log-level', '-W', '--ignore',
                     '--ignore-glob', '--deselect', '--confcutdir', '--override-ini', '--color', '--rootdir',
                     '--durations-min', '--cache-dir', '--timeout', '--dist', '--numprocesses', '--reruns'}
PYTEST_NO_RUN_OPTS = {'--version', '--help', '-h', '--collect-only', '--co', '--fixtures', '--markers',
                      '--setup-plan', '--fixtures-per-test'}
PHPUNIT_VALUE_OPTS = {'-c', '--configuration', '--bootstrap', '--exclude-group', '--testsuite', '--log-junit',
                      '--log-teamcity', '--log-testdox', '--coverage-html', '--coverage-clover', '--coverage-text',
                      '--coverage-xml', '--coverage-php', '--coverage-cobertura', '--include-path', '--order-by',
                      '--cache-result-file', '--cache-directory', '--test-suffix', '--covers', '--uses',
                      '--testdox-html', '--testdox-text', '--testdox-xml', '--colors', '--random-order-seed',
                      '--stop-on-defect', '-d', '--process-isolation-bootstrap'}
PHPUNIT_FILTER_OPTS = ('--filter', '--group')
PHPUNIT_NO_RUN_OPTS = {'--version', '--help', '-h', '--list-tests', '--list-groups', '--list-suites',
                       '--list-test-files', '--list-tests-xml', '--list-test-ids', '--migrate-configuration'}
PLAYWRIGHT_VALUE_OPTS = {'-c', '--config', '--project', '--reporter', '--workers', '-j', '--retries', '--timeout',
                         '--output', '--shard', '--max-failures', '--repeat-each', '--tsconfig', '--trace',
                         '--ui-host', '--ui-port'}
JEST_FILTER_OPTS = ('-t', '--testNamePattern', '--test-name-pattern', '--findRelatedTests', '--changedSince',
                    '--onlyChanged', '-o', '--onlyFailures', '--testPathPattern', '--related')
# A directory with at most this many test files is a small run; more (or one that cannot be inspected) is a suite.
MAX_LIGHT_TEST_FILES = 5
TEST_FILE_GLOBS = ('test_*.py', '*_test.py', '*Test.php', '*.test.*', '*.spec.*')
TEST_SCAN_SKIP_DIRS = {'node_modules', 'vendor', '.git', '.venv', 'venv', '__pycache__', '.tox'}
TEST_SCAN_MAX_ENTRIES = 20000
# Shell expansions that stand for explicit targets: `for f in tests/*Test.php; do phpunit $f`,
# `phpunit $(ls tests/X/*Test.php)` (shlex leaves a lone `$`). `$1` (a function or script argument) counts too;
# `$@`, `$*` and `$#` forward whatever the caller gave, so they prove nothing.
EXPANSION_RE = re.compile(r'^(\$|\$[0-9]|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$\(.*|`.*)$')
MAKE_VALUE_OPTS = {'-C', '--directory', '-f', '--file', '--makefile', '-I', '--include-dir', '-o', '--old-file',
                   '-W', '--what-if', '-l', '--load-average'}
MAKE_DRY_LONG = {'--dry-run', '--just-print', '--recon', '--question'}
PY_RUNNER_VALUE_OPTS = {'--with', '--project', '--python', '-p', '--directory', '--extra', '--group',
                        '--env-file', '--with-requirements', '-C'}
ML_PROGS = {'whisper', 'faster-whisper', 'faster_whisper', 'whisperx', 'whisper-ctranslate2', 'torchrun',
            'torch.distributed.run', 'accelerate.commands.launch'}
DOCKER_GLOBAL_OPTS = {'--context', '-c', '-H', '--host', '--config', '-l', '--log-level', '--project-name', '-p',
                      '--file', '-f', '--profile', '--env-file', '--project-directory'}


def _base(path):
    return os.path.basename(path) if path else ''


def _positionals(args, value_opts=()):
    """Arguments that are not options (nor the values of `value_opts`); everything after `--` counts."""
    out = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--':
            out.extend(args[i + 1:])
            break
        if a.startswith('-') and a != '-':
            if a in value_opts:
                i += 1
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _skip_opts(args, value_opts=()):
    """Drop the leading options (and the values of `value_opts`) of a wrapper; stop at the first operand or `--`."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--':
            return args[i + 1:]
        if a.startswith('-') and a != '-':
            i += 2 if a in value_opts else 1
            continue
        break
    return args[i:]


def _strip_heredocs(text):
    """Remove here-document bodies, which are data and not commands (only when the terminator line exists)."""
    if '<<' not in text:
        return text
    lines = text.split('\n')
    out = []
    i = 0
    marker = re.compile(r'(?<!<)<<(?!<)-?\s*(?:\'([^\']+)\'|"([^"]+)"|\\?([A-Za-z_][A-Za-z0-9_]*))')
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        words = [next(g for g in m.groups() if g) for m in marker.finditer(line)]
        for word in words:
            j = i
            while j < len(lines) and lines[j].strip() != word:
                j += 1
            if j < len(lines):
                i = j + 1
    return '\n'.join(out)


def _prepare(text):
    """Quote-aware pre-pass: drop comments and line continuations, turn unquoted newlines into ` ; `, and drop
    the file-descriptor digit of redirections (`2>&1`), so the tokenizer sees clean simple commands."""
    out = []
    i = 0
    n = len(text)
    quote = None
    word_start = True
    while i < n:
        c = text[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
        elif quote == '"':
            out.append(c)
            if c == '\\' and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                quote = None
        else:
            if c == '\\' and i + 1 < n:
                if text[i + 1] == '\n':
                    i += 2
                    continue
                out.append(c)
                out.append(text[i + 1])
                i += 2
                word_start = False
                continue
            if c in '\'"':
                quote = c
                out.append(c)
                word_start = False
            elif c == '#' and word_start:
                while i < n and text[i] != '\n':
                    i += 1
                continue
            elif c == '\n':
                out.append(' ; ')
                word_start = True
            else:
                if c in '<>':
                    j = len(out)
                    while j > 0 and out[j - 1].isdigit():
                        j -= 1
                    if j < len(out) and (j == 0 or out[j - 1][-1] in ' \t;&|('):
                        del out[j:]
                out.append(c)
                word_start = c in ' \t;&|()'
        i += 1
    return ''.join(out)


def _split_commands(command):
    """Split a shell line into simple commands (lists of words)."""
    text = _prepare(_strip_heredocs(command))
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ''
        tokens = list(lex)
    except ValueError:
        return [part.split() for part in re.split(r'&&|\|\||[;|&\n()]', command) if part.split()]
    cmds = []
    cur = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok and all(ch in PUNCT for ch in tok):
            if '<' in tok or '>' in tok:
                skip_next = True
                continue
            if cur:
                cmds.append(cur)
                cur = []
            continue
        cur.append(tok)
    if cur:
        cmds.append(cur)
    return cmds


def _strip_leading(argv):
    """Drop leading VAR=value assignments and shell keywords (`then`, `do`, `!`...)."""
    i = 0
    while i < len(argv) and (ASSIGN_RE.match(argv[i]) or argv[i] in KEYWORDS):
        i += 1
    return argv[i:]


def _script_alias(path):
    """Map the script an interpreter runs (`node .../npm-cli.js`) to the tool name the rules know."""
    if path.endswith('e2e/run.sh'):
        return path
    stem = _base(path)
    for ext in SCRIPT_EXTS:
        if stem.endswith(ext):
            stem = stem[:-len(ext)]
            break
    if stem == 'npm-cli':
        return 'npm'
    if stem == 'npx-cli':
        return 'npx'
    if stem in KNOWN_TOOLS:
        return stem
    if stem == 'cli' and 'playwright' in path:
        return 'playwright'
    return path


def _interpreter_step(prog, args):
    """Unwrap `bash -c STR`, `python -m MOD`, `node SCRIPT`, `php SCRIPT`, `bash SCRIPT`.

    Returns ('cmd', string) / ('argv', list) / ('light',) or None when it is not an interpreter call."""
    if prog in SHELLS:
        i = 0
        while i < len(args):
            a = args[i]
            if a in ('-o', '+o', '-O', '+O', '--rcfile', '--init-file'):
                i += 2
                continue
            if a.startswith('--'):
                i += 1
                continue
            if a.startswith('-') and len(a) > 1:
                if 'c' in a[1:]:
                    return ('cmd', args[i + 1]) if i + 1 < len(args) else ('light',)
                i += 1
                continue
            return ('argv', [_script_alias(a)] + args[i + 1:])
        return ('light',)
    if re.match(r'^python[0-9.]*$', prog):
        i = 0
        while i < len(args):
            a = args[i]
            if a == '-m':
                return ('argv', args[i + 1:]) if i + 1 < len(args) else ('light',)
            if a in ('-c', '-'):
                return ('light',)
            if a in ('-W', '-X'):
                i += 2
                continue
            if a.startswith('-'):
                i += 1
                continue
            return ('argv', [_script_alias(a)] + args[i + 1:])
        return ('light',)
    if prog in ('node', 'nodejs', 'php'):
        is_php = prog == 'php'
        value_opts = {'-d', '-c', '-f'} if is_php else {'-r', '--require', '--loader', '--import',
                                                         '--experimental-loader'}
        code_opts = {'-r'} if is_php else {'-e', '-p', '--eval', '--print'}
        i = 0
        while i < len(args):
            a = args[i]
            if a in code_opts:
                return ('light',)
            if a in value_opts:
                i += 2
                continue
            if a.startswith('-') and a != '-':
                i += 1
                continue
            return ('argv', [_script_alias(a)] + args[i + 1:])
        return ('light',)
    return None


def _wrapper_step(prog, args):
    """Unwrap a program that just runs another one. Returns ('argv', list) / ('cmd', str) / ('light',) / ('hit', r)
    or None when `prog` is not a wrapper."""
    if prog == 'env':
        return ('argv', _skip_opts(args, {'-u', '--unset', '-C', '--chdir', '-S', '--split-string'}))
    if prog == 'nice':
        return ('argv', _skip_opts(args, {'-n', '--adjustment'}))
    if prog == 'ionice':
        return ('argv', _skip_opts(args, {'-c', '--class', '-n', '--classdata', '-p', '--pid', '-P', '--pgid',
                                          '-u', '--uid'}))
    if prog == 'timeout':
        return ('argv', _skip_opts(args, {'-s', '--signal', '-k', '--kill-after'})[1:])  # [0] is the duration
    if prog in ('nohup', 'setsid'):
        return ('argv', _skip_opts(args))
    if prog == 'stdbuf':
        return ('argv', _skip_opts(args, {'-i', '-o', '-e', '--input', '--output', '--error'}))
    if prog == 'xvfb-run':
        return ('argv', _skip_opts(args, {'-e', '--error-file', '-f', '--auth-file', '-n', '--server-num', '-p',
                                          '--xauth-protocol', '-s', '--server-args', '-w', '--wait'}))
    if prog == 'time':
        return ('argv', _skip_opts(args, {'-f', '--format', '-o', '--output'}))
    if prog == 'command':
        if any(a in ('-v', '-V') for a in args):
            return ('light',)
        return ('argv', _skip_opts(args))
    if prog == 'exec':
        return ('argv', _skip_opts(args, {'-a'}))
    if prog == 'sudo':
        return ('argv', _skip_opts(args, {'-u', '-g', '-h', '-p', '-C', '-D', '-R', '-T', '-U', '--user',
                                          '--group', '--host', '--prompt', '--chdir', '--chroot'}))
    if prog == 'heavy-job':
        if args and args[0] in ('run', 'hold') and '--' in args:
            return ('argv', args[args.index('--') + 1:])
        return ('light',)
    if prog in ('npx', 'pnpx', 'bunx', 'uvx'):
        if prog == 'npx' and '-c' in args:
            i = args.index('-c')
            return ('cmd', args[i + 1]) if i + 1 < len(args) else ('light',)
        return ('argv', _skip_opts(args, PM_EXEC_VALUE_OPTS))
    if prog in ('npm', 'pnpm', 'yarn', 'bun'):
        pos = _positionals(args, NPM_VALUE_OPTS)
        if pos and pos[0] in ('exec', 'x', 'dlx'):
            return ('argv', _skip_opts(args[args.index(pos[0]) + 1:], PM_EXEC_VALUE_OPTS))
        return None
    if prog in ('uv', 'poetry', 'pipenv', 'pdm', 'hatch', 'rye'):
        pos = _positionals(args, PY_RUNNER_VALUE_OPTS)
        if pos and pos[0] == 'run':
            return ('argv', _skip_opts(args[args.index('run') + 1:], PY_RUNNER_VALUE_OPTS))
        return None
    if prog == 'worktree-slot.sh':
        if args and args[0] == 'exec':
            rest = args[1:]
            return ('argv', rest[1:] if rest[:1] == ['--'] else rest)
        if args and args[0] == 'make':
            return ('argv', ['make'] + args[1:])
        return ('light',)
    if prog == 'ddev':
        pos = _positionals(args, {'-s', '--service', '-d', '--dir'})
        if pos and pos[0] == 'e2e':
            return ('hit', ('e2e', 'ddev e2e (suite e2e del proyecto)'))
        if pos and pos[0] == 'exec':
            return ('argv', _skip_opts(args[args.index('exec') + 1:], {'-s', '--service', '-d', '--dir'}))
        return ('light',)
    if prog in ('docker', 'docker-compose', 'podman'):
        return _docker_step(prog, args)
    return None


def _docker_step(prog, args):
    rest = _skip_opts(args, DOCKER_GLOBAL_OPTS)
    if prog != 'docker-compose' and rest[:1] == ['compose']:
        rest = _skip_opts(rest[1:], DOCKER_GLOBAL_OPTS)
    sub, tail = (rest[0], rest[1:]) if rest else (None, [])
    if sub == 'run':
        if any('playwright' in a.lower() for a in tail):
            return ('hit', ('e2e', 'docker run con Playwright (suite e2e)'))
        return ('light',)
    if sub == 'exec':
        operands = _skip_opts(tail, {'-e', '--env', '-u', '--user', '-w', '--workdir', '--index', '--env-file',
                                     '--detach-keys'})
        return ('argv', operands[1:])  # operands[0] is the container or service name
    return ('light',)


def _gradle_tasks(args):
    return [a for a in _positionals(args, GRADLE_VALUE_OPTS) if '=' not in a]


# Directory the commands run in, for resolving relative test paths. classify_command tracks `cd X` and the
# hook passes the session cwd; None means os.getcwd().
_CWD = None


def _is_expansion(arg):
    """True for `$f`, `${f}`, a lone `$` (the head of a split `$(...)`) or a backtick: an explicit target the
    classifier cannot see. `$@`, `$*` and `$#` are not (they forward the caller's arguments)."""
    return bool(EXPANSION_RE.match(arg))


def _resolve_path(arg):
    return os.path.join(_CWD or os.getcwd(), os.path.expanduser(arg))


def _count_test_files(directory):
    """Number of test files (TEST_FILE_GLOBS) below `directory`, skipping node_modules, vendor and .git, or None
    if it cannot be inspected or is too big to look at. Stops as soon as it exceeds MAX_LIGHT_TEST_FILES."""
    count = 0
    seen = 0
    try:
        for root, dirs, files in os.walk(directory, onerror=_raise_walk_error):
            dirs[:] = [d for d in dirs if d not in TEST_SCAN_SKIP_DIRS]
            for name in files:
                seen += 1
                if any(fnmatch.fnmatch(name, g) for g in TEST_FILE_GLOBS):
                    count += 1
                    if count > MAX_LIGHT_TEST_FILES:
                        return count
            seen += len(dirs)
            if seen > TEST_SCAN_MAX_ENTRIES:
                return None
    except OSError:
        return None
    return count


def _raise_walk_error(error):
    raise error


def _small_test_target(operands):
    """True if every operand is a directory (or glob of them) or test file, and all of them together hold at most
    MAX_LIGHT_TEST_FILES test files. Anything missing, empty or uninspectable keeps the run heavy."""
    if not operands:
        return False
    total = 0
    for operand in operands:
        path = _resolve_path(operand)
        matches = glob.glob(path) if glob.has_magic(path) else [path]
        if not matches:
            return False
        for match in matches:
            if os.path.isdir(match):
                n = _count_test_files(match)
                if n is None:
                    return False
                total += n
            elif os.path.isfile(match):
                total += 1
            else:
                return False
            if total > MAX_LIGHT_TEST_FILES:
                return False
    return total > 0


def _check(argv):
    """Apply the heavy rules to a fully unwrapped argv. Returns (kind, reason) or None."""
    prog = _base(argv[0])
    args = argv[1:]
    joined = ' '.join(argv)

    if prog == 'emulator' and '-avd' in args:
        return ('emulator', 'emulador de Android (emulator -avd)')
    if prog.startswith('qemu-system') and (any('-avd' in a for a in args) or 'Android/Sdk/emulator' in joined):
        return ('emulator', 'proceso qemu del emulador de Android')

    if prog in ('gradlew', 'gradle', 'gradlew.bat'):
        return ('build', 'Gradle con tareas (compilación)') if _gradle_tasks(args) else None
    for main in GRADLE_MAINS:
        if main in argv:
            tasks = _gradle_tasks(argv[argv.index(main) + 1:])
            return ('build', 'cliente Gradle con tareas (compilación)') if tasks else None
    if 'maestro.cli.AppKt' in joined and 'test' in args:
        return ('e2e', 'maestro test (flujos e2e en el emulador)')

    if prog in ML_PROGS or (prog == 'accelerate' and _positionals(args)[:1] == ['launch']):
        if any(a in ('--version', '--help', '-h') for a in args):
            return None
        return ('ml', f'{prog} (modelo de ML: RAM y CPU/GPU altas durante minutos)')

    if prog == 'ffmpeg':
        return _check_ffmpeg(args)
    if prog == 'remotion' and _positionals(args)[:1] == ['render']:
        return ('render', 'remotion render (render de vídeo: todos los núcleos durante minutos)')

    if prog in ('npm', 'pnpm', 'yarn', 'bun'):
        return _check_node_pm(prog, args)
    if prog == 'maestro' and _positionals(args)[:1] == ['test']:
        return ('e2e', 'maestro test (flujos e2e en el emulador)')
    if prog == 'playwright' and _positionals(args)[:1] == ['test']:
        return _check_playwright(args)
    if argv[0].endswith('e2e/run.sh'):
        return ('e2e', 'e2e/run.sh (suite e2e en el emulador)')

    if prog in ('jest', 'vitest'):
        return _check_jest(prog, args)
    if prog in ('pytest', 'py.test'):
        return _check_pytest(args)
    if prog == 'phpunit':
        return _check_phpunit(args)

    if prog in ('make', 'gmake'):
        return _check_make(args)
    return None


def _check_ffmpeg(args):
    """A video encode is heavy (it takes several cores); a single
    frame (a poster), an audio-only conversion or an info flag is not."""
    if not args or any(a in FFMPEG_INFO_OPTS for a in args):
        return None
    for i, a in enumerate(args):
        if a in ('-vframes', '-frames:v', '-frames') and args[i + 1:i + 2] == ['1']:
            return None
    video_opts = any(a in FFMPEG_VIDEO_OPTS or a.startswith(('-c:v', '-codec:v')) for a in args)
    video_out = any(a.lower().endswith(VIDEO_EXTS) for a in _positionals(args, FFMPEG_VALUE_OPTS))
    if '-i' in args and (video_opts or video_out):
        return ('render', 'ffmpeg codificando vídeo (todos los núcleos durante minutos)')
    return None


def _check_pytest(args):
    if any(a in PYTEST_NO_RUN_OPTS or a.startswith('--list-') for a in args):
        return None
    if any('.py' in a or '::' in a for a in args):
        return None
    if any(a == '-k' or (a.startswith('-k') and not a.startswith('--')) for a in args):
        return None
    operands = _positionals(args, PYTEST_VALUE_OPTS)
    if any(_is_expansion(a) for a in operands):
        return None
    if _small_test_target(operands):
        return None
    return ('tests', 'pytest sin fichero ni filtro (suite completa)')


def _check_phpunit(args):
    if any(a in PHPUNIT_NO_RUN_OPTS or a.startswith('--list-') for a in args):
        return None
    if any(a in PHPUNIT_FILTER_OPTS or a.startswith(tuple(o + '=' for o in PHPUNIT_FILTER_OPTS)) or a.endswith('.php')
           for a in args):
        return None
    operands = _positionals(args, PHPUNIT_VALUE_OPTS)
    if any(_is_expansion(a) for a in operands):
        return None
    if _small_test_target(operands):
        return None
    return ('tests', 'phpunit sin filtro ni fichero (suite completa)')


def _check_playwright(args):
    if any(a in ('--list', '--help', '-h', '--version') for a in args):
        return None
    if any(a in ('--grep', '-g') or a.startswith('--grep=') for a in args):
        return None
    operands = _positionals(args, PLAYWRIGHT_VALUE_OPTS)[1:]   # drop the `test` subcommand
    for a in operands:
        spec = a.rsplit(':', 1)[0] if a.rsplit(':', 1)[-1].isdigit() else a    # file.spec.ts:42
        if _is_expansion(a) or spec.endswith(('.ts', '.js', '.mjs', '.tsx')):
            return None
    if _small_test_target(operands):
        return None
    return ('e2e', 'playwright test (suite e2e)')


def _check_node_pm(prog, args):
    pos = _positionals(args, NPM_VALUE_OPTS)
    sub = pos[0] if pos else None
    if sub is None:
        return ('install', 'yarn (instalación completa de dependencias)') if prog == 'yarn' else None
    if prog == 'npm' and sub in ('ci', 'clean-install', 'install-clean'):
        return ('install', 'npm ci (instalación limpia de dependencias)')
    if sub in ('install', 'i') and len(pos) == 1:
        return ('install', f'{prog} {sub} sin paquetes (instalación completa de dependencias)')
    if sub in ('test', 't', 'tst'):
        return ('tests', f'{prog} test (suite completa)')
    script = None
    if sub in ('run', 'run-script', 'rum', 'urn') and len(pos) > 1:
        script = pos[1]
    elif prog in ('yarn', 'pnpm') and sub not in ('install', 'i', 'add', 'remove', 'exec', 'dlx'):
        script = sub
    if script and TEST_SCRIPT_RE.match(script) and script not in NOT_HEAVY_SCRIPTS:
        return ('tests', f'{prog} run {script} (suite de tests)')
    return None


def _check_jest(prog, args):
    if any(a in ('--version', '--help', '-h', '--listTests', '--showConfig') for a in args):
        return None
    if any(a in JEST_FILTER_OPTS or a.startswith(tuple(o + '=' for o in JEST_FILTER_OPTS if o.startswith('--')))
           for a in args):
        return None
    operands = _positionals(args, JEST_VALUE_OPTS)
    for a in operands:
        if '/' in a or a.endswith(PATH_EXTS) or _is_expansion(a):
            return None
    if _small_test_target([a for a in operands if a not in ('run', 'watch', 'dev', 'related')]):
        return None
    return ('tests', f'{prog} sin ruta de fichero (suite completa)')


def _check_make(args):
    targets = []
    dry = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--':
            targets.extend(args[i + 1:])
            break
        if a in ('-j', '--jobs'):
            if i + 1 < len(args) and args[i + 1].isdigit():
                i += 1
        elif a in MAKE_VALUE_OPTS:
            i += 1
        elif a.startswith('-'):
            if a in MAKE_DRY_LONG or (not a.startswith('--') and a[1:].isalpha() and ('n' in a[1:] or 'q' in a[1:])):
                dry = True
        elif '=' not in a:
            targets.append(a)
        i += 1
    if dry:
        return None
    for t in targets:
        if t in MAKE_NOT_HEAVY or t.endswith(MAKE_NOT_HEAVY_SUFFIX):
            continue
        if MAKE_RENDER_RE.match(t):
            return ('render', f'make {t} (render de vídeo: todos los núcleos durante minutos)')
        if MAKE_HEAVY_RE.match(t):
            return ('gate', f'make {t} (puerta de calidad o suite)')
    return None


def classify_argv(argv, _depth=0, _outside=False):
    """Classify ONE simple command given as an argv list. Returns (kind, reason) or None (light).

    With `_outside` a `heavy-job run|hold ...` is not looked into: whatever it wraps already holds a slot."""
    argv = [str(a) for a in argv]
    if _depth > MAX_DEPTH:
        return None
    for _ in range(40):
        argv = _strip_leading(argv)
        if not argv:
            return None
        prog = _base(argv[0])
        if _outside and prog == 'heavy-job' and argv[1:2] and argv[1] in ('run', 'hold'):
            return None
        step = _wrapper_step(prog, argv[1:])
        if step is None:
            step = _interpreter_step(prog, argv[1:])
        if step is None:
            return _check(argv)
        if step[0] == 'argv':
            argv = step[1]
            if len(argv) == 1 and re.search(r'\s', argv[0]):  # `ddev exec "npm ci && npm test"`
                return classify_command(argv[0], _depth + 1, _outside)
        elif step[0] == 'cmd':
            return classify_command(step[1], _depth + 1, _outside)
        elif step[0] == 'hit':
            return step[1]
        else:
            return None
    return None


def classify_command(command, _depth=0, _outside=False, cwd=None):
    """Classify a shell command line. Returns (kind, reason) for the first heavy simple command, else None.

    `cwd` is the directory the line starts in (default: the process cwd); `cd X` inside the line moves it, so
    relative test directories are counted where the command would really run."""
    global _CWD
    if _depth > MAX_DEPTH:
        return None
    saved = _CWD
    if cwd:
        _CWD = cwd
    try:
        for argv in _split_commands(command):
            if argv[:1] == ['cd'] and len(argv) == 2 and not argv[1].startswith('-') and not _is_expansion(argv[1]):
                _CWD = os.path.normpath(_resolve_path(argv[1]))
                continue
            result = classify_argv(argv, _depth, _outside)
            if result:
                return result
        return None
    finally:
        _CWD = saved


def classify_outside_semaphore(command, cwd=None):
    """Like classify_command, but a simple command that really runs `heavy-job run|hold -- CMD` (after the usual
    wrapper stripping: `cd X &&`, `VAR=v`, `nohup`, `timeout`, `bash -c "..."`...) counts as covered and its CMD is
    not judged. Every other simple command of the line is judged: `heavy-job run -- npm ci && npm test` is heavy
    because of `npm test`. Merely mentioning `heavy-job` (`echo heavy-job; npm ci`) covers nothing. Used by the hook."""
    return classify_command(command, 0, True, cwd)


def _light_tool(prog, args):
    """Name of a known light tool (type checker, linter, formatter) run by this unwrapped argv, else None."""
    if prog in LIGHT_TOOLS:
        return prog
    if prog in ('npm', 'pnpm', 'yarn', 'bun'):
        pos = _positionals(args, NPM_VALUE_OPTS)
        script = None
        if pos[:1] and pos[0] in ('run', 'run-script') and len(pos) > 1:
            script = pos[1]
        elif pos and prog != 'npm':
            script = pos[0]
        if script and LIGHT_SCRIPT_RE.match(script):
            return f'{prog} run {script}'
    if prog in ('make', 'gmake'):
        targets = [a for a in _positionals(args, MAKE_VALUE_OPTS) if '=' not in a and not a.isdigit()]
        if targets and all(LIGHT_MAKE_RE.match(t) for t in targets):
            return f'make {" ".join(targets)}'
    return None


def command_leaves(command, depth=0):
    """What every simple command of a shell line really runs, after the same unwrapping as the classifier:
    a list of ('heavy', kind), ('tool', name) for a known light tool, ('trivial',) for `cd`, `echo`... and
    ('opaque',) for anything else (a script, `python -c`, an unknown program)."""
    global _CWD
    if depth > MAX_DEPTH:
        return [('opaque',)]
    saved = _CWD
    out = []
    try:
        for argv in _split_commands(command):
            if argv[:1] == ['cd'] and len(argv) == 2 and not argv[1].startswith('-') and not _is_expansion(argv[1]):
                _CWD = os.path.normpath(_resolve_path(argv[1]))
                out.append(('trivial',))
                continue
            out.extend(argv_leaves(argv, depth))
        return out
    finally:
        _CWD = saved


def argv_leaves(argv, depth=0):
    """`command_leaves` for one argv (see there)."""
    argv = [str(a) for a in argv]
    if depth > MAX_DEPTH:
        return [('opaque',)]
    for _ in range(40):
        argv = _strip_leading(argv)
        if not argv:
            return [('trivial',)]
        prog = _base(argv[0])
        step = _wrapper_step(prog, argv[1:])
        if step is None:
            step = _interpreter_step(prog, argv[1:])
        if step is None:
            hit = _check(argv)
            if hit:
                return [('heavy', hit[0])]
            tool = _light_tool(prog, argv[1:])
            if tool:
                return [('tool', tool)]
            return [('trivial',)] if prog in TRIVIAL_PROGS else [('opaque',)]
        if step[0] == 'argv':
            argv = step[1]
            if len(argv) == 1 and re.search(r'\s', argv[0]):
                return command_leaves(argv[0], depth + 1)
        elif step[0] == 'cmd':
            return command_leaves(step[1], depth + 1)
        elif step[0] == 'hit':
            return [('heavy', step[1][0])]
        else:
            return [('opaque',)]
    return [('opaque',)]


def pool_for(argv, declared_kind=None):
    """(pool, reason): which pool a job takes. Only what does not compile apps nor run tests goes to the light
    pool, and the command decides before the declared kind (`--kind gate` labels both `make ci` and `tsc -b`):
      - anything the classifier calls heavy other than an install (tests, e2e, build, gate, emulator, ml) -> cpu,
        whatever --kind says;
      - a command made only of installs, known light tools and trivial commands -> light;
      - an opaque command (a script) -> light only when --kind is a light kind, else cpu (the safe default)."""
    leaves = argv_leaves(argv)
    for leaf in leaves:
        if leaf[0] == 'heavy' and leaf[1] not in LIGHT_KINDS:
            return CPU_POOL, f'el comando lleva un trabajo de tipo {leaf[1]}'
    known = [leaf for leaf in leaves if leaf[0] in ('heavy', 'tool')]
    if known and all(leaf[0] != 'opaque' for leaf in leaves):
        names = [leaf[1] if leaf[0] == 'tool' else 'instalar dependencias' for leaf in known]
        return LIGHT_POOL, f'solo {", ".join(dict.fromkeys(names))}: ni compila apps ni corre tests'
    if declared_kind in LIGHT_KINDS:
        return LIGHT_POOL, f'--kind {declared_kind}'
    return CPU_POOL, 'puede compilar o correr tests (por defecto)'


def light_kind_of(argv):
    """The kind a light-only command gets when no --kind is given: typecheck, lint or install."""
    leaves = argv_leaves(argv)
    tools = [leaf[1] for leaf in leaves if leaf[0] == 'tool']
    if any(leaf[0] == 'heavy' for leaf in leaves):
        return 'install'
    if any(t.split()[-1] in TYPECHECK_TOOLS or 'type' in t or t.endswith(' tsc') for t in tools):
        return 'typecheck'
    return 'lint' if tools else None


# Worker processes of test runners: (runner, regex over ONE argv element, names that identify a live runner when
# they appear in the parent's command line). jest-worker is also the worker pool of Metro and Expo, hence the
# extra names: a live bundler must never look like an orphaned test run. Playwright's entries were checked in
# the installed node_modules (runner/processHost.js forks lib/common/process.js; older versions use
# lib/worker/workerProcessEntry.js and lib/loader/loaderProcessEntry.js).
ORPHAN_PATTERNS = (
    ('vitest', re.compile(r'vitest/dist/(workers/[A-Za-z0-9_.-]+|worker|child)\.js$'), ('vitest',)),
    ('jest', re.compile(r'jest-worker/build/(workers/)?(processChild|threadChild)\.js$'),
     ('jest', 'metro', 'react-native', 'expo')),
    ('playwright', re.compile(r'playwright/lib/(common/process|worker/workerProcessEntry'
                              r'|loader/loaderProcessEntry)\.js$'), ('playwright',)),
)


def orphan_test_worker(argv, parent_argv):
    """Is `argv` a test-runner worker whose runner is gone? Returns ('tests', reason) or None.

    A worker is orphaned when its parent's command line does not mention the runner (the parent is `systemd
    --user`, init, a shell... or no longer readable): the runner was killed (`pkill vitest`) and nobody will
    ever collect the worker's result, yet it can keep spinning. `parent_argv` is None/[] when unreadable."""
    for arg in argv[1:]:
        for runner, pattern, parent_names in ORPHAN_PATTERNS:
            if not pattern.search(arg):
                continue
            parent_text = ' '.join(parent_argv or []).lower()
            if any(name in parent_text for name in parent_names):
                return None
            return ('tests', f'worker huérfano de {runner} (su runner ya no existe)')
    return None
