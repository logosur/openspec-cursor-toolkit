"""The texts with which the gate denies a question."""
import json

from . import ask_gate, session_roles, settings


def deny_parked_tool(kind, lock):
    """Deny json for ExitPlanMode / start_session(initiation "offer") from a supervised session or a lock owner."""
    lock = lock if isinstance(lock, dict) else {}
    who = lock.get('title') or lock.get('session_id') or 'la supervisora'
    project = lock.get('project') or 'este proyecto'
    if kind == 'plan':
        what = ('Pedir que se apruebe un plan (ExitPlanMode) deja la sesión parada hasta que el desarrollador conteste, y '
                'no está delante: no se aprueba ningún plan. Anota el plan en tu informe (o en el registro de decisiones) y '
                'ejecútalo, decidiendo con lo documentado o con el panel de ' + PANEL_SKILL + '.')
    else:
        what = ('Una sesión propuesta con initiation «offer» espera a que el desarrollador pulse la tarjeta, y no '
                'está delante. Hazlo en esta misma sesión, o ábrela con initiation «user_asked» o «own_initiative», '
                'sin esperar a nadie.')
    reason = (f'Esta sesión la supervisa «{who}» ({project}) y nadie espera al desarrollador hasta la tanda final '
              f'({settings.DEPLOY_RULE}). {what}')
    return json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': reason}})


def deny_question(owner, local):
    project, mailbox = owner.get('project'), owner.get('mailbox')
    head = (f'Eres la supervisora de {project} (cerrojo {owner.get("key")}): no le preguntas al desarrollador, ni en un '
            f'diálogo propio, ni en la caja de fin de turno, ni en prosa, salvo cuando te está escribiendo aquí '
            f'(mensaje suyo de hace menos de {ask_gate.ask_gate_fresh_minutes():g} min, o de los últimos '
            f'{ask_gate.ask_gate_presence_minutes():g} pidiendo que le preguntes o dándote una orden que otro control quiere '
            f'confirmar en un diálogo); ahora no es el caso. Decide tú con las fuentes (F5) o con el '
            f'panel, eligiendo {settings.DECISION_CRITERION}. Un límite duro, o una duda que el '
            f'panel no vote radical por unanimidad, va a ask-queue para la tanda final, y sigues. Antes del final solo '
            f'va a la sesión de preguntas una decisión que el panel votó radical por unanimidad (ask-queue add '
            f'--radical --cost), y la tanda parcial: las preguntas de la cola que bloquean trabajo y nunca se le '
            f'presentaron (`ask-queue list --due`: las que bloquean una orden suya, con --order, y las que llevan '
            f'tiempo bloqueando trabajo real), todas juntas, como un radical, cuando te llegue ASKDUE. Mientras no se '
            f'le presenten, ningún informe dice que algo espera su respuesta. La tanda final se manda una sola vez (F9), cuando todo está integrado (y, donde las '
            f'reglas lo autorizan, desplegado en pre-producción) y cada sesión hija está archivada o, sin autorización para archivarla, aparcada con su '
            f'decisión en ask-queue: la sesión de preguntas la presenta entera como diálogos de preguntas, sin informe '
            f'aparte, y tú conservas el cerrojo de guardia (F9). ')
    tail = ' Termina el turno con la caja solo con el resumen, sin pregunta ni botones.'
    if session_roles.mailbox_alive(mailbox):
        reason = head + f'Para eso, la sesión de preguntas es {mailbox} (SendMessage).' + tail
    else:
        reason = (head + 'Para eso, si no tienes sesión de preguntas, ábrela '
                  f'(F5: start_session «{settings.questions_title(project)}») y guárdalo con '
                  f'supervisor-lock beat --session {local} --mailbox <id>.' + tail)
        if mailbox:
            reason = f'(La sesión de preguntas {mailbox} guardada en el cerrojo ya no existe o está archivada.) ' + reason
    return json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': reason}})


PANEL_SKILL = '~/.claude/skills/panel-de-decision/SKILL.md'


def deploy_sentence():
    """What a session may do about deploys: only what the developer authorised in writing (config), never by default."""
    if settings.DEPLOY_PREAUTHORISED:
        excluded = (f', salvo en {", ".join(settings.EXCLUDED_PROJECTS)}' if settings.EXCLUDED_PROJECTS else '')
        return (f'2) El desarrollador ha autorizado por escrito el despliegue a pre-producción ({settings.DEPLOY_RULE}), '
                f'así que ya está autorizado{excluded}: commit, integración en la rama principal, push y deploy con el '
                f'comando documentado del proyecto y sus salvaguardas (copia, dry run si lo hay, verificación desde '
                f'fuera). «¿Sigo?», «¿despliego?» y «he terminado» no son preguntas. ')
    return (f'2) Desplegar, también a pre-producción, no está autorizado salvo que las reglas escritas del proyecto o una '
            f'orden escrita del desarrollador lo autoricen ({settings.DEPLOY_RULE}); lo mismo vale para commit, push e '
            f'integración. Lo que esté autorizado se hace con el comando documentado y sus salvaguardas; lo que no, va '
            f'a ask-queue para la tanda final y sigues con lo demás. «¿Sigo?» y «he terminado» no son preguntas, y '
            f'«¿despliego?» tampoco: lo responde la regla escrita o la cola. ')


