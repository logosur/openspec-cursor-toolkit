---
name: openspec-extract-spec-from-doc
description: How to convert a .doc/.docx/.odt ticket reference document (text + screenshots) into a precise OpenSpec spec/design/tasks/VERIFY
---


# OpenSpec — extract spec from .doc/.docx reference

**Stack-agnostic:** verification steps (URL, browser, tests) MUST follow the **target project's** stack rule (`.claude/skills/00-openspec-stack-agnostic/SKILL.md`), not examples below.

Regla operativa para convertir un documento de referencia adjunto a un ticket (Word `.doc` / `.docx`, OpenDocument `.odt`, o PDF como fallback) — con **texto + capturas** — en una especificación OpenSpec precisa: `proposal.md`, `design.md`, `specs/<slug>/spec.md`, `tasks.md`, `OPERATOR.md`, `READY-TO-APPLY.md` y `VERIFY.md`.

Ejemplo canónico: un `.docx` en `~/Downloads/` para el ticket **`fix-checkout-validation`**. Reutilizable en cualquier ticket cuyo input sea un documento Office con párrafos y capturas anotadas.

Alineada con el flujo **EXPLORE → PROPOSE → HYDRATE → VERIFY** de `docs/openspec/prompts/master-openspec-prompt.md`. No autoriza implementar (APPLY) — solo prepara la especificación.

## Cuándo usar esta regla

Aplica cuando ocurre **cualquiera** de estas condiciones:

- El desarrollador adjunta o referencia un `.doc`, `.docx`, `.odt` (o `.pdf` como último recurso) en el chat o lo menciona por path (`~/Downloads/...`, `~/Descargas/...`, etc.) para un ticket (p. ej. `PROJ-1234`).
- Pide ejecutar `prepara-tarea`, `mejora-tarea`, `solucion-*`, o cualquier skill OpenSpec con ese documento como **fuente de verdad**.
- El documento contiene **lista numerada o viñetas de problemas** + **capturas anotadas** (flechas, recuadros, mensajes de error) y se quiere convertirlo en OpenSpec.

Reglas duras:

- **TODAS** las imágenes del documento deben analizarse, una por una. No se permite "agrupar varias capturas en un mismo bullet".
- **TODOS** los párrafos deben transcribirse en orden cronológico, intercalados con las imágenes a las que pertenecen.
- Nunca se infiere comportamiento que el documento no diga; lo dudoso se marca `UNKNOWN`.

## Paso 0 — Localizar el documento

Antes de cualquier comando, **localizar el archivo real**. Buscar en este orden:

1. La ruta exacta que el usuario pegó en el chat.
2. `~/Downloads/` o `~/Descargas/` (descargas locales habituales).
3. `~/Descargas/` (sistema en español).
4. Raíz del repo destino (por si dejaron el documento al lado del proyecto).
5. `.claude/context/openspec/<slug>/source.*` (si una sesión anterior ya lo copió).

Nunca asumir el nombre. Si no aparece, **preguntar una sola vez** al desarrollador con los paths buscados y parar hasta que conteste. No inventar contenido.

Cuando se encuentre, **dejar copia inmutable** en `.claude/context/openspec/<slug>/source.docx` (o `.odt` / `.pdf` según corresponda). Nunca borrar ni mover el original.

```bash
mkdir -p .claude/context/openspec/<slug>/
cp ~/Downloads/source-document.docx .claude/context/openspec/<slug>/source.docx
```

`<slug>` debe coincidir con la carpeta de `openspec/changes/<slug>/` (por convención del ticket: `swt4348`, `mejora-swt4348`, `solucion-swt4348`, etc.).

## Paso 1 — Extraer texto e imágenes en orden cronológico

### Caso `.docx` / `.odt`

`.docx` es un ZIP con `word/document.xml` (estructura) y `word/_rels/document.xml.rels` (mapa `rId` → `media/imageN.png`). `.odt` es ZIP con `content.xml` y `META-INF/manifest.xml`. La extracción debe **preservar el orden de párrafos y referenciar cada imagen embebida** en su sitio.

```bash
SLUG=swt4348
DOC=.claude/context/openspec/${SLUG}/source.docx
WORK=/tmp/${SLUG}-extracted
rm -rf "${WORK}" && mkdir -p "${WORK}"
unzip -q "${DOC}" -d "${WORK}"
ls "${WORK}/word/media/"   # confirma N imágenes
```

Script Python 3 listo para usar (guardar en `.claude/scripts/openspec-extract-doc.py` si se quiere reutilizar). Recorre `<w:p>` en orden, concatena `<w:t>`, captura cada `<a:blip r:embed="rIdX">` y resuelve `rIdX` contra `word/_rels/document.xml.rels`:

