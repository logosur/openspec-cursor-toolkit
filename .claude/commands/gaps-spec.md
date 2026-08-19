---
description: "Análisis honesto de gaps OpenSpec — bucle multiagente (≤5 iter), GAPS.md con evidencia; sin implementar"
argument-hint: "[slug|objetivo]"
---

# Gaps spec (OpenSpec gap analysis)

Cuando el desarrollador invoca el flujo de **descubrimiento de gaps** — **sin implementar código de producto** — por **cualquiera** de las vías abajo, ejecuta el mismo skill (no solo el slash command).

## Cómo invocar (slash + lenguaje natural)

| Vía | Ejemplos |
|-----|----------|
| **Slash command** | `/gaps-spec`, `/gaps-spec stats-net` |
| **Alias corto** | `gaps-spec stats-net` |
| **Lenguaje natural (ES)** | `analiza gaps stats-net`, `revisar gaps en polling rider`, `qué casuísticas faltantes hay`, `huecos en la spec`, `revisa los gaps del change`, `gaps antes de aplica-tarea` |
| **Lenguaje natural (EN)** | `gap analysis stats-net`, `spec gaps`, `missing casuistics`, `what gaps are left`, `update GAPS.md` |

**Regla:** si el mensaje encaja con **cualquier** frase de la tabla (intención de gap analysis / GAPS.md / casuísticas faltantes), el agente **debe** cargar y seguir **`.claude/skills/openspec-gap-analysis/SKILL.md`** aunque no aparezca `/gaps-spec`.

Soporta **dos modos de entrada** (ver reglas de parsing abajo).

## Modos de entrada

### Mode A — change-id (existente)

| Formato | Ejemplo |
|---------|---------|
| Slug del change | `/gaps-spec stats-net` |
| Ruta a spec | `/gaps-spec openspec/changes/stats-net/specs/stats-net/spec.md` |

- Requiere carpeta `openspec/changes/<change-id>/` (puede existir con spec completa o parcial).
- **Salida:** `openspec/changes/<change-id>/GAPS.md`
- Lee artefactos existentes: `proposal.md`, `design.md`, `specs/**/spec.md`, `tasks.md`, `OPERATOR.md`, `VERIFY.md`, `GAPS.md` previo.

### Mode B — ad-hoc / on-the-fly (NUEVO)

**Trigger:** comando sin slug/ruta; el desarrollador escribe el **objetivo de revisión** en línea(s) siguientes.

```
/gaps-spec
Revisar gaps en intervalos de polling y connection health para la app rider
```

- **No** exige `spec.md` ni `proposal.md` completos antes de empezar.
- La revisión se guía por **objetivo del usuario + evidencia en codebase**.
- Deriva un **slug** para la carpeta (kebab-case, inglés preferido, máx. ~40 chars) a partir del objetivo, **o** `adhoc-YYYY-MM-DD-<short-hash>` si el objetivo es demasiado vago.
- Crea scaffold mínimo si falta:

```
openspec/changes/<derived-slug>/
  GAPS.md       ← salida principal (incluye sección Review objective)
  proposal.md   ← stub mínimo: objetivo + "Created by /gaps-spec ad-hoc"
```

- Mismo bucle multiagente honesto (≤5 iter, early stop).
- **`GAPS.md` debe incluir sección `## Review objective`** citando el texto del usuario **verbatim**.

## Reglas de parsing (obligatorio)

Aplica a **slash**, **alias** y **mensajes en lenguaje natural** (misma lógica que el skill).

1. **Mode A** — si el mensaje contiene slug (`stats-net`, `SWT1234`) **o** ruta (`openspec/changes/...`, termina en `.md`) como target del change → resolver change-id y continuar Mode A.
2. **Mode B** — si hay intención de gap analysis **sin** slug/ruta → extraer objetivo (texto del usuario menos keywords de comando; multilínea permitido).
3. **Ambiguo** — si no hay slug **ni** texto de objetivo → preguntar **una vez**: *"Indica change-id o escribe el objetivo de la revisión en la línea siguiente"* y parar.
4. **No preguntar** si el objetivo está claramente presente (NL o línea siguiente tras `/gaps-spec`).

## Qué ejecutar (obligatorio)

1. Resolver modo (A o B) según parsing arriba.
2. Leer y seguir **`.claude/skills/openspec-gap-analysis/SKILL.md`** (paso a paso).
3. Aplicar **`.claude/skills/openspec-gap-analysis/SKILL.md`** (taxonomía FACT/INFERENCE/REJECTED, bucle ≤5 iter).
4. Operar en **modo multiagente** — orquestador + subagentes `Task` (`explore` / `shell`); orquestador **no implementa**.
5. Escribir o actualizar **`openspec/changes/<slug>/GAPS.md`** con evidencia honesta.

## Salida esperada

- Fichero **`openspec/changes/<slug>/GAPS.md`** (matriz + metodología + **`## Pending count`** + verification; Mode B incluye **Review objective**).
- Mode B: **`proposal.md`** stub si no existía.
- Resumen en chat: modo usado (A/B), slug derivado, iteraciones ejecutadas, parada anticipada (si aplica), conteos FACT/REJECTED, tabla **`## Pending count`**.
- **Última línea obligatoria del chat (sin texto después):**

```text
Gaps pending (mejora + apply): <N>
```

`<N>` = filas de la matriz consolidada con estado `FACT` / `PENDING` / vacío y evidencia FACT — excluye `HYDRATED`, `ALREADY`, `REJECTED`, `INFERENCE`, `UNKNOWN`. Debe coincidir con la misma línea al final de `## Pending count` en `GAPS.md`.

- **Stop:** no encadenar `/aplica-tarea` en el mismo turno salvo petición explícita.

## Ejemplos de invocación

**Mode A (slash o NL con slug):**

```
/gaps-spec stats-net
```

```
analiza gaps stats-net
```

**Mode B (slash sin slug o NL con objetivo):**

```
/gaps-spec
Revisar gaps en intervalos de polling y connection health para la app rider
```

```
revisar gaps en polling rider y connection health
```

```
qué casuísticas faltantes hay en connection health para riders
```

→ Mode B crea p. ej. `openspec/changes/rider-polling-connection-health/GAPS.md` (slug derivado del objetivo).

## Referencia canónica

`openspec/changes/archive/2026-06-24-inbound-external-orders/GAPS.md` (histórico; nuevos `GAPS.md` incluyen **`## Pending count`** y la línea final `Gaps pending (mejora + apply): N`).

## Relación

| Artefacto | Rol |
|-----------|-----|
| `.claude/skills/openspec-gap-analysis/SKILL.md` | Workflow ejecutable |
| `.claude/skills/openspec-gap-analysis/SKILL.md` | Reglas L2 (globs OpenSpec) |
| `.claude/skills/multiagente/SKILL.md` | Orquestación multiagente |
| `/mejora-tarea` | Hidratar REQ tras gaps FACT |
| `/aplica-tarea` | Implementar tras READY |
| `/repasa-spec <slug>` | Pipeline secuencial: gaps → mejora → apply → gaps |
