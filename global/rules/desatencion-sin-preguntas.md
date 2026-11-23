# Trabajo desatendido: decidir lo delegado y no parar el resto (regla global)

Por qué: una pregunta en una sesión que nadie mira deja parado también el trabajo que no dependía de ella. Se aplica a
las sesiones supervisadas y a las que el desarrollador haya dejado desatendidas; con el desarrollador delante, se le
puede preguntar.

- **Se decide lo que está dentro del encargo** con lo documentado: la orden, las reglas del proyecto, su registro de
  decisiones y las reglas globales. Elecciones técnicas, orden de trabajo, reintentos y «¿sigo?» no son preguntas.
- **Si lo documentado no lo zanja**, decide un panel (`~/.claude/skills/panel-de-decision/SKILL.md`) o, en una sesión
  supervisada, la supervisora. La decisión se anota con quién la tomó de verdad, su fuente y cómo se deshace.
- **Lo que exige autorización no se decide:** commit, push, merge, publicar, desplegar, archivar y los límites duros
  (`~/.claude/rules/despliegue-y-limites-duros.md`). Sin autorización va a `~/.claude/scripts/ask-queue` con «No hacerlo»
  por defecto, y la sesión sigue con lo que no dependa de eso.
- **Las preguntas se agrupan** en la sesión de preguntas cuando hay supervisora, al final de su ciclo. Solo se adelanta
  un rumbo radical votado por unanimidad del panel.
- **Desarrollador presente:** si ha escrito en esa sesión hace muy poco, o en los últimos `presence_min` minutos (pieza
  de configuración `supervision`, 20 por defecto) pidiendo que se le pregunte, se le pregunta allí.
- Que un hook impida preguntar no concede permiso: lo no autorizado sigue sin hacerse.
