#!/usr/bin/env bash
# Probe revision: 5.
# Measures whether a Claude Code cloud session can build an Android App Bundle, on a throwaway app made from the public
# Expo template, so that a cloud build setup is designed on measured facts:
#   1. the machine (CPUs, memory, disk, KVM);
#   2. which hosts an Android build needs are reachable through the session's network;
#   3. where the SDK and the NDK can come from (a Docker Hub image), how long that takes and how much disk it uses;
#   4. a real `bundleRelease` (native code included), timed, or the first thing that stops it.
# It prints no environment variables. Each step is bounded, a failed step never stops the next one, and the last lines are
# a short SUMMARY (the runner keeps only the tail of the log). Exit 0 when the probe ran, whatever it found.
set -uo pipefail

IMAGE=${ANDROID_PROBE_IMAGE:-reactnativecommunity/react-native-android:latest}
WORK=${ANDROID_PROBE_DIR:-/tmp/android-probe}
SDK=/opt/android-sdk-probe
JDK=/opt/jdk-probe
BUILD_LIMIT=${ANDROID_PROBE_BUILD_LIMIT:-2700}
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

section "docker and the SDK image"
if ! docker info >/dev/null 2>&1; then
  (nohup dockerd >/tmp/dockerd-probe.log 2>&1 &)
  for _ in $(seq 1 40); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi
if docker info >/dev/null 2>&1; then
  t=$(now)
  ok=no
  for _ in 1 2 3; do timeout 1500 docker pull -q "$IMAGE" >/dev/null 2>"$WORK/pull.err" && { ok=yes; break; }; sleep 5; done
  note "image_pull=$ok seconds=$(( $(now) - t )) image=$IMAGE"
  [ "$ok" = no ] && note "image_pull_error=$(tail -1 "$WORK/pull.err" | cut -c1-200)"
  if [ "$ok" = yes ]; then
    image_sdk=$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$IMAGE" | sed -n 's/^ANDROID_HOME=//p' | head -1)
    t=$(now)
    image_jdk=$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$IMAGE" | sed -n 's/^JAVA_HOME=//p' | head -1)
    c=$(docker create "$IMAGE"); rm -rf "$SDK" "$JDK"; docker cp "$c:${image_sdk:-/opt/android}" "$SDK" >/dev/null 2>&1
    # -L: JAVA_HOME is often a symlink into /usr/lib/jvm
    [ -n "$image_jdk" ] && docker cp -L "$c:$image_jdk" "$JDK" >/dev/null 2>&1
    # A Debian JDK keeps its configuration in /etc/<jdk name> behind absolute symlinks: bring it too, or the JVM cannot start.
    jdk_etc=/etc/$(basename "${image_jdk:-none}" | sed 's/-amd64$//; s/-arm64$//')
    [ -n "$image_jdk" ] && [ ! -e "$jdk_etc" ] && docker cp "$c:$jdk_etc" "$jdk_etc" >/dev/null 2>&1
    docker rm "$c" >/dev/null
    note "image_jdk=${image_jdk:-none} jdk_copied=$([ -x "$JDK/bin/java" ] && "$JDK/bin/java" -version 2>&1 | grep -i version | head -1 || echo no)"
    note "sdk_copy_seconds=$(( $(now) - t )) sdk_gb=$(du -s -BG "$SDK" 2>/dev/null | cut -f1) image_sdk=${image_sdk:-unknown}"
    note "sdk_platforms=$(ls "$SDK/platforms" 2>/dev/null | tr '\n' ' ')"
    note "sdk_build_tools=$(ls "$SDK/build-tools" 2>/dev/null | tr '\n' ' ')"
    note "sdk_ndk=$(ls "$SDK/ndk" 2>/dev/null | tr '\n' ' ') cmake=$(ls "$SDK/cmake" 2>/dev/null | tr '\n' ' ')"
    docker image rm "$IMAGE" >/dev/null 2>&1 || true
    note "disk_free_gb_after_sdk=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)"
  fi
else
  note "docker=unavailable $(tail -1 /tmp/dockerd-probe.log 2>/dev/null | cut -c1-160)"
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
    section "gradle bundleRelease (limit ${BUILD_LIMIT}s)"
    cd android || exit 0
    # The image's JDK, for Gradle itself and for its toolchains (the session's own Java may be another version).
    if [ -x "$JDK/bin/java" ]; then
      host_path=$PATH
      export JAVA_HOME=$JDK PATH=$JDK/bin:$PATH
      printf '\norg.gradle.java.installations.paths=%s\norg.gradle.java.installations.auto-download=false\n' "$JDK" >>gradle.properties
    fi
    # The NDK cannot be downloaded when dl.google.com is closed: build with the one the image brings.
    wanted_ndk=$(grep -hoE 'ndkVersion *= *"[^"]+"' ../node_modules/react-native/gradle/libs.versions.toml 2>/dev/null | grep -oE '[0-9.]+' | head -1)
    have_ndk=$(ls "$SDK/ndk" 2>/dev/null | sort -V | tail -1)
    if [ -n "$have_ndk" ] && [ ! -d "$SDK/ndk/$wanted_ndk" ]; then
      printf 'android.ndkVersion=%s\n' "$have_ndk" >>gradle.properties
      note "ndk_override=$have_ndk (wanted ${wanted_ndk:-unknown})"
    fi
    t=$(now); attempts=0; rc=1
    # A shared exit address makes Maven Central answer 429 now and then: retry, Gradle keeps what it already downloaded.
    # A failed plugin or dependency lookup right after a 429 fails again at once: wait and retry those too.
    while [ "$attempts" -lt 6 ]; do
      attempts=$((attempts + 1))
      left=$(( BUILD_LIMIT - ($(now) - t) )); [ "$left" -lt 60 ] && break
      timeout "$left" ./gradlew --no-daemon --console=plain --info -Dorg.gradle.internal.repository.max.tentatives=8 \
        -Dorg.gradle.internal.repository.initial.backoff=3000 :app:bundleRelease >"$WORK/gradle.log" 2>&1
      rc=$?
      note "gradle_attempt=$attempts exit=$rc elapsed=$(( $(now) - t )) http_429=$(grep -c 'status code 429' "$WORK/gradle.log") tasks=$(grep -cE '^> Task ' "$WORK/gradle.log")"
      [ "$rc" -eq 0 ] && break
      if [ "$attempts" -eq 1 ] && [ $(( $(now) - t )) -lt 15 ] && [ -n "${host_path:-}" ]; then
        # Gradle did not even start on the image's JDK: say why, then run it on the session's Java (toolchain still set).
        note "gradle_start_failure:"; head -12 "$WORK/gradle.log" | cut -c1-230 | tee -a "$SUMMARY"
        unset JAVA_HOME; export PATH=$host_path; continue
      fi
      note "gradle_http_statuses=$(grep -oE 'status code [0-9]+' "$WORK/gradle.log" | sort | uniq -c | tr '\n' ' ')"
      grep -qE 'status code 429|was not found in any of the following sources|Could not resolve' "$WORK/gradle.log" || break
      sleep 120
    done
    note "gradle_exit=$rc seconds=$(( $(now) - t )) attempts=$attempts (124 = stopped at the limit)"
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
