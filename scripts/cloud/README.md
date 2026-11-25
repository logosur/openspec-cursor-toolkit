# Cloud scripts

Tools for Claude Code cloud sessions (claude.ai/code). They belong to this repository and are not installed by
`install.sh`; another project copies what it needs into its own `scripts/cloud/`.

| File | What it is |
|------|------------|
| `android-env.sh` | **Android build preset**: SDK, NDK, CMake and JDK 17 for a cloud session, plus a Gradle runner with retries. |
| `android-probe.sh` | Measures a cloud session and builds a release bundle of a throwaway Expo app with the preset. Not a gate. |
| `setup.sh` | Setup of this repository's cloud suites (`.claude/cloud-tests.json`); nothing to install. |

## Android build preset

```bash
bash scripts/cloud/android-env.sh prepare                       # once per session; idempotent
eval "$(bash scripts/cloud/android-env.sh env)"                 # ANDROID_HOME, ANDROID_SDK_ROOT, JAVA_HOME, PATH
bash scripts/cloud/android-env.sh gradle-props android          # JDK toolchain and, when needed, the image's NDK
bash scripts/cloud/android-env.sh gradle android :app:bundleRelease
```

Why each step is there, measured on 2026-11-24/25 in cloud sessions (Ubuntu 24.04, 4 CPUs, 15 GB, about 60 GB free disk,
root, no KVM, Java 21 and Node 22 preinstalled, no Android SDK, no Java 17):

- **SDK from a Docker Hub image.** `reactnativecommunity/react-native-android` pulls in 46–87 s; copying its SDK
  (3 GB: platform 37, build-tools 37.0.0, NDK 28.2, CMake 3.30.5) takes 13–23 s. Docker Hub is reachable by default.
- **JDK 17 from the same image.** The session has none. A Debian JDK also needs its `/etc/<jdk name>` folder, or the
  JVM stops with "Error loading java.security file"; the preset copies both.
- **NDK override.** React Native 0.88 asks for NDK 27.1; the image brings 28.2. Building with 28.2 works: 19 native
  tasks, a 43 MB bundle with arm64-v8a, armeabi-v7a, x86 and x86_64.
- **Retries.** Maven Central answers 429 now and then from the shared exit address, and a plugin lookup right after one
  fails again at once. The preset waits 120 s and retries, up to 6 attempts within 45 minutes.
- **Time.** A cold `bundleRelease` of the blank Expo 58 app: 1755 s of Gradle (392 tasks), 1885 s in all. How much of
  that is downloads and how much native compilation is not measured yet; the probe prints the Gradle cache size before
  building, so a second run on a warm machine answers it.

## Network the cloud environment needs

The environment's network access is **Limited** with package managers allowed. An Android build also needs these
domains in the environment's allowed list (claude.ai/code, environment settings, Network access); without them the
proxy answers 403 "no rule or network setting allows this host":

- `*.google.com` (Google's Maven: `dl.google.com`, `maven.google.com`)
- `repo.reactnative.dev` (Maven Central redirects React Native's AAR there)
- `jitpack.io`, `*.jitpack.io` (libraries published on JitPack)

Speech and model work also needs `huggingface.co`, `*.huggingface.co`, `*.hf.co`, `elevenlabs.io`, `*.elevenlabs.io`,
`openai.com`, `*.openai.com`. `bash scripts/cloud/android-probe.sh --net-only` checks all of them in seconds.

## Environment setup script and caching

- The environment's **setup script** (environment settings, Setup script) runs as root on the first session; its
  result is a filesystem snapshot that later sessions start from, also the sessions the CLI launches. Measured: a
  stamp written by the script at 02:19 was present on a machine booted at 02:22, and still on one booted 3.5 hours
  later. Changing the allowed domains rebuilt it. Documented: cached only when it ends in about 5 minutes; expires
  after about 7 days; also rebuilt when the script changes.
- A **SessionStart hook** in the repository runs on every session and is not cached.
- The Android SDK stays out of the environment's setup script: the script is shared by every repository using that
  environment, every edit rebuilds the snapshot for all of them, and the SDK is only about 75 s of a half-hour build.

## One environment

Keep a single cloud environment. The CLI uses one environment and cannot choose one per invocation, so a runner that
launches sessions from the CLI cannot use more. Split off a separate environment only when paid-API secrets are added to
one (speech, models), so that they do not reach every repository's sessions.
