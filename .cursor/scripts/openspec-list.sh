#!/usr/bin/env bash
# List OpenSpec changes as a table (unfinished first, then complete).
# Usage:
#   openspec-list.sh [count] [--html [path]] [--no-chrome]
#   Prints Markdown table, writes HTML, opens Chrome.
#   Default (no count): show ALL active if any spec is unfinished; else 5.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if ! command -v openspec >/dev/null 2>&1; then
  echo "openspec-list: openspec CLI not found (install OpenSpec CLI)." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "openspec-list: jq is required." >&2
  exit 1
fi

REQUESTED=5
COUNT_EXPLICIT=false
OPEN_CHROME=true
HTML_PATH=".cursor/context/openspec/openspec-list.html"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --html)
      if [[ $# -ge 2 && "$2" != --* ]]; then
        HTML_PATH="$2"
        shift
      fi
      shift
      ;;
    --no-chrome)
      OPEN_CHROME=false
      shift
      ;;
    -h|--help)
      echo "Usage: openspec-list.sh [count] [--html [path]] [--no-chrome]" >&2
      echo "  count — active changes to list, unfinished first (+ same count archived)." >&2
      echo "          Default: ALL active if any spec is unfinished, otherwise 5." >&2
      echo "  --html [path] — HTML output path (default: .cursor/context/openspec/openspec-list.html)" >&2
      echo "  --no-chrome — skip opening the HTML report in the browser" >&2
      exit 0
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        REQUESTED="$1"
        COUNT_EXPLICIT=true
        shift
      else
        echo "Usage: openspec-list.sh [count] [--html [path]]" >&2
        exit 1
      fi
      ;;
  esac
done

if (( REQUESTED < 1 )); then
  echo "Usage: openspec-list.sh [count]  (positive integer; default 5)" >&2
  exit 1
fi

ARCHIVE_DIR="openspec/changes/archive"

LIST_JSON="$(openspec list --json)"
CHANGE_COUNT="$(jq '.changes | length' <<<"$LIST_JSON")"
UNFINISHED_COUNT="$(jq '[.changes[] | select(.status != "complete")] | length' <<<"$LIST_JSON")"

ARCHIVED_DIRS=()
if [[ -d "$ARCHIVE_DIR" ]]; then
  while IFS= read -r dir; do
    ARCHIVED_DIRS+=("$dir")
  done < <(find "$ARCHIVE_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -r)
fi
ARCHIVE_COUNT="${#ARCHIVED_DIRS[@]}"

if (( CHANGE_COUNT == 0 && ARCHIVE_COUNT == 0 )); then
  echo "No OpenSpec changes (openspec/changes/ or archive/)."
  exit 0
fi

# Default (no explicit count): list ALL active changes when any spec is
# unfinished, so in-progress work is never hidden by the default limit.
if [[ "$COUNT_EXPLICIT" == "false" ]] && (( UNFINISHED_COUNT > 0 )); then
  LIMIT="$CHANGE_COUNT"
else
  LIMIT="$REQUESTED"
  if (( CHANGE_COUNT > 0 && LIMIT > CHANGE_COUNT )); then
    LIMIT="$CHANGE_COUNT"
  fi
fi

ARCHIVE_LIMIT="$REQUESTED"
if (( ARCHIVE_COUNT > 0 && ARCHIVE_LIMIT > ARCHIVE_COUNT )); then
  ARCHIVE_LIMIT="$ARCHIVE_COUNT"
fi

sanitize_cell() {
  local value="${1:-}"
  value="${value//$'\n' / }"
  value="${value//|/·}"
  value="${value//$'\t'/ }"
  printf '%s' "$value"
}

html_escape() {
  local value="${1:-}"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  value="${value//\"/&quot;}"
  printf '%s' "$value"
}

format_md_cell() {
  local value="${1:-}"
  local bold="${2:-false}"
  local clean
  clean="$(sanitize_cell "$value")"
  if [[ "$bold" == "true" ]]; then
    printf '**%s**' "$clean"
  else
    printf '%s' "$clean"
  fi
}

format_html_cell() {
  local value="${1:-}"
  local bold="${2:-false}"
  local clean
  clean="$(html_escape "$(sanitize_cell "$value")")"
  if [[ "$bold" == "true" ]]; then
    printf '<strong>%s</strong>' "$clean"
  else
    printf '%s' "$clean"
  fi
}

count_tasks_from_file() {
  local tasks_file="$1"
  if [[ ! -f "$tasks_file" ]]; then
    printf '0/0'
    return
  fi
  local total done
  total="$(grep -cE '^- \[[ xX]\]' "$tasks_file" 2>/dev/null || true)"
  done="$(grep -cE '^- \[[xX]\]' "$tasks_file" 2>/dev/null || true)"
  printf '%s/%s' "$done" "$total"
}

modified_from_archive_dir() {
  local dir_name="$1"
  if [[ "$dir_name" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2}) ]]; then
    printf '%sT00:00:00.000Z' "${BASH_REMATCH[1]}"
  else
    stat -c '%y' "$ARCHIVE_DIR/$dir_name" 2>/dev/null | cut -d. -f1 | tr ' ' 'T' || printf 'unknown'
  fi
}