def deny_absent(minutes, last_s=None, fresh=None):
    """Deny json for a free session whose developer is away. With `last_s` (age in s of the developer's last message,
    inside the presence window) the head says it is too old and does not ask to be asked, instead of claiming silence."""
    if last_s is None:
        head = f'El desarrollador no está delante (no ha escrito en esta sesión en los últimos {minutes:g} min)'
    else:
        head = (f'El desarrollador no está delante (su último mensaje en esta sesión fue hace {max(1, round(last_s / 60))} '
                f'min, no hace menos de {fresh or ask_gate.ASK_GATE_FRESH_MIN:g}, y no pide que se le pregunte)')
    excluded = (f', push o deploy en {", ".join(settings.EXCLUDED_PROJECTS)}'
                if settings.DEPLOY_PREAUTHORISED and settings.EXCLUDED_PROJECTS else '')
    reason = (
        f'{head} y no quiere '
        f'ninguna sesión parada esperándole: no le preguntes, ni en un diálogo, ni en la caja de fin de turno, ni en '
        f'prosa. La regla es {settings.DEPLOY_RULE}. Haz esto: '
        f'1) Decide tú con lo documentado (reglas y CLAUDE.md del proyecto, ~/.claude/rules, el registro de decisiones '
        f'del proyecto) y, si no lo zanja, con el panel de {PANEL_SKILL} (hasta 3 agentes). Elige '
        f'{settings.DECISION_CRITERION}. Anota la decisión con su fuente en '
        f'el registro de decisiones del proyecto y continúa. '
        + deploy_sentence() +
        f'3) Un límite duro no se hace y no para nada: dinero fuera de un presupuesto aprobado, credenciales o cuentas '
        f'nuevas, un dato que solo sabe el desarrollador, borrar trabajo ajeno o datos sin copia, cambiar de familia de modelo, '
        f'envíos reales a terceros, cambios de infraestructura compartida (servidores, DNS){excluded}, reescribir '
        f'historia. Regístralo para la tanda final con '
        f'`~/.claude/scripts/ask-queue add --project "$PWD" --question … --default "No hacerlo" --why … --blocks …` '
        f'y sigue con todo lo demás. En --blocks escribe el trabajo que de verdad bloquea («nada» si no bloquea nada) '
        f'y, si bloquea algo que el desarrollador ordenó, añade --order "<sus palabras>": así entra en la tanda '
        f'parcial y no espera al final. '
        f'4) Si una supervisora lleva este proyecto, la duda que no puedas decidir va a decisiones_abiertas de tu '
        f'informe para ella, y sigues con lo demás. Al desarrollador se le pregunta todo a la vez al final, en la '
        f'sesión de preguntas, cuando no queda ninguna spec por implementar, todo está integrado (y, donde las reglas '
        f'lo autorizan, desplegado en pre-producción) y cada sesión hija está archivada o aparcada con su decisión en ask-queue. '
        f'Antes del final solo se adelantan un rumbo radical votado por unanimidad y la tanda parcial de las preguntas '
        f'que bloquean trabajo (`ask-queue list --due`). '
        f'En wrap_up, quita `ask` y `actions` y deja solo el recap.')
    return json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': reason}})


def deny_supervised(lock, minutes):
    """Deny json for a question from a session whose project has a live supervisor lock (it is not the owner)."""
    lock = lock if isinstance(lock, dict) else {}
    who = lock.get('title') or lock.get('session_id') or 'la supervisora'
    project = lock.get('project') or 'este proyecto'
    reason = (
        f'Esta sesión la supervisa «{who}» ({project}), y el desarrollador no está delante: no ha escrito aquí hace menos de '
        f'{ask_gate.ask_gate_fresh_minutes():g} min ni, en los últimos {minutes:g} min, ha pedido que se le pregunte. Solo se le '
        f'pregunta en una sesión que esté llevando en persona. Lo demás se le pregunta todo a la vez al final, en la sesión '
        f'de preguntas, cuando todo está integrado (y, donde las reglas lo autorizan, desplegado en pre-producción) y cada '
        f'sesión hija está archivada o aparcada con su decisión en ask-queue ({settings.DEPLOY_RULE}). Decide tú con lo documentado '
        f'o con el panel de {PANEL_SKILL}, eligiendo {settings.DECISION_CRITERION}, y anótala. Si no puedes, deja la duda en '
        f'decisiones_abiertas de tu informe a la supervisora, con las opciones y la que recomiendas, y sigue con todo '
        f'lo que no dependa de ella: la supervisora la contesta. Un límite duro (dinero, credenciales, un dato que '
        f'solo sabe el desarrollador, envíos a terceros, borrar trabajo ajeno) no se hace: va a la supervisora o a `ask-queue add` '
        f'para la tanda final, con lo que de verdad bloquea en --blocks; si bloquea algo que el desarrollador ordenó, con '
        f'--order "<sus palabras>", y la supervisora se la presenta antes, en la tanda parcial (`ask-queue list --due`). '
        f'Mientras no se le haya presentado, no digas que algo espera su respuesta. En wrap_up, quita `ask` y `actions` y deja solo el recap.')
    return json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': reason}})
