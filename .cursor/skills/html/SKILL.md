---
name: html
description: Opens the requested document as HTML in system Chrome. Use on /html, abreme en chrome html, abre el html, open html in chrome, muestra el informe en chrome.
---

# HTML — abrir en Chrome

> **Command:** `.cursor/commands/html.md`  
> **Rule (L2):** `.cursor/rules/comando-html.mdc`

Shortcut for: **“abreme lo que te he pedido en chrome html”**. Resolves the target artifact, ensures an `.html` file exists, opens it in **host Chrome** — never the IDE browser for human viewing.

---

## Preconditions

- Artifact path inside the repo (or explicit `file://` the developer named).
- Display available on host; if headless CI → report blocker, do not fake success.

---

## Phase 1 — Resolve target

### Explicit scope

| Input | Resolution |
|-------|------------|
| Path ending in `.html` | `realpath` from repo root; must exist |
| Path ending in `.md` | Twin `<basename>.html` same directory |
| Basename without extension | `find` under search roots for `<basename>.html` |
| `file:///…` URL | Strip scheme; validate file exists |

### Implicit scope (no argument)

1. Scan **current conversation** (newest first): paths matching `\.(html|md)$`, document titles, OpenSpec slugs, QA run folders.
2. If agent created/updated files this session → prefer those under search roots.
3. **Tie-break:** highest mtime among ≤3 best matches.

### Search roots

```
.cursor/context/
.cursor/QAtest/
tests/playwright-full-order/evidence/
documentacion/
tmp/
```

```bash
# Example: latest report.html in evidence
find tests/playwright-full-order/evidence -name 'report.html' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1
```

---

## Phase 2 — Ensure HTML exists

| State | Action |
|-------|--------|
| `.html` exists | Proceed to Phase 3 |
| Only `.md` exists | Generate HTML twin (`documents-md-and-html.mdc`): semantic structure, inline CSS, timestamp if informe (`qa-reports-timestamp-mandatory.mdc`) |
| Neither exists | **STOP** — list closest matches; do not invent paths |
| Stale `.html` (md newer) | Regenerate HTML from MD, then open |

Minimal HTML shell when generating from MD:

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title><!-- basename --></title>
  <style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;line-height:1.5}</style>
</head>
<body><!-- rendered content --></body>
</html>
```

---

## Phase 3 — Open in Chrome

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
ABS="${REPO_ROOT}/.cursor/context/…/doc.html"
google-chrome "file://${ABS}"
```

Fallback chain (same `file://` URL):

```bash
google-chrome "file://${ABS}" \
  || chromium-browser "file://${ABS}" \
  || xdg-open "file://${ABS}"
```

**Forbidden for human viewing:** `browser_navigate`, Cursor IDE browser, Glass, `open_resource` for web preview (`open-links-in-chrome-not-ide.mdc`).

MCP browser is allowed only when the **same turn** also needs automated inspection — still open Chrome for the developer to see the file.

---

## Phase 4 — Reply

Include in the message:

1. **Absolute path** and **relative path** from repo root.
2. Full **`file://`** URL (no shortening).
3. Whether Chrome command ran (exit code).
4. If HTML was generated this turn: note “gemelo creado desde `.md`”.

```markdown
## Verification
- **Verified:** `test -f <abs-path>`; `google-chrome "file://…"` exit 0
```

---

## Common targets

| Developer says | Likely file |
|----------------|-------------|
| “el informe QA” | Latest `qa-report-*.html` in `.cursor/QAtest/` or `documentacion/` |
| “la matriz” | `.cursor/context/verification/<slug>/matrix.html` |
| “el reporte e2e” | `tests/playwright-full-order/evidence/**/report.html` (newest) |
| “lo que acabas de generar” | Last written `*.html` this session |

---

## Anti-patterns — forbidden

1. **“Ábrelo tú en el navegador”** without running `google-chrome` (VR-07 spirit).
2. **IDE browser** as default for the developer to view the report.
3. **Opening `.md`** in Chrome when `.html` twin should exist — generate first.
4. **Wrong file** — opening unrelated HTML without matching conversation context.
5. **Truncated `file://` URLs** in chat.

---

## Integration

| Related | When |
|---------|------|
| `qa-reports-open-chrome.mdc` | Agent **generates** HTML → auto-open same turn |
| `/html` | Developer **asks to open** existing or contextual HTML later |
| `documents-md-and-html.mdc` | Create/regenerate twins |
| `open-local-artifacts-in-file-explorer.mdc` | “en el explorador” → `xdg-open` folder, not `/html` |
