# GAPS — loan-reminders (revisión multiagente honesta)

> **Nota:** ejemplo ilustrativo con un dominio inventado (avisos de préstamos de una biblioteca). Usa la **estructura**; el stack lo define cada proyecto (`00-openspec-stack-agnostic.mdc`).

> **Fecha:** 2026-06-24  
> **Estado real:** gaps **verificados** hidratados en `spec.md` como **REQ-LN-13…REQ-LN-17**.  
> **Corrección:** una versión anterior de este fichero afirmaba «hidratado REQ-LN-13…25»; `spec.md` solo tenía REQ-LN-01…12 hasta esta revisión.

## Metodología — bucle de 5 iteraciones (parada anticipada en iter. 5)

| Iter | Foco | Resultado honesto |
|------|------|-------------------|
| **1** | Cola de recordatorios async (reintentos, dead-letter, cerrojo, dry-run) | **3 gaps FACT** → REQ-LN-13, 14, 15 |
| **2** | Identificadores externos por proveedor de correo y SMS | **1 gap FACT** → REQ-LN-16; casuísticas de proveedores secundarios documentadas como limitación v1 |
| **3** | Ops / seguridad / coexistencia de herramientas | **1 gap FACT** (matriz del operador no era REQ) → REQ-LN-17; resto **INFERENCIA** o **ya cubierto** |
| **4** | Verificación cruzada spec ↔ código ↔ GAPS.md | Detectada **afirmación falsa** de hidratación previa; confirmado un fichero ausente (`SmsReminderSender.php`) |
| **5** | ¿Más gaps útiles sin inventar? | **STOP** — los candidatos restantes son política de producto, UNKNOWN en producción o duplicados de REQ existentes |

**Criterio de parada (iter. 5):** no quedan casuísticas **demostrables en código** que cambien el contrato de APPLY sin especular. Lo que sigue como «no hidratado» queda en design/OPERATOR como nota, no como REQ duro.

---

## Matriz consolidada

Leyenda: **HYDRATED** = REQ añadido | **ALREADY** = ya en REQ-LN-01…12 | **INFERENCE** = recomendación, no gap FACT | **REJECTED** = descartado (inventado, duplicado o UNKNOWN)

| ID | Sev | Gap | Evidencia (FACT) | Estado | Req |
|----|-----|-----|------------------|--------|-----|
| G-01 | must | La recuperación no cubre los mensajes en **dead-letter** | `ReminderQueue::DEAD_LETTER`, `ReminderReplayer`, OPERATOR L35 | **HYDRATED** | REQ-LN-13 |
| G-02 | must | Cerrojo compartido entre worker, reintento manual y panel de administración | `reminder_send:{loanId}`, 120 s, en worker y replayer | **HYDRATED** | REQ-LN-14 |
| G-03 | must | Un envío en **dry-run** no debe marcar el préstamo como avisado | `ReminderController` L120–128, `DryRunSender` | **HYDRATED** | REQ-LN-15 |
| G-04 | must | Id externo distinto por proveedor (`message_id` vs `sid`) | `MailProvider.php` / `SmsProvider.php` | **HYDRATED** | REQ-LN-16 |
| G-05 | must | Matriz de qué herramienta usa el operador según el estado | OPERATOR L31–38 existía pero no en spec | **HYDRATED** | REQ-LN-17 |
| G-06 | should | Permisos separados para listar y reintentar | Buena práctica genérica | **INFERENCE** | post-v1 |
| G-07 | should | Datos personales en el registro de envíos | `PayloadFormatter` ya redacta secretos | **INFERENCE** | post-v1 |
| G-08 | should | Tope de 4000 filas en el registro de envíos | `SendLogRepository::MAX_ROWS` | **ALREADY** | REQ-LN-11 |
| G-09 | should | Retención del registro en producción frente a ventana de 168 h | **No verificado** en producción | **REJECTED** | U-04 UNKNOWN |
| G-10 | could | Proveedor SMS sin API de consulta de estado | `SmsProvider.php` no hace fetch — no bloquea v1 | **INFERENCE** | REQ-LN-16 nota |

---

## Casuísticas útiles (documentación, no REQ nuevos)

- Mensaje en dead-letter con plantilla ya borrada → REQ-LN-13 con aviso al operador.
- Dos administradores reintentando a la vez → REQ-LN-14, mensaje «lock busy».
- Herramienta recomendada según el estado del envío → REQ-LN-17.

---

## Fuera de v1 (sin bloquear APPLY)

- Límite de reintentos por usuario y hora.
- Permisos granulares (G-06).
- E2E de permisos negativos por rol (VERIFY ampliado opcional).

---

## Verification (this document)

- **Verified:** `grep '^## Requirement REQ-LN-' spec.md` — antes solo LN-01…12; tras la revisión, LN-13…17 añadidos en el mismo turno.
- **Verified:** `Glob **/SmsReminderSender.php` → 0 ficheros; `SmsProvider.php` L186–201 stub.
- **Verified:** `ReminderReplayer.php` cerrojo + dead-letter; `ReminderController.php` L120–128 dry-run.
- **Not verified:** ejecución en el entorno local con el proveedor SMS real.
