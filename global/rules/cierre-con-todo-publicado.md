# Cerrar una sesión: terminado, publicado y recuperable (regla global)

Por qué: una sesión archivada con trabajo a medias, sin publicar o solo en su worktree lo esconde, y al archivarla la app
puede limpiar ese worktree.

- **Terminada:** no le queda nada de su encargo, nada suyo sigue en marcha y lo entregado está comprobado.
- **Publicada:** el trabajo está donde dice el flujo del proyecto (commit, integración y push si hay remoto). Esta regla
  no autoriza a publicar: commit, push, merge y publicación se hacen solo como los autoricen las reglas escritas del
  proyecto o el desarrollador (`~/.claude/rules/despliegue-y-limites-duros.md`). Desplegar es otra cosa.
- **Recuperable:** sus commits están en una rama que se conserva y en su worktree no hay ficheros sin versionar, tampoco
  ignorados, que se perderían al limpiarlo.
- Si falta una de las tres, **no se cierra ni se archiva**: se dice qué falta y de quién depende. Si falta una
  autorización, se apunta en `ask-queue` y el resto del trabajo sigue.
- **Archivar y borrar:** solo lo verificado con esas tres condiciones y, además, con el permiso del desarrollador (su
  orden o una regla escrita del proyecto). Un hook o un comando que señale una sesión como terminada no es ese permiso.
  Borrar sesiones, ramas con trabajo, worktrees con cambios o stashes es un límite duro.
- Nunca entran en un commit los ficheros de otra sesión.
