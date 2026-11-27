#!/usr/bin/env bash
# Try the whole toolkit from zero without touching your own ~/.claude.
#
#   bash examples/override-full/try.sh [OVERRIDE_DIR]      (default: this folder)
#
# It installs the toolkit with the override into a throwaway HOME, runs every check the toolkit has (contract
# probes, the pieces' own self-tests, drift, a second install that must change nothing), uninstalls, and removes
# the throwaway HOME. Nothing runs against your real HOME: every variable that could point a piece at real state
# is dropped. Exit 0 when every step passes; on a failure the throwaway HOME is kept so you can read the logs.
# TRY_KEEP=1 keeps it on success too.
set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)
override=$(cd "${1:-$here}" && pwd)
py=$(command -v python3) || { echo "python3 not found" >&2; exit 2; }
# a PyYAML installed with `pip --user` lives under the real user base, which a new HOME would hide
user_base=$("$py" -m site --user-base 2>/dev/null || true)

try_home=$(mktemp -d "${TMPDIR:-/tmp}/toolkit-try-XXXXXX")
target=$try_home/.claude
logs=$try_home/logs
mkdir -p "$logs" "$try_home/tmp" "$try_home/run"
chmod 700 "$try_home/run"

# A clean environment: only what the tools need, with every path inside the throwaway HOME.
sandbox=(env -i "PATH=$PATH" "HOME=$try_home" "TMPDIR=$try_home/tmp" "LANG=${LANG:-C.UTF-8}"
         "XDG_RUNTIME_DIR=$try_home/run" "HEAVY_JOB_DIR=$try_home/run/heavy-job"
         "GIT_CONFIG_GLOBAL=/dev/null" "GIT_CONFIG_SYSTEM=/dev/null" "PYTHONUSERBASE=$user_base")
installer=("${sandbox[@]}" "$repo/install.sh")

declare -a results=()
failed=0
step=0

run_step() {  # run_step <label> <command...>: PASS on exit 0, FAIL otherwise
    local label=$1; shift
    step=$((step + 1))
    local log
    log=$logs/$(printf '%02d' "$step")-$(echo "$label" | tr -c 'a-zA-Z0-9\n' '-').log
    if "$@" >"$log" 2>&1; then
        results+=("PASS  $label")
    else
        results+=("FAIL  $label (exit $?, log: $log)")
        failed=1
        tail -n 20 "$log" | sed 's/^/      /'
    fi
}

skip_step() {  # skip_step <label> <why>
    step=$((step + 1))
    results+=("SKIP  $1: $2")
}

expect_in_log() {  # expect_in_log <text> <command...>: the command passes and prints <text>
    local text=$1; shift
    local out
    out=$("$@" 2>&1) || { echo "$out"; return 1; }
    echo "$out"
    grep -qF -- "$text" <<<"$out" || { echo "expected: $text"; return 1; }
}

echo "throwaway HOME: $try_home"
echo "override:       $override"
echo

run_step "install, dry run" "${installer[@]}" install --dry-run --override "$override" --target "$target"
run_step "install" "${installer[@]}" install --override "$override" --target "$target"
run_step "status" "${installer[@]}" status --override "$override" --target "$target"
verify_ran_probes() {  # verify passes and ran at least one probe: zero probes means nothing was installed
    local out
    out=$("$@" 2>&1); local code=$?
    echo "$out"
    [ "$code" -eq 0 ] && ! grep -q 'verify: 0 probe(s)' <<<"$out"
}
run_step "contract probes of every installed piece (verify)" verify_ran_probes "${installer[@]}" verify --target "$target"
if [ -f "$target/scripts/supervisor-lock" ]; then
    run_step "supervisor-lock self-test" "${sandbox[@]}" "$py" "$target/scripts/supervisor-lock" self-test
else
    skip_step "supervisor-lock self-test" "the supervision module is not installed"
fi
if [ -f "$target/scripts/usage-watch" ]; then
    run_step "usage-watch self-test" "${sandbox[@]}" "$py" "$target/scripts/usage-watch" self-test
else
    skip_step "usage-watch self-test" "the usage module is not installed"
fi
if [ -f "$target/scripts/test-account" ]; then
    run_step "test-account self-test" "${sandbox[@]}" "$py" "$target/scripts/test-account" self-test
else
    skip_step "test-account self-test" "the devtools module is not installed"
fi
# The kill gate's self-test checks its patterns against processes a desktop session always has (gvfs).
if [ ! -f "$target/hooks/process-kill-gate" ]; then
    skip_step "process-kill-gate self-test" "the core module is not installed"
elif pgrep gvfs >/dev/null 2>&1; then
    run_step "process-kill-gate self-test" "${sandbox[@]}" "$py" "$target/hooks/process-kill-gate" --self-test
else
    skip_step "process-kill-gate self-test" "needs a desktop session (a running gvfs process)"
fi
run_step "drift: the install matches toolkit + override" "${installer[@]}" drift --override "$override" --target "$target"
run_step "a second install changes nothing" expect_in_log "already installed: nothing to do" \
    "${installer[@]}" install --override "$override" --target "$target"
installed=0
cp "$target/toolkit/installed.json" "$try_home/installed.json" 2>/dev/null && installed=1
run_step "uninstall" "${installer[@]}" uninstall --target "$target"
# Every file the install wrote is gone, with the bytecode Python made of it. What the pieces wrote while they ran
# (logs, queues, locks) is the user's runtime state: uninstall keeps it, and so does this check.
if [ "$installed" -eq 0 ]; then
    skip_step "nothing the install wrote is left after uninstall" "nothing was installed"
else
run_step "nothing the install wrote is left after uninstall" "${sandbox[@]}" "$py" - "$target" "$try_home/installed.json" <<'PY'
import json, os, sys
target, manifest = sys.argv[1], json.load(open(sys.argv[2]))
left = [d for d in manifest['files'] if os.path.lexists(os.path.join(target, d))]
left += [os.path.relpath(os.path.join(r, f), target) for r, _, fs in os.walk(target) for f in fs if f.endswith('.pyc')]
left += ['toolkit/installed.json'] if os.path.exists(os.path.join(target, 'toolkit/installed.json')) else []
print('\n'.join(left) or f"none of the {len(manifest['files'])} installed files is left")
sys.exit(1 if left else 0)
PY
fi
kept=$(find "$target" -type f -not -path "$target/backups/*" 2>/dev/null | wc -l)

echo
printf '%s\n' "${results[@]}"
echo "note  runtime state the pieces wrote while they ran, kept by uninstall as the user's: $kept file(s)"
if [ "$failed" -eq 0 ] && [ -z "${TRY_KEEP:-}" ]; then
    rm -rf "$try_home"
    echo
    echo "every step passed; throwaway HOME removed"
    exit 0
fi
echo
if [ "$failed" -eq 0 ]; then
    echo "every step passed; throwaway HOME kept: $try_home"
    exit 0
fi
echo "some step failed; throwaway HOME kept with its logs: $try_home"
exit 1
