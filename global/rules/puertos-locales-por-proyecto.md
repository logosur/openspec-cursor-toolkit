# Puertos locales: un bloque fijo por proyecto, sin choques (regla global)

- Todo puerto que un proyecto publique en la máquina (Compose, servidor de desarrollo, base de datos, mailer, Storybook,
  Playwright…) sale de **su bloque**: 16 puertos seguidos en 20000–29999, reservados en
  `~/.local/state/port-leases/registry.json`. Nunca 3000, 3306, 6379, 8080 ni otro «puerto de siempre». Excepciones: el
  router propio de una herramienta de desarrollo (DDEV) y producción.
- `~/.claude/scripts/port-lease claim SERVICIO...` toma o amplía el bloque del directorio (idempotente) y escribe
  `PORT_<SERVICIO>=n`. El proyecto versiona `dev-ports.env` y publica `${PORT_<SERVICIO>:-n}` en los compose.
  `port-lease verify` falla si no coinciden o si queda un literal.
- Un worktree es otro bloque, con su `COMPOSE_PROJECT_NAME`: se arranca con `port-lease exec -- <comando>`.
- Un compose nuevo nace con `${PORT_X:-n}`, `name: ${COMPOSE_PROJECT_NAME:-<proyecto>}` y su `dev-ports.env`. El bloque
  no se elige a mano.
- Archivar o eliminar un proyecto: `port-lease release`. Reactivarlo: `claim` otra vez y, si cambia el bloque, ajustar el
  proyecto hasta que `verify` pase.
- No se cambia un puerto a otro «libre» a ojo, no se para un servicio ajeno, no se solapan bloques y no se edita el
  registro a mano: si `claim` se niega, se dice al desarrollador.
