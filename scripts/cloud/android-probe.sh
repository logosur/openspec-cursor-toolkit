#!/usr/bin/env bash
# Measures whether a Claude Code cloud session can build an Android App Bundle, on a throwaway app made from the public
# Expo template, so that a cloud build setup is designed on measured facts:
#   1. the machine (CPUs, memory, disk, KVM);
#   2. which hosts an Android build needs are reachable through the session's network;
#   3. where the SDK and the NDK can come from (a Docker Hub image), how long that takes and how much disk it uses;
#   4. a real `bundleRelease` (native code included), timed, or the first thing that stops it.
# The SDK, JDK and Gradle steps are the reusable preset scripts/cloud/android-env.sh, so a passing probe also checks it.
# It prints no environment variables. Each step is bounded, a failed step never stops the next one, and the last lines are
# a short SUMMARY (the runner keeps only the tail of the log). Exit 0 when the probe ran, whatever it found.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ENV_SH=$HERE/android-env.sh
WORK=${ANDROID_PROBE_DIR:-/tmp/android-probe}
export ANDROID_ENV_SDK=${ANDROID_ENV_SDK:-/opt/android-sdk-probe} ANDROID_ENV_JDK=${ANDROID_ENV_JDK:-/opt/jdk-probe}
export ANDROID_ENV_LOG=$WORK/gradle.log
SDK=$ANDROID_ENV_SDK
export ANDROID_ENV_GRADLE_LIMIT=${ANDROID_PROBE_BUILD_LIMIT:-2700}
SUMMARY=$WORK/summary.txt
rm -rf "$WORK"; mkdir -p "$WORK"; : >"$SUMMARY"

note() { printf '%s\n' "$*" | tee -a "$SUMMARY"; }
section() { printf '\n== %s ==\n' "$1"; }
now() { date +%s; }

section "machine"
note "cpus=$(nproc) mem_gb=$(free -g | awk '/^Mem:/{print $2}') disk_free_gb=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)"
if [ -e /dev/kvm ]; then note "kvm=present"; else note "kvm=absent"; fi
note "java=$(java -version 2>&1 | grep -i version | head -1) node=$(node -v 2>/dev/null) uid=$(id -u)"

section "session setup (yes/no only, no names)"
note "env_file=$([ -n "${CLAUDE_ENV_FILE:-}" ] && echo yes || echo no) start_hook_ran=$([ -f "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)/info/cloud-identity.env" ] && echo yes || echo no)"
# An environment setup script that writes this stamp shows whether its result is reused: a stamp older than the
# machine means the session started from a saved copy of the setup, not from a fresh run of it.
note "setup_stamp=$(cat /opt/cloud-setup-stamp 2>/dev/null || echo none) now=$(date -u +%FT%TZ) up_since=$(uptime -s 2>/dev/null | tr " " T) docker_images=$(docker images -q 2>/dev/null | wc -l)"
note "remote_refs=$(git for-each-ref --format='%(refname:short)' refs/remotes 2>/dev/null | tr '\n' ' ' | cut -c1-200)"

section "network (HTTP code, 000 = unreachable)"
for url in \
  https://dl.google.com/android/repository/repository2-3.xml \
  https://maven.google.com/web/index.html \
  https://dl.google.com/dl/android/maven2/androidx/core/core/maven-metadata.xml \
  https://maven.google.com/androidx/core/core/maven-metadata.xml \
  https://repo1.maven.org/maven2/ \
  https://services.gradle.org/distributions/ \
  https://plugins.gradle.org/m2/ \
  https://repo.maven.apache.org/maven2/ \
  https://repo.reactnative.dev/maven2/com/facebook/react/react-android/0.88.1/react-android-0.88.1.pom \
  https://www.jitpack.io/ \
  https://jitpack.io/ \
  https://huggingface.co/openai/whisper-tiny/resolve/main/model.safetensors \
  https://registry.npmjs.org/expo \
  https://registry-1.docker.io/v2/ \
  https://storage.googleapis.com/ \
  https://huggingface.co/ \
  https://api.elevenlabs.io/ \
  https://api.elevenlabs.io/v1/voices \
  https://api.openai.com/ ; do
  code=$(curl -sS -L -m 20 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)
  note "net ${code:-000} $url"
done

# --net-only: just the machine and the network, to check a change of the environment's allowed domains in seconds.
if [ "${1:-}" = "--net-only" ]; then section "SUMMARY"; cat "$SUMMARY"; exit 0; fi

