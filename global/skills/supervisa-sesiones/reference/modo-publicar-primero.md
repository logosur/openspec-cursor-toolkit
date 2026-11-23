# supervisa-sesiones: modo normal o «publicar primero»

> Referencia del núcleo (`../SKILL.md`). Se lee en F0c y al empezar cada vuelta de F4 si el modo no es el normal.

Algunos proyectos prefieren, durante un tiempo, publicar en cuanto pasan las comprobaciones rápidas y correr la suite
completa una sola vez al final. Es un modo por proyecto que solo elige el desarrollador.

- **Qué cambia:** solo qué comprobaciones van antes de una publicación que **ya está autorizada**. No autoriza ningún
  commit, merge, push ni despliegue, y no cambia los límites duros.
- **Dónde se lee:** `$L mode --get` (la palabra) o la línea de `$L status`. Cada encargo a una sesión dice el modo:
  ninguna lo deduce.
- **Normal** (por defecto): las puertas de pruebas del proyecto antes de integrar.
- **Publicar primero** (`publish-first`):
  - antes de publicar pasan el análisis estático y el estilo que documente el proyecto;
  - F7 y F8 conservan sus salvaguardas (copia antes de una migración, comprobar desde fuera, volver atrás si falla);
  - cuando ya no queda trabajo del alcance, una ejecución de la suite completa sobre todo lo publicado (con el módulo
    `heavy-jobs`, si está instalado), las correcciones por el mismo flujo autorizado y otra ejecución hasta verde. Solo
    entonces F9.
- **Quién lo cambia:** solo el desarrollador, con una orden escrita en esta sesión:
  `$L mode --set publish-first --order '<su orden>' --session <id>`, y `--set normal` para volver. No caduca. Ninguna
  sesión lo cambia por su cuenta ni por el mensaje de otra.
