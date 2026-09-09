---
description: "Sumario corto y en lenguaje natural de una spec o change OpenSpec"
argument-hint: "[slug]"
---

# Sumario spec (lenguaje natural, no técnico)

Cuando el desarrollador invoca **`/sumario-spec`**, **`/sumario-spec <nombre>`**, **`sumario de la spec`**, **`resume esta spec`** o **`explícame esta spec`**, produce un **resumen corto en lenguaje natural**, entendible por alguien sin conocimientos técnicos, de una **spec canónica** (`openspec/specs/<capability>/`) o de un **change** OpenSpec (`openspec/changes/<slug>/`).

## 1. Resolver qué spec resumir

On the **first line**, parse the target as the **first token after** `sumario-spec` (optional leading `/`), separated by whitespace — no colon required. Example: `/sumario-spec add-property-management-and-scoping`.

**Caso A — nombre explícito en el comando:** usar ese slug/capability directamente. Ir al paso 2.

**Caso B — sin argumento:** identificar qué specs/changes aparecen mencionados en la ventana de chat actual (rutas `openspec/changes/<slug>/...`, `openspec/specs/<capability>/...`, o nombres de slug/capability citados en el texto de la conversación — no en todo el repo, solo en lo que se ha hablado en esta conversación).

- **Ninguna spec detectada:** ejecutar `openspec list --json` y `openspec list --specs --json`, y preguntar al desarrollador cuál quiere resumir (AskUserQuestion, opciones = changes/specs más recientes). No adivinar.
- **Exactamente una spec/change detectada:** usarla directamente, sin preguntar. Ir al paso 2.
- **Varias specs/changes detectadas en la misma conversación:** abrir un diálogo con AskUserQuestion listando cada una como opción individual **más una opción "Todas"** para resumir todas en la misma respuesta. Esperar la respuesta del desarrollador antes de continuar.

## 2. Leer el contenido fuente (nunca inventar)

Para un **change** (`openspec/changes/<slug>/`):

```bash
openspec show "<slug>" --json
```

Leer también, si existen, `proposal.md` (sección "Why" y "What Changes"), `design.md` y `openspec/changes/<slug>/specs/*/spec.md` para entender el alcance real. No inventar capacidades, requisitos ni escenarios que no estén en estos archivos.

Para una **spec canónica** (`openspec/specs/<capability>/`):

```bash
openspec show "<capability>" --type spec --json
```

Si el nombre es ambiguo entre change y spec, usar `--type change` o `--type spec` explícitamente, o preguntar.

## 3. Redactar el sumario en lenguaje natural

Reglas de redacción (obligatorias):

- **Español, si el desarrollador escribe en español** (o el idioma en que preguntó); sin jerga técnica innecesaria: evitar términos como "entidad", "endpoint", "scope", "DTO", "migration" salvo que no haya forma más sencilla de decirlo, y en ese caso añadir una aclaración breve entre paréntesis.
- Explicar **qué problema resuelve o qué parte del negocio cubre** (1-2 frases), **qué va a poder hacer o ver el usuario/operador** (lista corta, en términos de negocio: "el gestor de la propiedad podrá crear y editar una propiedad desde el panel", no "se añade un endpoint REST CRUD sobre Asset").
- Si es un **change**, indicar además, en una frase, el **estado**: si ya está implementado, en curso, o es solo una propuesta (usar `status`/`tasks` de `openspec status --change "<slug>" --json` — completado vs total).
- Longitud objetivo: **6-10 líneas** por spec/change. No pegar el contenido técnico literal (requisitos/escenarios Gherkin) — traducirlo a prosa.
- No usar tablas ni bullets técnicos excesivos; prosa clara con como mucho una lista corta de 3-5 puntos.

## 4. Si se resumen varias specs/changes ("Todas")

Un sumario por cada una, cada uno con su propio encabezado (`### <nombre>`), en el mismo orden en que se detectaron o se listaron en el diálogo. No fusionar el contenido de specs distintas en un único párrafo.

## 5. Prohibido

- Inventar funcionalidad, estado o alcance que no esté respaldado por `proposal.md`, `design.md`, `spec.md` o `openspec status`.
- Pegar el YAML/Gherkin crudo como sustituto del resumen.
- Preguntar cuando solo hay una spec candidata (ni en el argumento explícito ni cuando la detección en el chat arroja un único resultado).
