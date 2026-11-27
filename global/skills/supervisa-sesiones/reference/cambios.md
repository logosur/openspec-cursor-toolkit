# supervisa-sesiones: cambios que piden un paso al recargar

> Referencia del núcleo (`../SKILL.md`). Se lee al recargar la skill tras un `SKILL_CHANGED`, desde la última entrada
> que ya aplicaste.

El núcleo no lleva pasos de «al recargar», porque cada párrafo de más lo acerca al tamaño que la app conserva tras
compactar. Si un cambio de la skill pide que una supervisora en marcha haga algo una sola vez (rearmar el vigilante,
repasar sus aparcados), el paso se escribe aquí, la entrada más reciente arriba:

```markdown
## <versión o fecha del cambio>: <título corto>

1. <qué leer de nuevo y dónde>
2. <qué hacer una vez, con su comando>
```

Al recargar, se aplican las entradas desde la última anotada en tu historial y se anota hasta dónde llegaste.

## 2026-11-27 (2): tanda parcial de las preguntas que bloquean

1. Lee `f5-decisiones.md`, «Antes del final: rumbo radical y tanda parcial», y la fila `ASKDUE` de `vigilancia.md`.
2. Ejecuta una vez `~/.claude/scripts/ask-queue list --due --project "<checkout del proyecto>"`.
3. Si la última línea dice `due now`, manda ya la tanda parcial: `ask-queue asked <ids> --to <id de la sesión de
   preguntas>` y todas juntas a la sesión de preguntas, como un radical. Si dice `window closed until`, anota la hora.
4. Si tu último parte o tu registro dicen que algo espera la respuesta del desarrollador y esa pregunta no se le
   presentó, corrígelo en el parte siguiente: di que se le ha mandado y dónde la verá.
5. Rearma el vigilante: el código nuevo avisa con `ASKDUE`.

## 2026-11-27: nombres de sesión, copias de Control remoto y sesiones hijas

1. Lee `arranque.md`, «Nombres de sesión» (F0b), y las líneas de título de `f4b-cierre-de-sesiones.md` y `f5-decisiones.md`.
2. Ejecuta `$L titles --session <tu id>` y renombra con `set_session_title` cada sesión que lista en una línea `RENAME`
   (la tuya con `"self"`).
3. Si lista `LOCK <clave> «actual» -> «esperado»`, el título del cerrojo es otro: `$L beat --session <tu id> --title "<esperado>"`.
   Las copias de Control remoto (`REMOTE …`) las renombra el vigilante del sistema; no hagas nada con ellas.
4. Si lista `ADOPT <id> <rol> (…)`, la sesión de preguntas o de cierre no cuelga de ti. Aplica lo de `arranque.md`
   («Sesiones hijas en la barra lateral») en el siguiente turno que el desarrollador inicie en tu sesión; antes, nada.

Sin pasos pendientes.