```python
#!/usr/bin/env python3
import sys, zipfile, re
from xml.etree import ElementTree as ET

NS = {
  'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
  'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
  'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

def extract(docx_path, out_path):
    with zipfile.ZipFile(docx_path) as z:
        doc = ET.fromstring(z.read('word/document.xml'))
        rels = ET.fromstring(z.read('word/_rels/document.xml.rels'))
    # rId -> media/imageN.ext
    rel_map = {}
    for rel in rels:
        rid = rel.attrib.get('Id')
        target = rel.attrib.get('Target', '')
        if 'media/' in target:
            rel_map[rid] = target  # e.g. media/image3.png
    lines = []
    body = doc.find('w:body', NS)
    for p in body.iter('{%s}p' % NS['w']):
        text_parts = [t.text or '' for t in p.iter('{%s}t' % NS['w'])]
        text = ''.join(text_parts).strip()
        blips = [b.get('{%s}embed' % NS['r']) for b in p.iter('{%s}blip' % NS['a'])]
        imgs = [rel_map.get(rid, rid) for rid in blips if rid]
        if text and imgs:
            lines.append(f'[P] {text}  <<IMG: {", ".join(imgs)}>>')
        elif text:
            lines.append(f'[P] {text}')
        elif imgs:
            lines.append(f'[IMG-ONLY] <<IMG: {", ".join(imgs)}>>')
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')

if __name__ == '__main__':
    extract(sys.argv[1], sys.argv[2])
```

Ejecución:

```bash
python3 .claude/scripts/openspec-extract-doc.py \
  .claude/context/openspec/${SLUG}/source.docx \
  .claude/context/openspec/${SLUG}/source-doc-transcript.md

mkdir -p .claude/context/openspec/${SLUG}/media
cp ${WORK}/word/media/* .claude/context/openspec/${SLUG}/media/
```

Para `.odt` cambia los paths (`content.xml`, `META-INF/manifest.xml`, `Pictures/`) y los namespaces (`text:p`, `draw:image`, `xlink:href`). Misma idea: una línea por párrafo, con `<<IMG: Pictures/100000000000…png>>` adjunto.

### Caso `.pdf` (fallback)

Cuando solo hay PDF (no preferido — pierde estructura de párrafo):

```bash
pdftotext -layout .claude/context/openspec/${SLUG}/source.pdf \
  .claude/context/openspec/${SLUG}/source-doc-transcript.md

pdfimages -all .claude/context/openspec/${SLUG}/source.pdf \
  .claude/context/openspec/${SLUG}/media/img
```

Avisar en el transcript que **el orden imagen↔párrafo puede necesitar reconciliación manual** comparando con la maquetación del PDF abierto en visor.

### Artefactos obligatorios al cerrar el Paso 1

- `.claude/context/openspec/<slug>/source-doc-transcript.md` — transcripción intercalada (una línea por párrafo, con referencias `<<IMG: media/imageN.ext>>`).
- `.claude/context/openspec/<slug>/media/` — todas las imágenes embebidas, con sus nombres originales (`image1.png`, `image2.jpeg`, …).
- `.claude/context/openspec/<slug>/source.docx` (o `.odt` / `.pdf`) — copia inmutable.

## Paso 2 — Inspección visual obligatoria de TODAS las imágenes

El agente **debe abrir cada imagen** con la tool de lectura (una por llamada cuando el contenido sea denso). **Prohibido** saltarse capturas "obvias", "decorativas" o "duplicadas" — todas reciben caption propio.

Para **cada** imagen, escribir una fila en `.claude/context/openspec/<slug>/source-doc-transcript.md` (o en un archivo gemelo `image-captions.md`) con estos campos mínimos, todos como **hechos visibles**:

| Campo | Qué registrar |
|---|---|
| `file` | Nombre exacto, p. ej. `media/image11.png` |
| `url_or_path` | URL/Path visible en la barra de direcciones o título de pestaña, si aparece |
| `screen` | Formulario / panel / página / menú visible (verbatim del título) |
| `fields` | Lista de campos visibles con su valor actual literal |
| `error` | Mensaje de error visible, **verbatim** (entre comillas) |
| `annotations` | Flechas, recuadros, círculos rojos: qué señalan |
| `duplications` | Widgets/elementos duplicados o mal renderizados visibles |
| `notes` | Cualquier otro elemento factual (estado de checkbox, contador, badge, etc.) |

Forma sugerida en el archivo:

