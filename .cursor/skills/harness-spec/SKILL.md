---
name: harness-spec
description: Build a persistent, re-runnable test harness for an OpenSpec spec/change plus an independent supervisor agent that gates compliance. Auto-invoke on /harness-spec, crea un harness para la spec, harness de verificación, supervisor de la spec, verificador independiente.
---

# Harness spec — persistent harness + independent supervisor verifier

> **Command:** `.claude/commands/harness-spec.md`
> **OpenSpec:** `openspec/changes/<slug>/specs/**/spec.md` or `openspec/specs/<capability>/spec.md`
> **Stack:** Symfony/PHPUnit (`apps/api`), Next.js/Playwright (`apps/web`), Docker Compose

When `/harness-spec [<target>]` runs, read this skill in the same turn and execute Phases 0–6.

## Qué es esto y en qué se diferencia

`/verifica-tarea` y `/comando-verificar` producen una **matriz de verificación de un solo uso**, escrita por la **misma sesión** que implementó o revisó el cambio — el mismo agente se audita a sí mismo, en la misma conversación, con memoria de sus propias decisiones. Eso funciona para el cierre habitual de una tarea, pero tiene un punto ciego estructural: el "generador" y el "verificador" son la misma mente, así que el sesgo de autoevaluación (self-grading bias) y el reward hacking (aflojar aserciones, mockear el límite exacto que se debía probar, marcar escenarios como skipped) no se detectan solos.

`/harness-spec` construye dos cosas que **persisten más allá del turno**:

1. **Un harness real y re-ejecutable** — tests PHPUnit/Playwright mapeados 1:1 a los Requirements/Scenarios de la spec, versionados en los árboles de test normales del repo, más un runner script y un manifest que permiten volver a ejecutarlos en cualquier momento (o en CI) sin releer esta conversación.
2. **Un supervisor independiente** — un subagente lanzado en **contexto fresco** (sin la conversación de implementación), que solo recibe la spec y el harness, **re-ejecuta el harness él mismo** (no confía en cifras reportadas) y caza activamente señales de gaming antes de dar un veredicto.

Usar `/harness-spec` para cambios de alto riesgo (auth/autorización, scoping multi-tenant, ciclos regulatorios EINF/APA-EGAR, billing) donde "el código se ve bien" o "los tests pasan" no es prueba suficiente. Para el cierre habitual de una tarea, `/verifica-tarea` sigue siendo el flujo por defecto.

## Fundamento (investigado, julio 2026)

