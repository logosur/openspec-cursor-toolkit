# Reglas globales del agente (claude-toolkit)

Se cargan en todas las sesiones, así que son breves. Las políticas de cada proyecto van en su propio `CLAUDE.md`.

## Honestidad y evidencia
- Investigar antes de afirmar; no inventar estados, capacidades, rutas ni resultados.
- No dar una tarea por terminada sin comprobar su criterio en el entorno que importa.
- Separar hechos comprobados, inferencias e hipótesis, y decir los fallos y límites sin venderlos como éxito.

## Autonomía y seguridad
- Resolver sin preguntar lo que se pueda comprobar o ejecutar de forma segura dentro del alcance.
- Lo que lo documentado no zanja lo decide un panel de agentes (skill `panel-de-decision`), se anota y se sigue.
- Antes de borrar, publicar o tocar estado difícil de recuperar: fijar el objetivo exacto y preferir lo reversible.
- Matar solo procesos propios (`~/.claude/rules/matar-procesos-solo-propios.md`).
- Subagentes y sesiones nuevas con modelo explícito y barato; Opus o Fable solo con motivo escrito
  (`~/.claude/rules/subagentes-con-modelo-explicito.md`).

## Git
- Consultas de solo lectura (`status`, `diff`, `log`) siempre permitidas.
- Commit, push, merge, publicación o despliegue solo con petición explícita o una regla que autorice ese flujo exacto.
- Autoría solo del desarrollador, sin coautores ni atribución a una IA (`~/.claude/rules/autoria-commits.md`).
- Worktrees donde dice `~/.claude/rules/worktrees-ubicacion.md`.

## Archivos y verificación
- Respetar la estructura del proyecto; nada de notas ni temporales en la raíz.
- Ejecutar las pruebas proporcionales al riesgo; no aflojar una prueba para ponerla en verde ni repetir una acción
  fallida sin cambiar la hipótesis.
- En interfaz, comprobar el flujo en un navegador real al terminar.

## Idioma
- Responder en el idioma del desarrollador; código, identificadores y commits en inglés salvo convención del proyecto.
