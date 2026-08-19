---
name: /html
id: html
category: Presentation
description: "Open the requested artifact as HTML in Chrome — resolve path from context or argument"
---

# Abrir HTML en Chrome

When the developer invokes **`/html`**, **`abreme lo que te he pedido en chrome html`**, **`abre en chrome`**, **`abre el html`**, **`open html in chrome`**, or **`muestra el informe en chrome`**, open the **HTML version** of what they asked for in **system Chrome** (not the IDE browser).

## Mandatory (this turn)

1. Read **`.cursor/skills/html/SKILL.md`** in the same turn before executing.
2. Load **`.cursor/rules/comando-html.mdc`** (L2).
3. Resolve target → ensure `.html` exists → run Chrome open command → confirm path in reply.

## Scope parsing

Optional scope on the same line or following lines:

| Scope token | Example | Action |
|-------------|---------|--------|
| Absolute/relative path | `/html .cursor/context/informes/bug-500.html` | Resolve to repo-absolute `.html` |
| Basename | `/html matrix` | Find `matrix.html` under search roots (most recent mtime wins) |
| MD twin | `/html informe-cobertura.md` | Open paired `informe-cobertura.html`; generate if missing |
| *(omitted)* | `/html` | Resolve from **conversation context** — last document/artifact the developer asked for |

## Resolution priority (when scope omitted)

1. Last explicit `.html` or `.md` path cited in the **current chat** (developer or agent).
2. Last artifact **created or updated this session** under search roots.
3. If still ambiguous → list ≤3 candidates with mtime; pick the one that best matches the last user request; if tie, most recent mtime.

## Search roots (in order)

| Root | Typical content |
|------|-----------------|
| `.cursor/context/` | Informes, matrices, evidencia, planes |
| `.cursor/QAtest/` | QA HTML reports |
| `tests/playwright-full-order/evidence/` | E2E evidence `report.html` |
| `documentacion/` | Stakeholder QA HTML |
| `tmp/` | Salidas temporales |

## If only `.md` exists

Generate the **HTML twin** first (`documents-md-and-html.mdc`): same basename, semantic HTML, inline `<style>` for `file://`. Then open it.

## Chrome command (agent runs it)

```bash
google-chrome "file:///absolute/path/to/document.html"
```

Fallbacks: `chromium-browser`, then `xdg-open` on the same `file://` URL.

**Prohibited:** `browser_navigate`, IDE preview, or “ábrelo tú” without running the command (`open-links-in-chrome-not-ide.mdc`).

## Close format

```markdown
## Verification
- **Verified:** Chrome open — `google-chrome "file:///…"` exit 0; file exists at `<absolute-path>`

## Resumen
- Ruta absoluta y `file://` citadas; Chrome abierto en esta interacción.
```

If no display/browser: state once — do not claim Chrome opened.

## Related

| Item | Role |
|------|------|
| `.cursor/skills/html/SKILL.md` | Full resolution + HTML generation workflow |
| `.cursor/rules/comando-html.mdc` | L2 triggers and prohibitions |
| `open-links-in-chrome-not-ide.mdc` | Chrome on host, not IDE |
| `documents-md-and-html.mdc` | MD/HTML/PDF twins |
| `qa-reports-open-chrome.mdc` | Auto-open after **generating** reports |