section "SDK and JDK (android-env.sh prepare)"
t=$(now)
if bash "$ENV_SH" prepare >"$WORK/prepare.log" 2>&1; then
  note "prepare=ok seconds=$(( $(now) - t ))"; sed 's/^/  /' "$WORK/prepare.log" | cut -c1-230 | tee -a "$SUMMARY"
  note "sdk_gb=$(du -s -BG "$SDK" 2>/dev/null | cut -f1) disk_free_gb_after_sdk=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)"
else
  note "prepare=failed seconds=$(( $(now) - t )) $(tail -2 "$WORK/prepare.log" | tr '\n' ' ' | cut -c1-240)"
fi

section "template app"
cd "$WORK" || exit 0
t=$(now)
if timeout 900 npx --yes create-expo-app@latest app --template blank --no-install >"$WORK/create.log" 2>&1 \
  && cd app && timeout 900 npm install --no-audit --no-fund >"$WORK/npm.log" 2>&1; then
  note "app_created=yes seconds=$(( $(now) - t )) expo=$(node -p "require('./node_modules/expo/package.json').version" 2>/dev/null) rn=$(node -p "require('./node_modules/react-native/package.json').version" 2>/dev/null)"
else
  note "app_created=no seconds=$(( $(now) - t )) $(tail -2 "$WORK/create.log" "$WORK/npm.log" 2>/dev/null | tr '\n' ' ' | cut -c1-240)"
fi

if [ -f package.json ] && [ -d "$SDK/platforms" ]; then
  export ANDROID_HOME=$SDK ANDROID_SDK_ROOT=$SDK CI=1
  t=$(now)
  if timeout 600 npx expo prebuild --platform android --no-install >"$WORK/prebuild.log" 2>&1; then
    note "prebuild=ok seconds=$(( $(now) - t )) wants_ndk=$(grep -rhoE 'ndkVersion *= *"[^"]+"' node_modules/react-native/gradle/libs.versions.toml android 2>/dev/null | head -1) wants=$(grep -hE '^(ndkVersion|compileSdk|buildTools) *=' node_modules/react-native/gradle/libs.versions.toml 2>/dev/null | tr '\n' ' ')"
    section "gradle bundleRelease (limit ${ANDROID_ENV_GRADLE_LIMIT}s)"
    # A warm second run on the same machine shows how much of the build time is downloads.
    note "gradle_cache_before_gb=$(du -s -BG "$HOME/.gradle" 2>/dev/null | cut -f1 || echo 0)"
    bash "$ENV_SH" gradle-props android 2>&1 | tee -a "$SUMMARY"
    t=$(now)
    bash "$ENV_SH" gradle android :app:bundleRelease >"$WORK/gradle-attempts.log" 2>&1
    rc=$?
    cut -c1-230 "$WORK/gradle-attempts.log" | tee -a "$SUMMARY"
    note "gradle_exit=$rc seconds=$(( $(now) - t ))"
    cd android || exit 0
    aab=$(find app/build/outputs/bundle -name '*.aab' 2>/dev/null | head -1)
    if [ -n "$aab" ]; then note "aab=yes size_mb=$(( $(stat -c %s "$aab") / 1048576 )) abis=$(unzip -l "$aab" 2>/dev/null | grep -oE 'base/lib/[^/]+' | sort -u | cut -d/ -f3 | tr '\n' ' ')"; else note "aab=no"; fi
    note "gradle_tasks_run=$(grep -cE '^> Task ' "$WORK/gradle.log") native_tasks=$(grep -cE '^> Task .*(CMake|buildCMake|configureCMake)' "$WORK/gradle.log")"
    if [ "$rc" -ne 0 ]; then
      note "gradle_log_tail:"; grep -v '^$' "$WORK/gradle.log" | tail -25 | cut -c1-230 | tee -a "$SUMMARY"
      note "gradle_first_errors:"
      grep -nE 'Could not (resolve|GET|HEAD|download|find)|FAILURE|What went wrong|NDK|> Failed|403|Connection|Cannot find' "$WORK/gradle.log" | head -12 | cut -c1-230 | tee -a "$SUMMARY"
      note "gradle_blocked_hosts=$(grep -oE "Could not (GET|HEAD) 'https://[^/']+" "$WORK/gradle.log" | grep -oE 'https://.*' | sort | uniq -c | tr '\n' ' ' | cut -c1-300)"
    fi
    note "gradle_cache_gb=$(du -s -BG "$HOME/.gradle" 2>/dev/null | cut -f1) disk_free_gb_end=$(df -BG --output=avail / | tail -1 | tr -dc 0-9) mem_peak_note=see_free"
  else
    note "prebuild=failed seconds=$(( $(now) - t )) $(tail -3 "$WORK/prebuild.log" | tr '\n' ' ' | cut -c1-240)"
  fi
else
  note "build=skipped (no app or no SDK)"
fi

section "SUMMARY"
cat "$SUMMARY"
exit 0
