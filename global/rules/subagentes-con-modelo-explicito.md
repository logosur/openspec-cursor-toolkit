# Subagentes y sesiones nuevas: modelo explícito y barato, el caro solo con motivo (regla global)

- Un subagente que no nombra modelo hereda el de quien lo lanza, casi siempre el más caro, y una consulta al asesor
  cuesta como un turno largo. Repetidos, se llevan buena parte de la cuota. Por eso se fija el modelo en cada llamada.
- **`Agent` (y `Task`):** siempre con `model`. Implementar, explorar y verificar: `"sonnet"`; búsquedas triviales:
  `"haiku"`. Un `fork` hereda y no necesita `model`.
- **Opus o Fable** (alias o id): solo con la marca `[opus: <motivo de al menos 10 caracteres>]` en `description` o en
  `prompt`, para una pieza compleja (arquitectura, seguridad, concurrencia, un fallo difícil, dos intentos fallidos con
  uno más barato). El panel de decisión no la necesita: su `description` empieza por `Panel`.
- **`start_session` con `prompt`:** `model` explícito; un id de Opus o Fable lleva la marca en `prompt` o `background`.
  Una oferta de solo título o un `proposal_id` no se tocan.
- **Asesor:** como mucho `advisor_max_per_day` llamadas por sesión en 24 horas móviles. Pasado el tope se sigue sin él.
- **Lo impone `~/.claude/hooks/agent-model-gate`, que se instala desactivado** (`enabled: false`: permite todo y no
  escribe nada hasta que la pieza de config privada ponga `enabled: true`) (deniega antes de ejecutar y dice cómo reenviar). Es un hook
  `PreToolUse`: el asesor es una herramienta del servidor y puede que el cliente no la anuncie al hook; en ese caso su
  tope no actúa.
- **Austeridad:** con `austerity: true` en la pieza de config `agent-model-gate` se deniegan Opus y Fable aunque lleven
  marca (salvo el panel) y el tope del asesor pasa a 1. Se enciende cuando la cuota va justa y se apaga al acabar.
- Ajustes en la misma pieza: `enabled`, `require_explicit_model`, `opus_needs_marker`, `panel_pattern`,
  `advisor_max_per_day` y `exempt_paths` (carpetas donde no aplica). El valor real va al override, no al repositorio.
- No se esquiva la guardia con una marca sin motivo real: la marca existe para que la decisión quede escrita.