```markdown
### media/image11.png
- url_or_path: `<BASE_URL_FROM_PROJECT>/admin/structure/types/manage/...`
- screen: "Editar Programa de Sweetpoints — pestaña Premios"
- fields:
  - "Tipo de premio": `Descuento`
  - "Productos": vacío
- error: "implode(): Argument #1 ($array) must be of type array, string given"
- annotations: flecha roja apuntando al selector "Productos", recuadro rojo sobre el mensaje de error de PHP
- duplications: el widget "Productos" aparece dos veces en la página
- notes: el botón "Guardar" está deshabilitado
```

**Prohibido** resumir varias imágenes en un único caption. Cada imagen es una fila independiente.

## Paso 3 — Derivar problemas atómicos (1 problema = 1 bullet)

Convertir el transcript en una lista **plana** de problemas atómicos. Un problema atómico ocupa **un solo bullet** y se redacta como una afirmación verificable. Cada bullet contiene:

1. `source_paragraph` — texto exacto del párrafo del documento (verbatim, entre comillas).
2. `images` — lista de archivos en `media/` que muestran el problema (`image3.png`, `image11.png`, …).
3. `current_behaviour` — comportamiento actual observado (FACT a partir del doc + captura). Si la captura muestra error PHP, copiarlo verbatim.
4. `expected_behaviour` — comportamiento esperado, **solo** lo que diga el doc. Si el doc no lo precisa, marcar `UNKNOWN — preguntar al desarrollador`.
5. `tags` — etiquetas funcionales (UI, validation, render, workflow, permissions, etc.).

Guardar en:

- `.claude/context/openspec/<slug>/problems.md`
- `.claude/context/openspec/<slug>/problems.html` (twin renderizado, según `documents-md-and-html.mdc`).

Plantilla por problema:

```markdown
### Problem P-01 (par. 3, image3, image4)
- source_paragraph: "Cuando intento añadir un producto al premio, sale un error de PHP y el selector aparece dos veces."
- images: media/image3.png, media/image4.png
- current_behaviour: FACT — la pantalla muestra "implode(): Argument #1 ($array) must be of type array, string given" y el widget "Productos" aparece duplicado.
- expected_behaviour: FACT (del párrafo) — al pulsar "Añadir otro producto" debe añadir una fila adicional sin lanzar excepción.
- tags: render, form-api, multivalue
```

## Paso 4 — Mapear problemas a OpenSpec

Para cada problema atómico se crea **un Requirement** en `openspec/changes/<slug>/specs/<slug>/spec.md` y al menos **un escenario GIVEN/WHEN/THEN** que cite verbatim el párrafo origen y mencione el archivo de imagen.

Estructura mínima del cambio OpenSpec:

```
openspec/changes/<slug>/
├── .openspec.yaml
├── proposal.md
├── design.md
├── tasks.md
├── OPERATOR.md
├── READY-TO-APPLY.md
├── VERIFY.md
└── specs/<slug>/
    └── spec.md
```

### `proposal.md`

- Problem summary — resumen 2–4 frases.
- Source of truth — apunta a `.claude/context/openspec/<slug>/source.docx` y al transcript.
- Evidence map — tabla `Problem ID → párrafo → imágenes → Requirement ID`.
- Included / excluded scope — lista los problemas IN y los que quedan OUT.

### `design.md`

- Arquitectura afectada (formulario, servicio, plugin, hook).
- Decisiones técnicas con justificación.
- Si la solución toca renderizado o validación: enlazar a `workflow-field-sync-architecture.mdc`, `order-event-subscribers.mdc`, `testing-browser-parity-and-form-events.mdc` según corresponda.

### `specs/<slug>/spec.md`

Un `### Requirement` por problema atómico, con título trazable:

```markdown
### Requirement REQ-SP-RENDER-01 (image11, par. 3, bullet 1)

The premios edit form SHALL render the multivalue "Productos" widget exactly once and SHALL allow adding additional rows without raising a `TypeError`.

#### Scenario: Añadir producto sin error PHP
- **GIVEN** un usuario administrador autenticado en `/admin/.../premios/<id>/edit`
- **WHEN** pulsa "Añadir otro producto" (par. 3 del doc; ver `media/image11.png`)
- **THEN** la página NO contiene "implode(): Argument #1 ($array) must be of type array, string given"
- **AND** el widget "Productos" aparece exactamente una vez en el DOM
- **AND** `$form_state->getValue('field_productos')` es un array con la entrada nueva.
```

Reglas de titulado: cada `### Requirement` lleva al final, en paréntesis, **la captura y el bullet origen** (`image11, par. 3, bullet 1`). Esto permite auditar trazabilidad sin abrir el doc.

