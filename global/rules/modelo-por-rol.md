# Modelo por rol: capacidad según el trabajo (regla global)

Por qué: un modelo capaz en tareas mecánicas gasta de más y uno barato en decisiones delicadas obliga a rehacer. Se
elige por rol. Los modelos concretos, si hacen falta, los fija el desarrollador en su override o en las reglas del
proyecto.

| Rol | Qué hace | Modelo | Esfuerzo |
|-----|----------|--------|----------|
| Supervisor | Censo, turnos, decisiones e integración autorizada | El que eligió quien la abrió | Alto |
| Orquestador | Reparte una spec en micro-tareas; no escribe código | El de la supervisora; más barato si el reparto es simple | Alto |
| Implementador | Escribe código en micro-tareas, cada una con su comprobación | Más barato; más capaz para una pieza compleja | Medio o alto |
| Panel | Hasta tres agentes de solo lectura que votan | Más capaz | Alto |
| Mensajero | Sesión de preguntas: abre los diálogos y nada más | Más barato | Bajo |
| Cierre | Comprueba en disco lo terminado; no escribe código | Más barato | Medio o alto |

- Quien lanza una sesión o un subagente le da el modelo y el esfuerzo de su rol, y después lo comprueba.
- Una pieza es compleja si toca arquitectura, seguridad, concurrencia o varios módulos, si es un fallo difícil o tras
  dos intentos fallidos con hipótesis distintas.
- A una sesión que ya existía no se le cambia el modelo por iniciativa propia: se dice y elige el desarrollador.
- Un modelo fuera de lo que el desarrollador configuró, o que se factura aparte, es una decisión de dinero: espera al
  desarrollador.