- **Independencia estructural generador/verificador.** El patrón con mejores resultados separa quién implementa de quién verifica en agentes distintos, sin historial de conversación compartido, donde el verificador trabaja desde el contrato (la spec) y no desde el razonamiento del implementador — no desde su propio resumen de lo que hizo. ([LLM-as-Judge in Production, Zylos Research 2026](https://zylos.ai/research/2026-04-10-llm-as-judge-production-agent-verification-2026/); [Meta-Engineering Harnesses for AI-Native Software Production](https://arxiv.org/pdf/2605.25665))
- **Verificar es ahora más difícil que generar.** A medida que los modelos mejoran generando código complejo, la verificación fiable —no la generación— es el cuello de botella; todo verificador es un proxy de la intención real, nunca la intención misma, así que el hueco entre "pasa el proxy" y "cumple la spec" hay que cerrarlo por diseño, no dando por hecho que un test verde implica cumplimiento. ([The Verification Horizon: No Silver Bullet for Coding Agent Rewards](https://arxiv.org/abs/2606.26300))
- **Los rewards basados en tests reducen el gaming de forma medible.** Sustituir "confía en el reporte" por "recompensa/gate atado a tests reales del contrato" bajó las resoluciones con trampa del 28.57% al 0.56% en el estudio citado — de ahí que el harness deba ser tests ejecutables reales, no una checklist en prosa. ([The Verification Horizon](https://arxiv.org/abs/2606.26300))
- **Patrón Evaluator-Optimizer (Anthropic).** Un LLM genera, otro evalúa y da feedback estructurado, en bucle acotado hasta cumplir el criterio o agotar iteraciones — no bucle infinito, no auto-aprobación. ([Building Effective AI Agents, Anthropic](https://www.anthropic.com/engineering/building-effective-agents))
- **Ningún verificador es gratis ni infalible.** La calidad de una señal de verificación se mide en escalabilidad, fidelidad y robustez a la vez — de ahí que el harness combine capas mecánicas (PHPUnit/Playwright, deterministas, baratas) con una capa de juicio (el supervisor LLM) para lo que no es mecánicamente comprobable (intención de negocio, cobertura real de un escenario Gherkin, i18n).

## Preconditions

- Docker Compose local disponible para tests (`docker compose ps`); si no está arriba, levantar antes de Fase 3 (`npm run docker:up` si el desarrollador lo autoriza, o pedir que lo levante él).
- `openspec` CLI disponible (`openspec show`, `openspec status`, `openspec validate`).
- **El change target debe estar completo** (todas las tareas de `tasks.md` marcadas) — ver Fase 0.25. Si no lo está, el comando se niega a construir el harness salvo override explícito del desarrollador en el mismo turno.
- Nunca usar `--no-verify`, mocks del límite exacto bajo prueba, ni `markTestSkipped`/`test.skip` sin dejarlo explícito en el manifest como `BLOCKED`.

## Fase 0 — Resolver el target (spec o change)

**Caso A — argumento explícito:** primer token kebab-case tras `harness-spec` que resuelva a `openspec/changes/<slug>/` o `openspec/specs/<capability>/`. Ir a Fase 1.

**Caso B — sin argumento:** igual que `/sumario-spec` y `/verifica-tarea` — identificar qué specs/changes se han mencionado en la ventana de chat actual (rutas `openspec/changes/<slug>/...`, `openspec/specs/<capability>/...`, o slugs citados en el texto).

- **Ninguna detectada:** ejecutar `openspec list --json` y `openspec list --specs --json`; abrir **AskUserQuestion** en lenguaje natural y claro (no telegráfico) listando los changes/specs más recientes como opciones, explicando qué implica elegir cada una (p.ej. "construir el harness sobre el change en curso `add-x`, que todavía no está archivado" vs "sobre la spec canónica `y`, ya estable"). No adivinar.
- **Exactamente una detectada:** usarla directamente, sin preguntar.
- **Varias detectadas:** AskUserQuestion listando cada una como opción individual, explicando en una frase de qué trata cada spec/change para que el desarrollador elija con criterio.

Derivar `<slug>` (kebab-case) del change o capability elegido.

## Fase 0.25 — Gate de completitud del target (bloqueante, antes de nada más)

Un harness verifica que las conductas **ya implementadas** cumplen la spec; **no** verifica que la implementación esté terminada. Un harness verde sobre un change a medio implementar es engañoso: transmite sensación de cierre sin que el trabajo esté hecho. Caso real que motiva este gate: `add-waste-company-collaboration-lifecycle` con `tasks.md` a 32/35 y un harness que reportaba PASS — el contrato de comportamiento pasaba, pero el change no estaba completo, y el harness no lo revelaba.

Por eso, **cuando el target es un change** (`openspec/changes/<slug>/`), antes de construir o ejecutar absolutamente nada (Fase 0.5 incluida):

1. Comprobar el estado de las tareas con **evidencia real del repo, no de memoria**:
   - `openspec status --change "<slug>" --json` (si el CLI expone completitud del change), y
   - contar los checkboxes sin marcar en `openspec/changes/<slug>/tasks.md` — cualquier `- [ ]` pendiente cuenta como incompleto.
2. **Si queda una sola tarea sin completar** (uno o más `- [ ]`, o `openspec status` no marca el change como completo) → **negarse a construir el harness**. No crear ni editar tests, no ejecutar `run.sh`, no lanzar el supervisor, no escribir ningún artefacto en `.claude/context/verification/harness-<slug>/`. Parar aquí. En el chat, en el idioma del desarrollador:
   - Reportar el conteo `hechas/total` y la **lista literal** de las tareas pendientes (el texto de cada `- [ ]`).
   - Explicar en una frase por qué se para: un harness no certifica un change incompleto; hacerlo daría una falsa señal de cierre.
   - Indicar el camino correcto: terminar la implementación (`/aplica-tarea <slug>` o el flujo que corresponda) y volver a `/harness-spec` cuando `tasks.md` esté al 100%.
3. **Excepción única — override explícito del desarrollador en este mismo turno.** Solo si el propio mensaje pide a sabiendas construir el harness sobre el change incompleto (p.ej. "sé que está a 32/35, hazlo igual", "constrúyelo aunque falten tareas"), continuar — pero dejar constancia inequívoca en `STATUS.md` y en el `## Resumen` de cierre de que el harness se construyó sobre un change **incompleto** y qué tareas faltaban. Nunca asumir este override: si el mensaje no lo dice explícitamente, aplicar el gate y parar. La mera invocación de `/harness-spec` **no** es override.
4. **Spec canónica** (`openspec/specs/<capability>/`): este gate no aplica de forma bloqueante — una capability canónica ya es estable/archivada por definición. Continuar a Fase 0.5.

## Fase 0.5 — Evaluar proporcionalidad (obligatorio, antes de construir nada)

Construir un harness persistente + supervisor independiente tiene coste real: nuevos ficheros de test versionados, varias llamadas a subagente, y hasta 3 ciclos de evaluator-optimizer. No todas las specs lo justifican. Antes de tocar nada, valorar con evidencia del propio repo (no de memoria):

| Señal | Sentido |
|-------|---------|
| Auth/autorización, scoping multi-tenant/organización/rol, permisos | a favor |
| Ciclo regulatorio (EINF, certificación APA/EGAR, submission gateway ES/PT) | a favor |
| Dinero (billing, invoicing, coste) | a favor |
| Acciones destructivas/irreversibles, integridad de datos con escritura concurrente | a favor |
| La spec ya tuvo gaming/gaps detectados antes (`GAPS.md` previo con hallazgos) | a favor |
| Spec/change **doc-only**, **infra-only**, o solo copy/i18n | en contra |
| Change todavía en estado propuesta, sin requirements estables (`openspec validate` falla, o `tasks.md` apenas empezado) | en contra — mejor `/gaps-spec` o `/mejora-tarea` primero, construir un harness sobre una spec que aún se mueve es esfuerzo tirado |
| Ya existe una matriz `/verifica-tarea` reciente con 100% PASS y sin código tocado desde entonces | en contra — no reconstruir lo ya probado |
| Cambio trivial, sin lógica de negocio nueva | en contra |

Comprobar con comandos reales antes de decidir, no asumir: `openspec status --change "<slug>" --json`, `openspec validate "<slug>"`, `git log --oneline -- openspec/changes/<slug>` o `openspec/specs/<capability>`, y si existe, la última matriz en `.cursor/context/verification/openspec-<slug>/matrix.md` o `.claude/context/verification/openspec-<slug>/matrix.md`.

**Decisión:**

- **Señales claramente a favor y ninguna fuerte en contra** → seguir sin preguntar; dejar una línea de justificación en el resumen final (p.ej. "auth+scoping multi-tenant → harness completo").
- **Señales claramente en contra** (doc-only, infra-only, spec inestable, ya cubierta al 100%, cambio trivial) → **no** construir el harness completo. Explicar en 2-3 frases por qué, en el idioma del desarrollador, y sugerir la alternativa proporcionada (`/verifica-tarea` para cierre normal, `/gaps-spec` si la spec aún no está estable). Parar aquí salvo que el propio mensaje del desarrollador ya haya insistido explícitamente en construirlo igualmente.
- **Señales mixtas o insuficientes para decidir con confianza** → abrir **AskUserQuestion** en lenguaje natural, claro y bien explicado (no telegráfico): plantear qué implica cada opción y su coste/beneficio, por ejemplo:
  - *"Harness completo + supervisor independiente"* — construye tests persistentes mapeados a cada escenario y lanza un subagente en contexto fresco que los audita en un bucle de hasta 3 ciclos; es la opción más rigurosa pero también la más costosa en tiempo y en tests nuevos versionados.
  - *"Solo el harness de tests, sin el supervisor"* — crea/actualiza los tests mapeados a escenarios y los deja re-ejecutables, pero sin el gate independiente ni el bucle de reintento; más barato, útil si solo se quiere una suite de regresión trazable a la spec.
  - *"No construir nada aquí — usar `/verifica-tarea`"* — cierre habitual de un solo uso, sin persistir tests nuevos ni supervisor.
  Esperar la respuesta antes de continuar; no adivinar la intención del desarrollador cuando las señales están en conflicto.

## Fase 1 — Inventario de Requirements/Scenarios

1. `openspec show "<slug>" --json` (o `--type spec` para spec canónica); leer también `proposal.md`, `design.md`, `VERIFY.md` si existen.
2. Parsear cada `### Requirement` y `#### Scenario:` en `specs/**/spec.md`.
3. Asignar ids estables: `scenario_id = SC-<slug>-NN`, `req_id` tal como aparece en la spec.
4. Clasificar cada escenario por capa: `api` (PHPUnit/HTTP kernel test), `web` (Playwright), `service` (PHPUnit unit/service), `config`, `doc-only`.
5. Detectar si ya existe un harness previo en `.claude/context/verification/harness-<slug>/harness-manifest.json` → modo `update` (añadir escenarios nuevos, no duplicar tests existentes) en vez de `create`.

## Fase 2 — Construir/actualizar el harness (persistente)

Para **cada** `scenario_id`:

1. **Buscar si ya hay un test real que lo cubre** (`grep` en `apps/api/tests/**` y `apps/web/e2e/**` por el nombre del escenario o del requirement). Si existe y la aserción realmente comprueba el resultado declarado en el escenario → referenciarlo en el manifest, añadir el tag `@scenario SC-<slug>-NN` en un comentario si no lo tiene.
2. **Si no existe o es insuficiente**, escribir un test nuevo:
   - API/servicio → `apps/api/tests/Harness/<PascalSlug>HarnessTest.php`, extendiendo `DatabaseTestCase`/`ApiTestBootstrapTrait` como el resto de la suite; ejercer el mismo boundary HTTP/API Platform que un cliente real, nunca invocar el servicio saltándose la ruta cuando el escenario depende de ella.
   - Web/UI → `apps/web/e2e/harness-<slug>.spec.ts`, usando los helpers existentes (`apps/web/e2e/helpers/`), ejerciendo la misma ruta/flujo que un usuario real (sin bypass de auth ni de formularios).
   - Cada test method/case lleva un comentario de una línea `// @scenario SC-<slug>-NN` / `// @requirement REQ-...` — es lo que el supervisor usa para trazar cobertura.
3. **Prohibido en el test generado** (checklist anti-gaming, aplicar siempre):
   - Aserciones tautológicas (`assertTrue(true)`, `expect(1).toBe(1)`) o que solo comprueban que el código no lanza excepción.
   - `try/catch` que trague el fallo real del escenario.
   - Mockear el límite exacto que el escenario dice probar (DB, autorización, servicio externo, storage) — mockear solo lo que esté fuera del alcance del escenario.
   - Datos hardcodeados sustituyendo lo que la spec dice que debe venir de BD (viola la regla del proyecto "No Hardcoded Display Data").
   - `markTestSkipped()` / `test.skip()` sin dejar constancia explícita como `BLOCKED` en el manifest y el motivo.
4. Escribir/actualizar `.claude/context/verification/harness-<slug>/harness-manifest.md` (+ `.json` gemelo machine-readable) con columnas: `req_id | scenario_id | test_id (file::method o spec.ts title) | layer | status (covered/new/blocked)`.

## Fase 3 — Ejecutar el harness (comando real, ahora)

Crear/actualizar `.claude/scripts/harness/<slug>/run.sh` que ejecute exactamente el subconjunto del harness y escriba un JSON de resultado:

```bash
# API layer
docker compose exec -T api php bin/phpunit --filter='HarnessTest' --testdox

# Web layer
npm run test:e2e --workspace @residuos/web -- "apps/web/e2e/harness-<slug>.spec.ts"
```

Ejecutar `run.sh` en esta sesión, después del último cambio (nunca reusar resultados pre-edición). Guardar salida cruda + resumen estructurado en `.claude/context/verification/harness-<slug>/run-<timestamp>.json` (`scenario_id → PASS/FAIL/BLOCKED`, comando, exit code, duración).

## Fase 4 — Supervisor independiente (el gate real)

Este es el paso que no existe en `/verifica-tarea`/`/comando-verificar`: un **subagente en contexto fresco**, lanzado con la herramienta `Agent` (`subagent_type: general-purpose`, foreground — se necesita su veredicto antes de continuar), que **no ha visto esta conversación** ni la implementación. Prompt autocontenido con:

- Ruta a `specs/**/spec.md` del target (que lea él mismo los Requirements/Scenarios).
- Ruta a `harness-manifest.md`/`.json` y a los ficheros de test del harness.
- Ruta a `run.sh` — instrucción explícita de **re-ejecutarlo él mismo**, no confiar en el `run-<timestamp>.json` que reporta el orquestador.
- Checklist adversarial obligatoria:
  1. ¿Todo Requirement/Scenario de la spec tiene un test mapeado? (cobertura — listar los que no).
  2. Para cada test mapeado: ¿la aserción comprueba realmente el resultado que el escenario declara, leyendo la aserción, no solo confirmando que el test existe?
  3. ¿Hay aserciones aflojadas, excepciones tragadas, tests skipped/disabled sin justificar?
  4. ¿Algún test mockea el límite exacto (auth, persistencia, servicio externo) que el escenario dice probar?
  5. ¿Algún dato hardcodeado sustituye contenido que debería venir de BD?
  6. ¿El resultado de su propia re-ejecución coincide con el `run-<timestamp>.json` del orquestador? Si no coincide, marcarlo como discrepancia y fallar ese punto.
- Formato de salida exigido: veredicto por `req_id` (`PASS` / `FAIL` / `GAMED` / `NOT-COVERED`) + veredicto global (`PASS` solo si 100% `PASS`, cero `GAMED`/`NOT-COVERED`).

Escribir el veredicto tal cual lo devuelve el subagente en `.claude/context/verification/harness-<slug>/supervisor-verdict-<timestamp>.md` (+ `.html` gemelo si >8 filas). El orquestador **no edita ni suaviza** este fichero.

## Fase 5 — Bucle evaluator-optimizer (acotado)

- Si el veredicto global es `FAIL` → el orquestador corrige lo señalado (implementación y/o tests del harness — nunca aflojar la aserción para que pase), vuelve a Fase 3, y **relanza un supervisor en contexto fresco** (nueva llamada `Agent`, no reutilizar la anterior) para la Fase 4.
- **Máximo 3 ciclos.** Si tras 3 ciclos el veredicto sigue en `FAIL`, parar y dejarlo así de honesto en `STATUS.md` — no reintentar indefinidamente, no reportar éxito parcial como éxito.
- Actualizar `.claude/context/verification/harness-<slug>/STATUS.md` en cada ciclo: `iteration N/3`, veredicto global, ruta al último `supervisor-verdict-*.md`, pendientes.

## Fase 6 — Cierre

En el chat, en este orden:

1. **`## Verification`** (técnico) — target resuelto, `harness-manifest.md` path, `M/N` requirements con test mapeado, comando(s) ejecutados, `run-<timestamp>.json` path, `supervisor-verdict-<timestamp>.md` path, iteraciones usadas, veredicto global.
2. **`## Qué se ha verificado`** — 5-12 bullets en lenguaje natural: qué construye el harness, qué encontró (o no) el supervisor, qué queda pendiente si el gate no cerró en PASS.
3. **`## Resumen`** — nunca "listo"/"completado" salvo veredicto global `PASS` con 0 `GAMED`/`NOT-COVERED`/`FAIL`.

## Artefactos

| Path | Contenido |
|------|-----------|
| `.claude/context/verification/harness-<slug>/harness-manifest.md` (+ `.json`) | req_id → scenario_id → test_id → layer → status |
| `apps/api/tests/Harness/<PascalSlug>HarnessTest.php` | Tests PHPUnit reales, tag `@scenario` |
| `apps/web/e2e/harness-<slug>.spec.ts` | Tests Playwright reales, tag `@scenario` |
| `.claude/scripts/harness/<slug>/run.sh` | Runner re-ejecutable (local o CI) |
| `.claude/context/verification/harness-<slug>/run-<timestamp>.json` | Resultado crudo de la última ejecución del harness |
| `.claude/context/verification/harness-<slug>/supervisor-verdict-<timestamp>.md` (+ `.html`) | Veredicto del subagente independiente |
| `.claude/context/verification/harness-<slug>/STATUS.md` | Estado vigente: iteración, veredicto, pendientes |

## Relación con comandos existentes

| Comando | Rol |
|---------|-----|
| **`/harness-spec [<target>]`** | Harness persistente + supervisor en contexto fresco — para cambios de alto riesgo donde el auto-informe no basta |
| **`/verifica-tarea [<slug>]`** | Matriz de un solo uso, misma sesión, cierre habitual de una tarea OpenSpec |
| **`/comando-verificar`** | Matriz combinatoria acotada al diff actual, misma sesión |
| **`/gaps-spec <slug>`** | Gaps de la spec antes de implementar — sin ejecutar nada en runtime |
| **`/ejecuta-tests-reporte`** | Batería de tests + reporte, sin mapeo a escenarios ni supervisor independiente |

## Prohibido

- Construir el harness sobre un **change incompleto** (`tasks.md` con `- [ ]` pendientes) sin override explícito del desarrollador en el mismo turno — ver Fase 0.25.
- Declarar el gate en `PASS` sin `supervisor-verdict-<timestamp>.md` en disco con veredicto global `PASS`.
- Que el orquestador redacte o edite el veredicto del supervisor.
- Relanzar el supervisor reutilizando la misma llamada `Agent` (pierde la independencia de contexto).
- Bucles sin límite — parar honestamente a los 3 ciclos.
- Aflojar una aserición del harness para que el supervisor la apruebe.
- Tests del harness que no ejercen el boundary real (mocks del límite exacto bajo prueba, bypass de formulario/auth).
- Marcar un escenario como cubierto sin `@scenario` trazable en el test.