### `tasks.md`

Una tarea por Requirement (o subtarea cuando hay más de un componente). Cada tarea cita el `REQ-…` que cumple. Si una tarea no cubre ningún Requirement, sobra.

### `OPERATOR.md` y `READY-TO-APPLY.md`

- `OPERATOR.md` — guía manual de aplicación (comandos del stack del proyecto, orden, cuándo rebuild/import).
- `READY-TO-APPLY.md` — checklist de pre-flight (specs hidratadas, VERIFY definido, no UNKNOWN, riesgos cubiertos).

### `VERIFY.md`

Ver Paso 5.

## Paso 5 — VERIFY reforzado (browser-real, no solo unit)

`VERIFY.md` debe garantizar que la solución se valida **como un usuario real**, no solo en kernel. Por cada `Requirement` del spec, el VERIFY incluye **todos** estos bloques:

### 5.1 URL real del proyecto

```bash
BASE_URL=$(project URL resolution (stack rule) | jq -r '.raw.primary_url')
echo "${BASE_URL}/admin/...."
```

Prohibido hardcodear `<BASE_URL_FROM_PROJECT>` o un puerto. Se obtiene de `project URL resolution (stack rule)` (acorde a `.claude/skills/00-openspec-stack-agnostic/SKILL.md`).

### 5.2 Playwright spec por Requirement

Una spec por Requirement (o por agrupación obvia) bajo `tests/playwright-full-order/` (suite versionada) o `.claude/QAtest/playwright-e2e/` (local). La spec debe:

- Navegar a la URL exacta que el doc cita.
- Reproducir la acción del usuario descrita en el párrafo origen.
- Aserciones DOM concretas: selector + texto/atributo/estado esperado.
- Capturar screenshot final en `.claude/context/openspec/<slug>/verification/REQ-SP-RENDER-01.png`.

Estructura mínima:

```typescript
test('REQ-SP-RENDER-01 — premios productos sin error PHP', async ({ page }) => {
  await page.goto(`${BASE_URL}/admin/.../premios/123/edit`);
  await page.getByRole('button', { name: 'Añadir otro producto' }).click();
  await expect(page.locator('body')).not.toContainText('implode(): Argument #1');
  await expect(page.locator('[data-testid or stable selector="edit-field-productos"]')).toHaveCount(1);
  await page.screenshot({
    path: '.claude/context/openspec/swt4348/verification/REQ-SP-RENDER-01.png',
    fullPage: true,
  });
});
```

Ejecutar **dentro del contenedor web** con `project E2E suite` o `project container exec "cd /var/www/html/e2e && npx playwright test"` (acorde a `project E2E rules`).

### 5.3 Reproducción server-side (kernel / functional)

Test PHP que construya el formulario por la **misma ruta** y simule `user_input`, ejecutando la cadena completa:

```
$form_builder->buildForm(...) → #validate → render → FormErrorHandler::handleFormErrors → Renderer::renderPlain
```

Aserciones obligatorias:

- `expectNotToThrow()` (o ausencia de excepción capturada).
- `$form_state->getValue('field_xxx')` contiene la estructura canónica (arrays multivalor en entity_reference, no strings).
- Sin mensajes de error de PHP en el render.

Ejecución:

```bash
project test command <module_name>
```

### 5.4 Aserción HTTP / red

Login real con el helper de auth del proyecto + `curl`, contra la **misma URL** que la captura:

```bash
TOKEN_URL=$(project CLI (when applicable) user-login --uri="${BASE_URL}" --name=admin)
COOKIE=/tmp/cookie-${SLUG}.txt
curl -sL -c "${COOKIE}" -o /tmp/login.html -w 'login:%{http_code}\n' "${TOKEN_URL}"
curl -sL -b "${COOKIE}" -o /tmp/page.html \
  -w 'page:%{http_code}\n' "${BASE_URL}/admin/.../premios/123/edit"
grep -q 'name="field_productos\[0\]\[target_id\]"' /tmp/page.html
! grep -q 'implode(): Argument #1' /tmp/page.html
```

Respuesta debe ser `200`. El HTML guardado debe contener cada atributo `name=` esperado y **no** debe contener el string de error histórico.

### 5.5 Aserciones negativas (obligatorias)

Listar verbatim cada fallo histórico conocido y aseverar que **no** aparece. Ejemplos comunes:

- `implode(): Argument #1 must be of type array, string given`
- `count(): Argument #1 ($value) must be of type Countable|array`
- Widgets duplicados (el mismo `data-testid or stable selector` aparece dos veces).
- Valores de submit vacíos cuando la UI mostraba selección.
- `LogicException: Form errors cannot be set …` durante `renderPlain`.

