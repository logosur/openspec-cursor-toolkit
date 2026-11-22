---
description: "Supervisora de las sesiones del proyecto donde se invoca: censa, reparte turnos, vigila, verifica y agrupa lo que espera al desarrollador; integra, despliega o archiva solo con autorización escrita"
argument-hint: "[alcance] [--no-deploy] [--max-rondas N]"
---

# Supervisa sesiones

Ejecuta la skill global `~/.claude/skills/supervisa-sesiones/SKILL.md` en el proyecto de esta sesión: su checkout
principal y todos sus worktrees, o la carpeta de trabajo que agrupa sus repositorios.

- **Primero el cerrojo:** `~/.claude/scripts/supervisor-lock acquire`. Si otra supervisora del proyecto está viva, no
  arranca.
- **Después**, el núcleo de la skill y la referencia de cada fase al entrar en ella.
- **Argumentos:** `alcance` estrecha el trabajo dentro del proyecto (vacío: lo que las sesiones abiertas ya tienen entre
  manos); `--no-deploy` no entra en el despliegue aunque esté autorizado; `--max-rondas N` (1 a 10, 3 por defecto) son
  las rondas seguidas sin progreso antes de `NO PROGRESS`.

Invocarla no autoriza nada por sí solo. Commit, push, merge, publicación, despliegue y archivado siguen las reglas
escritas del proyecto y las órdenes escritas del desarrollador
(`~/.claude/rules/despliegue-y-limites-duros.md`). La supervisora no sube el modo de permisos de ninguna sesión y no
contesta en nombre del desarrollador: lo que solo puede decidir el desarrollador espera en `ask-queue`, sin parar lo demás.

Termina con el informe de la skill y la línea literal `Supervisor verdict: <VERDICT>`.
