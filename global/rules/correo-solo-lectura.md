# Correo: los agentes leen y redactan, el desarrollador envía (regla global)

- Leer, buscar y descargar correo nunca se bloquea. Enviar, responder, reenviar, etiquetar, archivar en la papelera o marcar como spam no lo hace un agente.
- Lo impone `~/.claude/hooks/mail-send-gate`: deniega las herramientas de escritura de un conector de correo y las órdenes de Bash que envían (`sendmail`, `mail`, `msmtp`, `swaks`, `curl smtp://…`, un intérprete en línea con una librería SMTP).
- El buzón de pruebas local siempre vale: un destino SMTP explícito en `localhost`, `127.0.0.1`, `::1`, `*.localhost` o `*.test`.
- Ante una denegación, el texto se entrega en el chat o en un fichero y lo envía el desarrollador. No se esquiva la guardia con un script.
- Excepciones (`exempt_paths`, `extra_commands`, `drafts` para borradores) en la pieza de config `mail-send-gate`; el valor real va al override.