Cada negativa debe escribirse **literal** y atarse a la captura origen (`media/image11.png`).

### 5.6 Tabla de checklist manual

`VERIFY.md` termina con una tabla con **una fila por imagen** del doc fuente. No vale agruparlas.

```markdown
| Image | Expected behaviour (from doc) | Manual Pass |
|---|---|---|
| media/image1.png | Pantalla inicial muestra X | [ ] |
| media/image2.png | El selector Y permite Z | [ ] |
| media/image3.png | Al pulsar "Añadir" no aparece error PHP | [ ] |
| …               | …                              | [ ] |
```

Mientras alguna fila quede en `[ ]` sin captura de verificación pareja, la tarea NO está cerrada.

## Anti-patterns prohibidos

- ❌ Resumir varias capturas en un solo bullet. Cada imagen = caption + fila propia en la tabla de VERIFY.
- ❌ Inventar comportamiento que no esté en el doc. Lo no especificado se marca `UNKNOWN — preguntar`.
- ❌ Cerrar VERIFY solo con `project test command` verdes. Debe haber **prueba en navegador (Playwright)** + **aserción HTTP** + **aserciones negativas**.
- ❌ Borrar o mover el `.docx` original. Siempre dejar copia inmutable en `.claude/context/openspec/<slug>/source.docx`.
- ❌ Saltar capturas "obvias" o "duplicadas" sin caption. Todas se documentan.
- ❌ Generar `Requirement` sin trazabilidad al doc (sin `(imageN, par. X, bullet Y)` en el título).
- ❌ Hardcodear URLs `<BASE_URL_FROM_PROJECT>:NNNN`. Siempre `project URL resolution (stack rule)`.
- ❌ Crear `.md` u otros artefactos en la raíz del repo. Todo va bajo `.claude/context/openspec/<slug>/` u `openspec/changes/<slug>/` (ver `no-artifacts-in-root.mdc`, `no-md-in-root.mdc`).
- ❌ Mezclar implementación con extracción de spec. Esta regla es **EXPLORE → PROPOSE → HYDRATE → VERIFY only** — la implementación va por `aplica-tarea` / `/opsx:apply` en un turno separado.

## Relación con otras reglas y skills

- `tdd-spec-driven-tests.mdc` — los tests del Paso 5 son el contrato; el código se adapta a ellos, no al revés.
- `testing-browser-parity-and-form-events.mdc` — la prueba server-side debe pasar por `build → #validate → render`, no atajos.
- `documents-md-and-html.mdc` — `problems.md`, `source-doc-transcript.md`, `image-captions.md` y cualquier informe llevan twin `.html`.
- `ai-helper-files.mdc` — toda la documentación auxiliar de la extracción vive en `.claude/context/openspec/<slug>/`.
- `qa-evidence-html-by-role.mdc` — si el problema afecta a varios roles, el VERIFY incluye evidencia por rol.
- `qa-reports-open-chrome.mdc` — al terminar un informe HTML (`problems.html`, `verification/index.html`), abrirlo en Chrome con `google-chrome "file://..."`.
- `.claude/skills/00-openspec-stack-agnostic/SKILL.md` — resolver comandos de proyecto desde la regla de stack del repo destino.
- `no-artifacts-in-root.mdc`, `no-md-in-root.mdc` — nada en la raíz del repo.
- Skill `00-openspec-master` — flujo maestro EXPLORE→PROPOSE→HYDRATE→VERIFY.
- Skill `20-openspec-hydrate-spec` — hidratar specs débiles hasta que sean testables.
- Skill `30-openspec-anti-hallucination` — separar FACT / INFERENCE / HYPOTHESIS / UNKNOWN al transcribir el doc.
- Skill `prepara-tarea` — punto de entrada habitual cuando se adjunta el documento al chat.

## Resumen para el agente

1. **Localiza** el documento real, déjalo copiado e inmutable en `.claude/context/openspec/<slug>/source.*`.
2. **Extrae** texto + imágenes preservando orden cronológico → `source-doc-transcript.md` + `media/`.
3. **Captión imagen por imagen** — todas, con campos factuales.
4. **Lista problemas atómicos** trazables a párrafo + imagen.
5. **Genera el cambio OpenSpec** con Requirements titulados con la fuente.
6. **VERIFY browser-real**: Playwright + server-side + HTTP + aserciones negativas + checklist 1 fila por imagen.
7. **Para** tras VERIFY. La implementación (APPLY) va en un turno aparte vía `aplica-tarea` / `/opsx:apply`.
