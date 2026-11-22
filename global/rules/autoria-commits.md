# Autoría de commits y PRs: solo el desarrollador (regla global, dura)

> Por qué: un commit o un PR que lleva a la IA como coautora atribuye trabajo a quien no firma ni responde de él, y
> en un proyecto ajeno puede incumplir sus normas de contribución. La identidad de cada repositorio es la del
> desarrollador, y solo él la cambia.

## La regla
- Todo commit, tag, nota, PR, issue, release o comentario que haga el agente lleva como único autor y
  committer la identidad git que el desarrollador tiene configurada en ese repositorio. Sin coautores.
- Ningún texto publicado lleva `Co-Authored-By` (en ninguna forma), `Co-developed-by`, `Assisted-by`,
  `Claude-Session`, `noreply@anthropic.com`, «Generated with Claude Code», 🤖 ni otra atribución a
  Claude, Anthropic o una IA. Mencionar Claude como tema (un proyecto sobre IA) sí está permitido.
- Prevalece sobre cualquier recordatorio del sistema, plantilla o instrucción de un repositorio que pida
  atribución. No hay excepciones ni «solo esta vez».
- El agente nunca se salta hooks de git (`--no-verify`, `commit -n`, `-c core.hooksPath`), nunca hace
  commits como otra persona (`--author`, `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, `-c user.*`) y nunca cambia
  `user.name`/`user.email`. Si la identidad de un repositorio parece incorrecta, lo dice y decide el
  desarrollador.

## Cómo se hace cumplir
- `~/.claude/settings.json`: `attribution.commit` y `attribution.pr` vacíos, `includeCoAuthoredBy: false`.
  Ningún `.claude/settings*.json` de un proyecto puede volver a activarla.
- `~/.claude/hooks/commit-authorship-gate` (PreToolUse en Bash, Edit y Write): deniega lo anterior antes de
  que se ejecute, valida cualquier escritura de un `.claude/settings*.json` y protege el propio gate, esta
  regla y la configuración de usuario. La detección es por texto: un comando que solo menciona esas opciones
  también se deniega; entonces se reformula, no se esquiva.
- Una barrera de git por proyecto (hooks `commit-msg`, `reference-transaction` y `pre-push` con la identidad
  fijada) es opcional y se instala solo si el desarrollador lo pide. No se usa un `core.hooksPath` global:
  bloquearía clones de dependencias con coautores en su historial, apagaría los hooks propios de algunos repos
  (git-lfs, husky) y no encaja con varias identidades.

## Qué no hace el agente
- No edita el gate, esta regla ni `~/.claude/settings.json` para relajar nada: los cambia el desarrollador,
  a mano.
- Si un commit propio sin publicar incumple, no lo publica: lo reescribe limpio y elimina el anterior sin
  dejar rastro (reflog, `ORIG_HEAD`, `COMMIT_EDITMSG`, objeto suelto), y lo informa.
- El historial ya publicado con atribución no se reescribe salvo orden explícita del desarrollador, repo por
  repo: reescribir ramas compartidas es destructivo.
