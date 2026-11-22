# Matar procesos: solo los propios, por PID o con una marca única (regla global)

- `pkill -f`, `killall`, `kill $(pgrep …)` y `pgrep … | xargs kill` buscan en **todos** los procesos del usuario: los
  de las demás sesiones, la app de Claude, el escritorio y los contenedores que corren con su uid. Un patrón pensado para
  un bucle propio (`pkill -f monitor`) puede cerrar la sesión de escritorio entera, con la app y todas las sesiones, o
  parar el router de desarrollo compartido.
- **Se mata solo lo propio:**
  - `kill <PID>` de lo que lanzó la sesión (`$!`, un fichero `.pid`, o lo que se vio antes con `pgrep -af`);
  - `pkill -P <PID>` para sus hijos;
  - o un patrón con una marca única que solo lleve esa orden (`exec -a <marca>`, una ruta del scratchpad).
- **Lo impone `~/.claude/hooks/process-kill-gate`.** Antes de ejecutar la orden, evalúa el patrón contra los procesos
  vivos y la deniega si alcanza alguno que no sea de la sesión. Es de la sesión lo que desciende de su proceso
  `claude` o lleva su `CLAUDE_CODE_SESSION_ID`.
  - También deniega `kill -1` y matar por PID el escritorio, la app de Claude, otra sesión (se usa `stop_session`) o un
    contenedor (`ddev stop`, `docker stop`).
- **Si el desarrollador ordena parar algo ajeno** que no esté en esa lista (el navegador, un servidor de otra sesión),
  se hace por PID. No se esquiva la guardia: ni variables para esconder el patrón, ni un script que haga el `pkill`.
