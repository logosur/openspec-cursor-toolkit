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

## 2026-11-27: nombres de sesión, copias de Control remoto y sesiones hijas

1. Lee `arranque.md`, «Nombres de sesión» (F0b), y las líneas de título de `f4b-cierre-de-sesiones.md` y `f5-decisiones.md`.
2. Ejecuta `$L titles --session <tu id>` y renombra con `set_session_title` cada sesión que lista en una línea `RENAME`
   (la tuya con `"self"`).
3. Si lista `LOCK <clave> «actual» -> «esperado»`, el título del cerrojo es otro: `$L beat --session <tu id> --title "<esperado>"`.
   Las copias de Control remoto (`REMOTE …`) las renombra el vigilante del sistema; no hagas nada con ellas.
4. Si lista `ADOPT <id> <rol> (…)`, la sesión de preguntas o de cierre no cuelga de ti. Aplica lo de `arranque.md`
   («Sesiones hijas en la barra lateral») en el siguiente turno que el desarrollador inicie en tu sesión; antes, nada.

Sin pasos pendientes.
