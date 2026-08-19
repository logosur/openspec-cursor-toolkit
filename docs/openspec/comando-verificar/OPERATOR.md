# OPERATOR — comando-verificar

Guía para desarrolladores — verificación profunda con matriz combinatoria.

**Stack-agnóstico:** resuelve URL, auth y comandos de test desde la regla de stack del proyecto (`00-openspec-stack-agnostic.mdc`).

## Cuándo usar

| Situación | Comando |
|-----------|---------|
| Desconfías del "listo" de la IA | `/comando-verificar` + scope |
| Formulario con varios campos/roles | `/comando-verificar <ruta o form_id>` |
| Servicio con ramas de negocio | `/comando-verificar <package> <ServiceClass>` |
| Tras fix UI/AJAX antes de merge | `/comando-verificar` → `/verifica-cierra` |
| Change OpenSpec ya aplicado | `/comando-verificar <slug>` (+ lee `VERIFY.md` del change) |

## Auth y flood (IMPORTANTE)

Matrices multi-rol usan **un intento de login** por usuario. Preferir el **helper E2E documentado** en el proyecto (storage state, fixture users).

Si hay flood → filas `BLOCKED (credentials)`; no reintentar. Ver `auth-credential-failure-no-retry.mdc`.

## URL correcta

Resolver base URL desde la regla de stack del proyecto — **no hardcodear** host/puerto de otro repo.

## Regresión (Phase 4)

Usar los comandos que el proyecto documente, por ejemplo:

- Cache / rebuild cuando cambie bootstrap, DI, routing o assets
- Import de config/migraciones cuando el diff toque config
- Lint en paths tocados
- Tests en el paquete/módulo afectado
- Comprobación de sintaxis JS si aplica
- Gate E2E del proyecto si existe

## OpenSpec + tests

Con scope slug OpenSpec: fusiona filas con `openspec/changes/<slug>/VERIFY.md`. Para batería de tests del change, ver también `/ejecuta-tests-reporte`.
