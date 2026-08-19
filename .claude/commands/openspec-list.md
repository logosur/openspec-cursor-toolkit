---
description: "Lista los últimos cambios OpenSpec en tabla y abre HTML en Chrome"
argument-hint: "[count]"
---

# OpenSpec list — últimos cambios en tabla + HTML en Chrome

Cuando el desarrollador invoca **`/openspec-list`**, **`openspec-list`**, **`lista openspec`** o **`/openspec-list 20`**, ejecuta el listado de cambios activos en `openspec/changes/` como **tabla Markdown** (primero las specs **sin concluir**, después las **completas**; dentro de cada grupo, de más a menos reciente), **genera siempre** el HTML y **abre Chrome** con el informe.

## Argumento opcional (conteo)

El número indica **cuántos cambios listar** sobre la lista ya ordenada (sin concluir primero); no es un índice ni offset.

| Invocación | Cantidad listada |
|------------|------------------|
| `/openspec-list` | **Todos** los activos si hay alguna spec sin terminar; **5** si todas están completas |
| `/openspec-list 12` | **12** primeros del orden sin-concluir→completas (o todos si hay menos de 12 activos) |
| `/openspec-list 32` | **32** primeros (o todos si hay menos activos) |

El límite por defecto **nunca oculta specs sin terminar**: sin argumento, si existe al menos un cambio `in-progress`/`no-tasks`, se listan todos los activos.

Si el argumento no es un entero positivo, mostrar el mensaje de uso del script y no inventar datos.

## Comando obligatorio (ejecutar tú)

Desde la raíz del repositorio:

```bash
bash .claude/scripts/openspec-list.sh
```

Con conteo explícito:

```bash
bash .claude/scripts/openspec-list.sh 20
```

El script **siempre**:

1. Imprime la tabla Markdown en stdout (para pegar en el chat).
2. Escribe `.claude/context/openspec/openspec-list.html` (o `--html [path]`).
3. Abre el HTML en **Chrome** del host (`google-chrome file://…`, fallbacks `chromium-browser`, `xdg-open`).

Opciones:

| Flag | Efecto |
|------|--------|
| `--html [path]` | Ruta del HTML (default: `.claude/context/openspec/openspec-list.html`) |
| `--no-chrome` | No abrir navegador (solo stdout + archivo) |

**No** sustituir por lectura manual de carpetas si `openspec` y `jq` están disponibles.

## Formato (tabla Markdown)

Cabecera de contexto + tabla con columnas:

| Columna | Fuente |
|---------|--------|
| **#** | Posición en el listado (1 = sin concluir más reciente) |
| **name** | Slug del cambio (`openspec/changes/<name>/`) |
| **schema** | `openspec status --change <name> --json` → `schemaName` |
| **tasks** | `completedTasks/totalTasks` |
| **status** | `status` de `openspec list --json` (`in-progress`, `complete`, `no-tasks`) |
| **artifacts** | Resumen `id:status` unido con `·` si había `|` |
| **artifacts_ok** | `isComplete` del status JSON |
| **modified** | `lastModified` ISO de `openspec list --json` |

**Negrita:** filas con `status=complete` (activos) y todas las filas **archivadas** (`openspec/changes/archive/`) van en **bold** en cada celda (y resaltadas en el HTML).

## Qué incluye y qué no

- **Incluye:** cambios **activos** en `openspec/changes/` (lo mismo que `openspec list`), reordenados: **sin concluir primero**, completas después.
- **Incluye también:** hasta el mismo `count` de cambios en `openspec/changes/archive/` (orden por nombre de carpeta, más reciente primero), siempre en **bold**.
- **No incluye:** specs canónicas de `openspec/specs/` (usar `openspec list --specs` aparte si hace falta).

## Respuesta al desarrollador

1. Ejecutar el script con el conteo pedido (sin argumento: todos si hay specs sin terminar, 5 si no).
2. Pegar la salida Markdown completa en el chat (cabecera + tabla).
3. Confirmar que Chrome abrió el HTML (o indicar si `--no-chrome` / sin display).
4. Si `openspec` o `jq` fallan, mostrar el error del comando — no listar desde disco.

## Relación

- `openspec list --json` / `openspec status --change <name> --json` — fuente de datos.
- `.claude/context/openspec-docs/README.md` — índice OpenSpec del proyecto.
- `qa-reports-open-chrome.mdc` — abrir informe HTML en Chrome.
- `/opsx-archive`, `/archiva-tarea` — archivar cuando un cambio esté listo.
