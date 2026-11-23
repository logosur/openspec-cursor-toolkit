Claude Code solo carga este archivo y `.claude/rules/*.md`; `.cursor/rules/*.mdc` NO se cargan solos — ver índice final.

# openspec-skills-toolkit

**Qué es:** toolkit **global de Claude Code** (repo público): se instala una vez por máquina en `~/.claude` con `./install.sh install` (por defecto `openspec`, `core`, `devtools`; opcionales `sessions`, `supervision`, `heavy-jobs`) y se personaliza con un **override privado fuera del repo** (`~/.config/claude-toolkit/`). Incluye el catálogo OpenSpec (commands, skills, `docs/openspec/`), que además se sigue **exportando** por proyecto; Cursor (`.cursor/`) es destino secundario. Stack-agnostic: el consumidor aporta su rule de stack (`01-project-stack-quality-gate.mdc` o su `CLAUDE.md`).

**Qué NO es:** no es app; no contiene `openspec/` de producto, solo sus propios changes (`openspec/changes/<slug>/`). Se cambia la fuente y se instala o exporta; no se parchea por proyecto ni por máquina (lo personal va al override).

## Export

- `/exporta-spec <slug>` | `/exporta-spec all` | `/exporta-spec command|skill <slug>`.
- Flujo: bundle `<ai-developer>/templates/openspec-cursor/<slug>/bundle.manifest` → `bash <ai-developer>/scripts/exporta-spec.sh --slug <slug> --projects-base "$PROJECTS_BASE"` (o `--all`). Diff `cmp -s`: NEW/UPDATE/SKIP; `--force` solo si se pide.
- `PROJECTS_BASE` defecto `$HOME/projects`; si no existe, preguntar (exit 2), nunca adivinar.
- Script en clon externo: `<ai-developer>/scripts/exporta-spec.sh` (ruta local del clon, fuera de este repo) (no aquí). Si falta: parar e informar.
- Registro `<PROJECTS_BASE>/.claude-local/export-spec/` y `.claude/context/export-spec/`: gitignored, nunca commitear.
- Tras exportar: pegar lista completa `## EXPORT_TARGETS` en chat.

## Layout

- `.cursor/{commands,skills,rules/*.mdc}` paquete Cursor original.
- `.claude/{commands,skills/*/SKILL.md}` espejo nativo Claude Code; rules `.mdc` plegadas en `SKILL.md`.
- `.{cursor,claude}/scripts/openspec-list.sh` listado de changes.
- `docs/openspec/` índice, prompts, templates; compartido.
- `install.sh` + `scripts/toolkit/` instalador (install, uninstall, status, verify, drift, pull, equivalence) y sus tests (`scripts/toolkit/tests/`, siempre en un `HOME` temporal).
- `global/` lo que instalan los módulos que no es catálogo: `modules/*.yaml` (manifiestos), `hooks/`, `scripts/` (+ `lib/toolkit_config.py`), `rules/`, `skills/`, `CLAUDE.md` (bloque gestionado), `config/<pieza>.json` (valores por defecto), `settings/hooks.*.json` (fragmentos de hooks) y `contracts/<pieza>.yaml` (sondas).
- `examples/override/` override de ejemplo; el real nunca entra en el repo.
- `scripts/` validador del catálogo, comprobador de privacidad (`privacy-check.py`, patrones y excepciones), sus tests; herramienta de este repo, no se instala ni se exporta.
- `.{cursor,claude}/context/` salida de sesión, gitignored.

## Invariantes

