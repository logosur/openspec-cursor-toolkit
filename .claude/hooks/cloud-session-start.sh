#!/bin/bash
# SessionStart, cloud sessions only (CLAUDE_CODE_REMOTE=true): commit with the identity of the repository's owner, never
# with the platform's default one. A cloud session does not read the user's own configuration, so the repository sets it.
# The identity is read from the last commit of the default branch, so no name or address is written here. Idempotent.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}"
ref=$(git symbolic-ref -q refs/remotes/origin/HEAD || echo refs/remotes/origin/main)
name=$(git log -1 --format=%an "$ref")
email=$(git log -1 --format=%ae "$ref")
[ -n "$name" ] && [ -n "$email" ] || { echo "cloud-session-start: no identity found on $ref" >&2; exit 0; }
git config user.name "$name"
git config user.email "$email"
exports="$(git rev-parse --path-format=absolute --git-common-dir)/info/cloud-identity.env"
mkdir -p "$(dirname "$exports")"
{
  printf "export GIT_AUTHOR_NAME='%s'\n" "$name"
  printf "export GIT_AUTHOR_EMAIL='%s'\n" "$email"
  printf "export GIT_COMMITTER_NAME='%s'\n" "$name"
  printf "export GIT_COMMITTER_EMAIL='%s'\n" "$email"
} > "$exports"
if [ -n "${CLAUDE_ENV_FILE:-}" ] && ! grep -qs 'cloud-identity.env' "$CLAUDE_ENV_FILE"; then
  printf '. %q\n' "$exports" >> "$CLAUDE_ENV_FILE"
fi