# Row fields: idx name schema tasks status artifacts artifacts_ok modified bold
ROWS=()

collect_active_rows() {
  if (( CHANGE_COUNT == 0 )); then
    return
  fi
  local idx=0
  while IFS= read -r name; do
    idx=$((idx + 1))
    change_row="$(jq -r --arg n "$name" '.changes[] | select(.name == $n)' <<<"$LIST_JSON")"
    completed="$(jq -r '.completedTasks' <<<"$change_row")"
    total="$(jq -r '.totalTasks' <<<"$change_row")"
    list_status="$(jq -r '.status' <<<"$change_row")"
    modified="$(jq -r '.lastModified' <<<"$change_row")"

    status_json="$(openspec status --change "$name" --json 2>/dev/null || echo '{}')"
    schema="$(jq -r '.schemaName // "unknown"' <<<"$status_json")"
    is_complete="$(jq -r '.isComplete // false' <<<"$status_json")"
    artifacts_summary="$(jq -r '
      if (.artifacts | length) == 0 then "none"
      else ([.artifacts[] | "\(.id):\(.status)"] | join("|"))
      end
    ' <<<"$status_json")"

    tasks="${completed}/${total}"
    row_bold="false"
    if [[ "$list_status" == "complete" ]]; then
      row_bold="true"
    fi

    ROWS+=("$idx|$name|$schema|$tasks|$list_status|$artifacts_summary|$is_complete|$modified|$row_bold")
  done < <(jq -r --argjson limit "$LIMIT" '
    ([.changes[] | select(.status != "complete")]
     + [.changes[] | select(.status == "complete")])
    | .[:$limit][] | .name
  ' <<<"$LIST_JSON")
}

collect_archived_rows() {
  if (( ARCHIVE_LIMIT == 0 )); then
    return
  fi
  local idx="${#ROWS[@]}"
  for (( i = 0; i < ARCHIVE_LIMIT; i++ )); do
    idx=$((idx + 1))
    archive_path="${ARCHIVED_DIRS[$i]}"
    dir_name="$(basename "$archive_path")"
    tasks_file="${archive_path}/tasks.md"
    tasks="$(count_tasks_from_file "$tasks_file")"
    modified="$(modified_from_archive_dir "$dir_name")"
    schema="spec-driven"
    if [[ -f "${archive_path}/.openspec.yaml" ]]; then
      schema="$(grep -E '^schema:' "${archive_path}/.openspec.yaml" 2>/dev/null | awk '{print $2}' | tr -d '"' || echo "spec-driven")"
    fi
    ROWS+=("$idx|$dir_name|$schema|$tasks|archived|archived|true|$modified|true")
  done
}

collect_active_rows
collect_archived_rows

REQUESTED_LABEL="$REQUESTED"
if [[ "$COUNT_EXPLICIT" == "false" ]] && (( UNFINISHED_COUNT > 0 )); then
  REQUESTED_LABEL="all (default: unfinished specs present)"
fi

print_markdown() {
  echo "OpenSpec changes — **${LIMIT}** active of **${CHANGE_COUNT}** (unfinished first, then complete) + **${ARCHIVE_LIMIT}** archived of **${ARCHIVE_COUNT}** (requested: ${REQUESTED_LABEL})"
  echo ""
  echo "_Rows in **bold**: tasks complete or archived._"
  echo ""
  echo "| # | name | schema | tasks | status | artifacts | artifacts_ok | modified |"
  echo "|---:|---|---|---:|---|---|---|---|"

  local row
  for row in "${ROWS[@]}"; do
    IFS='|' read -r idx name schema tasks status artifacts artifacts_ok modified row_bold <<<"$row"
    printf '| %d | %s | %s | %s | %s | %s | %s | %s |\n' \
      "$idx" \
      "$(format_md_cell "$name" "$row_bold")" \
      "$(format_md_cell "$schema" "$row_bold")" \
      "$(format_md_cell "$tasks" "$row_bold")" \
      "$(format_md_cell "$status" "$row_bold")" \
      "$(format_md_cell "$artifacts" "$row_bold")" \
      "$(format_md_cell "$artifacts_ok" "$row_bold")" \
      "$(format_md_cell "$modified" "$row_bold")"
  done
}

write_html() {
  local iso_utc display
  iso_utc="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
  display="$(TZ=Europe/Madrid date +'%Y-%m-%d %H:%M:%S Europe/Madrid')"

  mkdir -p "$(dirname "$HTML_PATH")"

  {
    cat <<'HTMLHEAD'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenSpec changes</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, sans-serif; margin: 1.5rem; line-height: 1.45; }
    h1 { font-size: 1.35rem; margin-bottom: 0.25rem; }
    .meta { color: #555; font-size: 0.9rem; margin-bottom: 1rem; }
    .legend { font-size: 0.9rem; margin-bottom: 1rem; }
    table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
    th, td { border: 1px solid #ccc; padding: 0.4rem 0.55rem; text-align: left; vertical-align: top; }
    th { background: #f0f0f0; position: sticky; top: 0; }
    tr.complete td, tr.archived td { font-weight: 600; }
    td.num { text-align: right; width: 2.5rem; }
    td.status-complete { color: #0a6b0a; }
    td.status-archived { color: #555; }
    td.status-in-progress { color: #b45309; }
    @media (prefers-color-scheme: dark) {
      th { background: #2a2a2a; }
      th, td { border-color: #444; }
      .meta { color: #aaa; }
      td.status-complete { color: #6ee76e; }
      td.status-in-progress { color: #fbbf24; }
    }
  </style>
</head>
<body>
  <h1>OpenSpec changes</h1>
HTMLHEAD
    printf '  <p class="meta">Generado: <time datetime="%s">%s</time> · repo: %s</p>\n' \
      "$iso_utc" "$display" "$(basename "$ROOT")"
    printf '  <p class="meta"><strong>%s</strong> active of <strong>%s</strong> (unfinished first, then complete) + <strong>%s</strong> archived of <strong>%s</strong> (requested: %s)</p>\n' \
      "$LIMIT" "$CHANGE_COUNT" "$ARCHIVE_LIMIT" "$ARCHIVE_COUNT" "$REQUESTED_LABEL"
    echo '  <p class="legend">Rows in <strong>bold</strong> (and highlighted rows): tasks <code>complete</code> or <code>archived</code>.</p>'
    echo '  <table>'
    echo '    <thead><tr>'
    echo '      <th class="num">#</th><th>name</th><th>schema</th><th>tasks</th><th>status</th>'
    echo '      <th>artifacts</th><th>artifacts_ok</th><th>modified</th>'
    echo '    </tr></thead>'
    echo '    <tbody>'

    local row idx name schema tasks status artifacts artifacts_ok modified row_bold
    local row_class status_class
    for row in "${ROWS[@]}"; do
      IFS='|' read -r idx name schema tasks status artifacts artifacts_ok modified row_bold <<<"$row"
      row_class=""
      status_class=""
      if [[ "$status" == "complete" ]]; then
        row_class="complete"
        status_class="status-complete"
      elif [[ "$status" == "archived" ]]; then
        row_class="archived"
        status_class="status-archived"
      elif [[ "$status" == "in-progress" ]]; then
        status_class="status-in-progress"
      fi
      printf '      <tr class="%s">\n' "$row_class"
      printf '        <td class="num">%s</td>\n' "$(format_html_cell "$idx" "$row_bold")"
      printf '        <td>%s</td>\n' "$(format_html_cell "$name" "$row_bold")"
      printf '        <td>%s</td>\n' "$(format_html_cell "$schema" "$row_bold")"
      printf '        <td>%s</td>\n' "$(format_html_cell "$tasks" "$row_bold")"
      printf '        <td class="%s">%s</td>\n' "$status_class" "$(format_html_cell "$status" "$row_bold")"
      printf '        <td>%s</td>\n' "$(format_html_cell "$artifacts" "$row_bold")"
      printf '        <td>%s</td>\n' "$(format_html_cell "$artifacts_ok" "$row_bold")"
      printf '        <td>%s</td>\n' "$(format_html_cell "$modified" "$row_bold")"
      echo '      </tr>'
    done

    echo '    </tbody>'
    echo '  </table>'
    echo '</body>'
    echo '</html>'
  } >"$HTML_PATH"

}

open_html_in_chrome() {
  local abs_path file_url
  abs_path="$(realpath "$HTML_PATH")"
  file_url="file://${abs_path}"

  if [[ "$OPEN_CHROME" != "true" ]]; then
    echo ""
    echo "HTML report: ${file_url}"
    return 0
  fi

  if command -v google-chrome >/dev/null 2>&1; then
    google-chrome "$file_url" >/dev/null 2>&1 &
  elif command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser "$file_url" >/dev/null 2>&1 &
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$file_url" >/dev/null 2>&1 &
  else
    echo ""
    echo "openspec-list: no browser found — open manually: ${file_url}" >&2
    return 1
  fi

  echo ""
  echo "HTML report opened in browser: ${file_url}"
}

print_markdown
write_html
open_html_in_chrome
