# GAPS — inbound-external-orders (revisión multiagente honesta)

> **Source:** real archived change (`openspec/changes/archive/2026-06-24-inbound-external-orders/`). Domain-specific names (modules, Drush) are **historical** — use the structure, not the stack.  
> **Use:** canonical **example** of honest gap analysis output — not a live change in this toolkit repo.

> **Fecha:** 2026-06-24  
> **Estado real:** gaps **verificados** hidratados en `spec.md` como **REQ-IO-13…REQ-IO-19**.  
> **Corrección:** una versión anterior de este fichero afirmaba falsamente «hidratado REQ-IO-13…28»; `spec.md` solo tenía REQ-IO-01…12 hasta esta revisión.

## Metodología — bucle de 5 iteraciones (parada anticipada en iter. 5)

| Iter | Foco | Resultado honesto |
|------|------|-------------------|
| **1** | Cadena Deliverect async (pending KV, DL, lock, dry-run) | **4 gaps FACT** → REQ-IO-13, 14, 15, 16 |
| **2** | `sweetrail_external_orders` + IDs por proveedor | **2 gaps FACT** → REQ-IO-17, 18; casuísticas marketplace documentadas como limitación v1 |
| **3** | Ops / seguridad / coexistencia herramientas | **1 gap FACT** (matriz operador no era REQ) → REQ-IO-19; resto **INFERENCIA** o **ya cubierto** |
| **4** | Verificación cruzada spec ↔ código ↔ GAPS.md | Detectada **afirmación falsa** de hidratación previa; confirmados ficheros ausentes (`UberEatsProcessor.php`, `JustEatProcessor.php`) |
| **5** | ¿Más gaps útiles sin inventar? | **STOP** — candidatos restantes son política de producto, UNKNOWN en PRO, o duplicados de REQ existentes |

**Criterio de parada (iter. 5):** no quedan casuísticas **demostrables en código** que cambien el contrato de APPLY sin especular. Lo que sigue abajo como «no hidratado» queda en diseño/OPERATOR como notas, no como REQ duro.

---

## Matriz consolidada

Leyenda estado: **HYDRATED** = REQ añadido | **ALREADY** = ya en REQ-IO-01…12 | **INFERENCE** = recomendación, no gap FACT | **REJECTED** = descartado (inventado, duplicado o UNKNOWN)

