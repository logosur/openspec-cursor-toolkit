#!/usr/bin/env bash
# Android build preset for a Claude Code cloud session (Ubuntu, root, no Android SDK, no Java 17, limited network).
# Copy it into a project's scripts/cloud/ and call it from the project's own cloud scripts. Measured facts behind each
# step are in scripts/cloud/README.md.
#
#   android-env.sh prepare               SDK, NDK, CMake and JDK 17 copied out of a public Docker Hub image (idempotent)
#   android-env.sh env                   print the exports to eval: ANDROID_HOME, ANDROID_SDK_ROOT, JAVA_HOME, PATH
#   android-env.sh gradle-props DIR      point DIR/gradle.properties at that JDK, and at the image's NDK when the project
#                                        asks for one the image does not bring (idempotent)
#   android-env.sh gradle DIR TASK...    run DIR/gradlew TASK... with retries on rate limits and failed lookups
#
# Settings (environment): ANDROID_ENV_IMAGE (default reactnativecommunity/react-native-android:latest),
# ANDROID_ENV_SDK (/opt/android-sdk), ANDROID_ENV_JDK (/opt/android-jdk), ANDROID_ENV_GRADLE_LIMIT (seconds, 2700),
# ANDROID_ENV_GRADLE_ATTEMPTS (6), ANDROID_ENV_LOG (file for the last Gradle output, /tmp/android-env-gradle.log).
# It prints no secrets. Exit codes: 0 done, 1 failed (the reason on stderr), 2 wrong usage.
set -uo pipefail

IMAGE=${ANDROID_ENV_IMAGE:-reactnativecommunity/react-native-android:latest}
SDK=${ANDROID_ENV_SDK:-/opt/android-sdk}
JDK=${ANDROID_ENV_JDK:-/opt/android-jdk}
GRADLE_LIMIT=${ANDROID_ENV_GRADLE_LIMIT:-2700}
GRADLE_ATTEMPTS=${ANDROID_ENV_GRADLE_ATTEMPTS:-6}
LOG=${ANDROID_ENV_LOG:-/tmp/android-env-gradle.log}
MARK='# android-env.sh'

say() { printf 'android-env: %s\n' "$*"; }
die() { printf 'android-env: %s\n' "$*" >&2; exit 1; }
now() { date +%s; }

ready() { [ -d "$SDK/platforms" ] && [ -x "$JDK/bin/java" ] && "$JDK/bin/java" -version >/dev/null 2>&1; }

start_docker() {
  docker info >/dev/null 2>&1 && return 0
  (nohup dockerd >/tmp/android-env-dockerd.log 2>&1 &)
  for _ in $(seq 1 40); do docker info >/dev/null 2>&1 && return 0; sleep 1; done
  return 1
}

