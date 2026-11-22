# Worktrees: dónde se crean (regla global)

Por qué: los worktrees repartidos por cualquier carpeta se pierden, chocan entre sesiones y, en un proyecto con un
contenedor de desarrollo, quedan fuera de lo que el contenedor ve. Una sola ubicación calculada evita las tres cosas.

- **Proyecto sin contenedor de proyecto (DDEV):** `<root>/<proyecto>/worktree-<rama>-<AAAAMMDD>`. `<root>` es la clave
  `root` de la pieza de configuración `worktree-location` (por defecto `~/worktrees`).
- **Proyecto con DDEV** (`.ddev/config.yaml` en el checkout principal, en una carpeta padre dentro de `$HOME` o hasta dos
  niveles más abajo): `<repo>/.claude/worktrees/worktree-<rama>-<AAAAMMDD>`, porque el contenedor solo ve la carpeta
  del proyecto. `worktree-location where` dice cuál le toca a un repo.
- Vale para todos los worktrees (de sesión, de subagente, de verificación y temporales) y manda sobre la ruta que fije un
  proyecto. El nombre de la rama lo decide el proyecto.
- **A mano:** `~/.claude/scripts/worktree-location add [--repo DIR] [--base REF] RAMA` (o `--detach`); `path RAMA` solo
  calcula la ruta. Nunca `git worktree add` con otra ruta: `worktree-location-gate` lo deniega. La app, `--worktree`,
  `EnterWorktree`, los subagentes con `isolation: "worktree"` y `/fork` pasan por el hook `WorktreeCreate`.
- **Cerrar:** hook `WorktreeRemove` o `git worktree remove <ruta>`, sin `--force` mientras quede trabajo sin guardar. Si
  el worktree tiene DDEV propio, antes `ddev delete` en él.
- En proyectos con DDEV, linters, bundlers y test runners que recorren el árbol ignoran `.claude/worktrees/`.
- Los worktrees que ya existían no se mueven: se terminan y se cierran donde están.
- Un repositorio con su propio flujo de worktrees (un `make worktree-create`, un script de preparación) lo declara en su
  `CLAUDE.md`, y ese flujo manda en él.