| ID | Sev | Gap | Evidencia (FACT) | Estado | Req |
|----|-----|-----|------------------|--------|-----|
| G-01 | must | Recovery no cubre **pending KV** ni **dead-letter** tras backup/watchdog | `DispatchCreateAsyncEnqueuerInterface::PENDING_KV_COLLECTION`, `DeliverectDispatchCreateReplayer`, OPERATOR L35 | **HYDRATED** | REQ-IO-13 |
| G-02 | must | Recovery Deliverect debe resolver **store_id** vía `DeliverectStoreResolver` | `DeliverectDispatchCreateReplayer` L63–69, `DispatchCreateMaterializer::materialize()` L64–71 | **HYDRATED** | REQ-IO-14 |
| G-03 | must | Lock compartido worker / DL replay / admin recovery | Worker + replayer `deliverect_dispatch_create_materialize:{jobId}`, 120 s | **HYDRATED** | REQ-IO-15 |
| G-04 | must | No capturar/recuperar como Create real el tráfico **Postman dry-run** | `DispatchWebhookController` L226–229, `DispatchProductionDryRunHandler` | **HYDRATED** | REQ-IO-16 |
| G-05 | should | Cola capture con política important-queue / DL | `important-items-harness.mdc` — **no** fallo observable hoy (módulo no existe) | **INFERENCE** | design.md nota |
| G-06 | must | Marketplace: handlers rotos o stub; recovery frágil | `WebhookController` referencia clases ausentes; `GlovoProcessor::processNotification` no materializa; JustEat L212–214 | **HYDRATED** | REQ-IO-17 |
| G-07 | must | ID externo distinto por integrador (`order_number` vs `field_external_order_id`) | Plugins `UberEats.php`/`Glovo.php`/`JustEat.php` vs Deliverect `orderId` | **HYDRATED** | REQ-IO-18 |
| G-08 | must | Matriz coexistencia admin tab vs Drush DL | OPERATOR L31–38 existía pero no en spec | **HYDRATED** | REQ-IO-19 |
| G-09 | should | Preview admin ≠ dry-run materialization | Patrón dry-run en replayer L80–81 — Drush ya lo cubre | **INFERENCE** | OPERATOR |
| G-10 | should | Permisos granulares list vs recover vs outbound | Buena práctica genérica | **INFERENCE** | post-v1 |
| G-11 | should | PII extendida en backup/preview | `HttpExchangePayloadFormatter` redacta secrets; backup no existe aún | **INFERENCE** | post-v1 |
| G-12 | should | Auditoría `recovered_by_uid` | No conflicto con código actual | **INFERENCE** | design D2 |
| G-13 | should | Watchdog repo cap 4000 filas | `IntegrationHttpExchangeWatchdogRepository::MAX_ROWS` | **ALREADY** | REQ-IO-11 edge + OPERATOR |
| G-14 | should | Materialización parcial multi-location | Loop en `DispatchCreateMaterializer` | **ALREADY** | spec Edge cases |
| G-15 | should | Tab 3 no aplica a marketplace inbound-only | REQ-IO-08/09 ya dashboard commerce order | **ALREADY** | REQ-IO-17 |
| G-16 | should | Banner cola capture atascada | Cola aún no implementada | **INFERENCE** | post-v1 |
| G-17 | should | dblog retention PRO vs lookback 168h | **No verificado** en PRO | **REJECTED** | U-04 UNKNOWN |
| G-18 | should | Cap entradas KV backup además de TTL | No hay storage backup en código | **INFERENCE** | T-R2 área |
| G-19 | could | Uber notification-only sin API fetch | `UberEats.php` fetch — no bloquea Deliverect v1 | **INFERENCE** | REQ-IO-17 nota |
| G-20 | could | PRO default `capture_enabled=false` | Política deploy, no evidencia runtime | **REJECTED** | design nota |

---

## Casuísticas útiles (documentación, no REQ nuevos)

### Deliverect
- Backup expirado pero pending KV / DL aún con payload → usar REQ-IO-13 (enlace operador a Drush si admin no puede).
- Payload watchdog truncado (6000 chars) → REQ-IO-11 + pending KV / DL.
- `canDeliver=false` → payload en `DispatchValidateFalseLogStorage` (auxiliar REQ-IO-11); **no** materializar como Create exitoso.

### Marketplace
- Modo 2 manual: claves por proveedor (REQ-IO-18).
- Recovery v1 **Deliverect-first**; marketplace con aviso explícito si handler no materializa (REQ-IO-17).

### Operación
- Dos admins recovery simultáneo → REQ-IO-15 lock + mensaje «lock busy».
- Herramienta recomendada según estado → REQ-IO-19.

---

## Fuera de v1 (sin bloquear APPLY Deliverect)

- Rate limits por uid/hora en PRO.
- Email ops automático.
- Permisos granulares (G-10).
- Export legal hold / congelar entry más allá de TTL.
- E2E permisos negativos por rol (VERIFY ampliado opcional).

---

## Verification (this document)

- **Verified:** `grep '^## Requirement REQ-IO-' spec.md` — antes solo IO-01…12; tras revisión IO-13…19 añadidos en el mismo turno.
- **Verified:** `Glob **/UberEatsProcessor.php` → 0 ficheros; `GlovoProcessor.php` L186–201 stub; `JustEat` handler L212–214 not implemented.
- **Verified:** `DeliverectDispatchCreateReplayer.php` pending store + lock; `DispatchWebhookController.php` L226–234 dry-run / canDeliver=false.
- **Not verified:** Runtime DDEV con servicios rotos de `WebhookController` (autowire fail al habilitar módulo).