image_env() { docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$IMAGE" | sed -n "s/^$1=//p" | head -1; }

prepare() {
  if ready; then say "ready (sdk=$SDK jdk=$JDK)"; return 0; fi
  start_docker || die "docker is not available: $(tail -1 /tmp/android-env-dockerd.log 2>/dev/null)"
  local t ok=no c image_sdk image_jdk jdk_etc
  t=$(now)
  # Docker Hub answers slowly now and then from a shared exit address: retry the pull.
  for _ in 1 2 3; do timeout 1500 docker pull -q "$IMAGE" >/dev/null 2>/tmp/android-env-pull.err && { ok=yes; break; }; sleep 5; done
  [ "$ok" = yes ] || die "cannot pull $IMAGE: $(tail -1 /tmp/android-env-pull.err | cut -c1-200)"
  say "image pulled in $(( $(now) - t ))s"
  image_sdk=$(image_env ANDROID_HOME); image_jdk=$(image_env JAVA_HOME)
  [ -n "$image_jdk" ] || die "$IMAGE declares no JAVA_HOME"
  t=$(now)
  c=$(docker create "$IMAGE") || die "cannot create a container from $IMAGE"
  rm -rf "$SDK" "$JDK"; mkdir -p "$(dirname "$SDK")" "$(dirname "$JDK")"
  docker cp "$c:${image_sdk:-/opt/android}" "$SDK" >/dev/null 2>&1
  # -L: JAVA_HOME is often a symlink into /usr/lib/jvm.
  docker cp -L "$c:$image_jdk" "$JDK" >/dev/null 2>&1
  # A Debian JDK keeps its configuration in /etc/<jdk name> behind absolute symlinks: without it the JVM cannot start
  # ("Error loading java.security file").
  jdk_etc=/etc/$(basename "$image_jdk" | sed 's/-amd64$//; s/-arm64$//')
  [ -e "$jdk_etc" ] || docker cp "$c:$jdk_etc" "$jdk_etc" >/dev/null 2>&1
  docker rm "$c" >/dev/null
  docker image rm "$IMAGE" >/dev/null 2>&1 || true
  ready || die "the copied SDK or JDK does not work (sdk=$SDK jdk=$JDK)"
  say "copied in $(( $(now) - t ))s: platforms=$(ls "$SDK/platforms" | tr '\n' ' ')build-tools=$(ls "$SDK/build-tools" 2>/dev/null | tr '\n' ' ')ndk=$(ls "$SDK/ndk" 2>/dev/null | tr '\n' ' ')cmake=$(ls "$SDK/cmake" 2>/dev/null | tr '\n' ' ')"
}

print_env() {
  ready || die "not prepared: run '$0 prepare' first"
  printf 'export ANDROID_HOME=%q ANDROID_SDK_ROOT=%q JAVA_HOME=%q PATH=%q\n' "$SDK" "$SDK" "$JDK" "$JDK/bin:$PATH"
}

gradle_props() {
  local dir=${1:-} props wanted have
  [ -n "$dir" ] && [ -f "$dir/gradlew" ] || { echo "usage: $0 gradle-props ANDROID_DIR (the folder with gradlew)" >&2; exit 2; }
  ready || die "not prepared: run '$0 prepare' first"
  props=$dir/gradle.properties
  if ! grep -qs "^$MARK" "$props"; then
    # The session's own Java is another version: give Gradle's toolchains this JDK and never let them download one.
    printf '\n%s\norg.gradle.java.installations.paths=%s\norg.gradle.java.installations.auto-download=false\n' \
      "$MARK" "$JDK" >>"$props"
    # React Native asks for one exact NDK. When the image brings another, build with the image's (measured: RN 0.88
    # with NDK 28.2 instead of 27.1 builds and packs all four ABIs).
    wanted=$(grep -hoE 'ndkVersion *= *"[^"]+"' "$dir"/../node_modules/react-native/gradle/libs.versions.toml "$dir"/build.gradle 2>/dev/null | grep -oE '[0-9][0-9.]+' | head -1)
    have=$(ls "$SDK/ndk" 2>/dev/null | sort -V | tail -1)
    if [ -n "$have" ] && [ -n "$wanted" ] && [ ! -d "$SDK/ndk/$wanted" ]; then
      printf 'android.ndkVersion=%s\n' "$have" >>"$props"
      say "ndk $have instead of $wanted"
    fi
  fi
  say "gradle.properties ready"
}

gradle() {
  local dir=${1:-} t attempts=0 rc=1 left
  [ -n "$dir" ] && [ -f "$dir/gradlew" ] && [ $# -ge 2 ] || { echo "usage: $0 gradle ANDROID_DIR TASK..." >&2; exit 2; }
  shift
  eval "$(print_env)"
  t=$(now)
  # A shared exit address makes Maven Central answer 429 now and then, and a lookup that failed right after one fails
  # again at once: wait and retry. Gradle keeps what it already downloaded between attempts.
  while [ "$attempts" -lt "$GRADLE_ATTEMPTS" ]; do
    attempts=$((attempts + 1))
    left=$(( GRADLE_LIMIT - ($(now) - t) )); [ "$left" -lt 60 ] && break
    (cd "$dir" && timeout "$left" ./gradlew --no-daemon --console=plain \
      -Dorg.gradle.internal.repository.max.tentatives=8 -Dorg.gradle.internal.repository.initial.backoff=3000 "$@") \
      >"$LOG" 2>&1
    rc=$?
    say "gradle attempt $attempts: exit $rc after $(( $(now) - t ))s, $(grep -cE '^> Task ' "$LOG") tasks"
    [ "$rc" -eq 0 ] && return 0
    grep -qE 'status code 429|was not found in any of the following sources|Could not resolve' "$LOG" || break
    sleep 120
  done
  printf 'android-env: gradle failed (exit %s); blocked hosts: %s\n' "$rc" \
    "$(grep -oE "Could not (GET|HEAD) 'https://[^/']+" "$LOG" | grep -oE 'https://.*' | sort -u | tr '\n' ' ')" >&2
  return 1
}

case "${1:-}" in
  prepare) prepare ;;
  env) print_env ;;
  gradle-props) shift; gradle_props "$@" ;;
  gradle) shift; gradle "$@" ;;
  *) sed -n '2,17p' "$0" >&2; exit 2 ;;
esac