- **Paridad `.cursor/` ↔ `.claude/`**: mismo set de commands (idéntico hoy) y skills. Cambio en uno → replicar en otro. `.claude/skills` tiene 4 extra que en Cursor son solo rule: `00-openspec-stack-agnostic`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore`. Lo comprueba `scripts/validate-toolkit.py`; toda asimetría se declara, con motivo, en `scripts/catalog-exceptions.yaml`.
- Rule `.mdc` con skill homónima: cambiar contenido → actualizar también `SKILL.md`.
- `.cursor/skills/README.md` y `.claude/skills/README.md` nombran cada carpeta de skill de su árbol (lo comprueba el validador).
- Nombres kebab-case; alias ES (`prepara-tarea`, …) + OPSX EN (`opsx-*`); serie numerada `00-`..`40-`.
- Frontmatter: commands `description` (+ `argument-hint`); skills `name` (= carpeta) + `description`. YAML válido y claves permitidas: lo comprueba el validador.
- Routing: skill invocable → `description` con qué + cuándo (`Use when`/`Use on`/`Auto-invoke on`/`Triggers on`), frases sacadas del repo, ≤ 1024 car., sin colisión TF-IDF ≥ 0.50. Duplicado → alias obsoleto (`Deprecated alias of <canónica>`, `disable-model-invocation: true`), nunca borrar.
- Antes de cerrar un cambio del catálogo: `python3 -m unittest scripts/test_validate_toolkit.py && python3 scripts/validate-toolkit.py` (CI lo repite en cada push/PR). Detalle en `README.md` → «Validate the catalog».
- Nunca hardcodear host/puerto/comandos ajenos.
- **Dos fuentes, ninguna copia:** el catálogo vive solo en `.claude/` (el módulo `openspec` lo instala desde ahí) y lo demás en `global/`. La paridad compara `.claude/` ↔ `.cursor/`; `global/` no entra en ella.
- **Cada fichero de `global/` pertenece a un solo módulo**; todo hook instalado tiene contrato en `global/contracts/`; una pieza solo cita lo que instala su módulo o sus dependencias (lo comprueba el validador, reglas `global-*`).
- **Nada de una máquina concreta en `global/`:** rutas, hosts, proyectos y listas van a una pieza de config (`global/config/<pieza>.json`, leída con `toolkit_config.load`) con valor por defecto genérico; el valor real, al override. Un hook con la config rota falla abierto.
- **Privacidad antes de cada commit:** `python3 scripts/privacy-check.py --staged --require-private` y `--message <fichero>` en 0; nada personal (IPs, correos, UUID de cuentas, rutas de home, nombres de proyectos o clientes, citas literales) entra en el repo. Ante la duda, al override.
- **Las piezas solo se ejecutan en un `HOME` temporal** (`verify`, tests, `equivalence`); el `~/.claude` real solo se lee.
- Antes de cerrar un cambio del instalador o de `global/`: `python3 -m unittest discover -s scripts/toolkit/tests -t .` además de las pruebas del catálogo.
- Prohibido: `git commit/push/merge` sin orden; commitear registros export; cerrar apply/verify sin evidencia; aflojar aserciones E2E; deploy sin diálogo (`run-spec` para en gate).
- Fases `repasa-spec`/`run-spec` secuenciales, nunca paralelas. Gate se lee de disco (`GAPS.md`, `tasks.md`), no de lo que afirme un agente.

## Qué .mdc leer según el tema (`.cursor/rules/`)

| Tema | Archivo |
|---|---|
| Stack-agnostic | `00-openspec-stack-agnostic.mdc` |
| Spec fuerte / workflow | `00-openspec-master.mdc`, `00-openspec-orchestrator.mdc`, `openspec-workflow.mdc` |
| Refactor SOLID/DI | `10-openspec-refactor-solid.mdc` |
| Hidratar proposals | `20-openspec-hydrate-spec.mdc` (`20-hydrate-spec`: alias obsoleto) |
| Anti-alucinación | `30-openspec-anti-hallucination.mdc` (`openspec-anti-hallucination`: alias obsoleto) |
| Apply seguro, scope, evidencia | `40-openspec-safe-apply.mdc` |
| Gap analysis / GAPS.md | `openspec-gap-analysis.mdc` |
| Pipeline `/repasa-spec` | `repasa-spec-openspec-pipeline.mdc` |
| Loop `/run-spec` | `run-spec-openspec-loop.mdc` |
| `/verifica-tarea`, `/comando-verificar` | `verifica-tarea-openspec-a-fondo.mdc`, `comando-verificar-a-fondo.mdc` |
| `/qa`, `/html` | `comando-qa.mdc`, `comando-html.mdc` |
| `/exporta-spec` | `comando-exporta-spec.mdc` |
| Multiagente | `hazlo-en-modo-multiagente.mdc` |
| Cierre de sesión | `cierra-sesion-check.mdc` |
| E2E regresión | `openspec-e2e-regression-guard.mdc` |
| Spec desde .doc/.docx | `openspec-extract-spec-from-doc.mdc` |
| gitignore artefactos | `openspec-fix-changes-gitignore.mdc` |
| RUNE specs | `rune-specs.mdc` |
