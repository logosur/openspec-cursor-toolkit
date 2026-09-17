Claude Code solo carga este archivo y `.claude/rules/*.md`; `.cursor/rules/*.mdc` NO se cargan solos — ver índice final.

# openspec-cursor-toolkit

**Qué es:** fuente de verdad del toolkit OpenSpec (commands, skills, rules, `docs/openspec/`) que se **exporta** a proyectos consumidores. Stack-agnostic: el consumidor aporta su rule de stack (`01-project-stack-quality-gate.mdc` o su `CLAUDE.md`).

**Qué NO es:** no es app; no contiene `openspec/` de producto, solo sus propios changes (`openspec/changes/<slug>/`). Se cambia la fuente y se exporta; no se parchea por proyecto.

## Export

- `/exporta-spec <slug>` | `/exporta-spec all` | `/exporta-spec command|skill <slug>`.
- Flujo: bundle `<ai-developer>/templates/openspec-claude/<slug>/bundle.manifest` → `bash <ai-developer>/scripts/exporta-spec.sh --slug <slug> --projects-base "$PROJECTS_BASE"` (o `--all`). Diff `cmp -s`: NEW/UPDATE/SKIP; `--force` solo si se pide.
- `PROJECTS_BASE` defecto `$HOME/projects`; si no existe, preguntar (exit 2), nunca adivinar.
- Script en clon externo: `/home/ivan/projects/htdocs/auladrupal/ai-developer/scripts/exporta-spec.sh` (no aquí). Si falta: parar e informar.
- Registro `<PROJECTS_BASE>/.claude-local/export-spec/` y `.claude/context/export-spec/`: gitignored, nunca commitear.
- Tras exportar: pegar lista completa `## EXPORT_TARGETS` en chat.

## Layout

- `.cursor/{commands,skills,rules/*.mdc}` paquete Cursor original.
- `.claude/{commands,skills/*/SKILL.md}` espejo nativo Claude Code; rules `.mdc` plegadas en `SKILL.md`.
- `.{cursor,claude}/scripts/openspec-list.sh` listado de changes.
- `docs/openspec/` índice, prompts, templates; compartido.
- `.{cursor,claude}/context/` salida de sesión, gitignored.

## Invariantes

- **Paridad `.cursor/` ↔ `.claude/`**: mismo set de commands (idéntico hoy) y skills. Cambio en uno → replicar en otro. `.claude/skills` tiene 4 extra que en Cursor son solo rule: `00-openspec-stack-agnostic`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore`.
- Rule `.mdc` con skill homónima: cambiar contenido → actualizar también `SKILL.md`.
- `.cursor/skills/README.md` y `.claude/skills/README.md` al día al añadir/renombrar.
- Nombres kebab-case; alias ES (`prepara-tarea`, …) + OPSX EN (`opsx-*`); serie numerada `00-`..`40-`.
- Frontmatter: commands `description` (+ `argument-hint`); skills `name` + `description` con triggers.
- Nunca hardcodear host/puerto/comandos ajenos.
- Prohibido: `git commit/push/merge` sin orden; commitear registros export; cerrar apply/verify sin evidencia; aflojar aserciones E2E; deploy sin diálogo (`run-spec` para en gate).
- Fases `repasa-spec`/`run-spec` secuenciales, nunca paralelas. Gate se lee de disco (`GAPS.md`, `tasks.md`), no de lo que afirme un agente.

## Qué .mdc leer según el tema (`.cursor/rules/`)

| Tema | Archivo |
|---|---|
| Stack-agnostic | `00-openspec-stack-agnostic.mdc` |
| Spec fuerte / workflow | `00-openspec-master.mdc`, `00-openspec-orchestrator.mdc`, `openspec-workflow.mdc` |
| Refactor SOLID/DI | `10-openspec-refactor-solid.mdc` |
| Hidratar proposals | `20-openspec-hydrate-spec.mdc`, `20-hydrate-spec.mdc` |
| Anti-alucinación | `30-openspec-anti-hallucination.mdc`, `openspec-anti-hallucination.mdc` |
| Apply seguro, scope, evidencia | `40-openspec-safe-apply.mdc` |
| Gap analysis / GAPS.md | `openspec-gap-analysis.mdc` |
| Pipeline `/repasa-spec` | `repasa-spec-openspec-pipeline.mdc` |
| Loop `/run-spec` | `run-spec-openspec-loop.mdc` |
| Supervisor multi-sesión | `supervisa-sesiones-multisesion.mdc` |
| `/verifica-tarea`, `/comando-verificar` | `verifica-tarea-openspec-a-fondo.mdc`, `comando-verificar-a-fondo.mdc` |
| `/qa`, `/html` | `comando-qa.mdc`, `comando-html.mdc` |
| `/exporta-spec` | `comando-exporta-spec.mdc` |
| Multiagente | `hazlo-en-modo-multiagente.mdc` |
| Cierre de sesión | `cierra-sesion-check.mdc` |
| E2E regresión | `openspec-e2e-regression-guard.mdc` |
| Spec desde .doc/.docx | `openspec-extract-spec-from-doc.mdc` |
| gitignore artefactos | `openspec-fix-changes-gitignore.mdc` |
| RUNE specs | `rune-specs.mdc` |
