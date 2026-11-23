"""Sessions cut by a usage limit or an API error, and their resumption."""
import glob
import json
import os
import time

from . import census, closable, lock as lock_mod, providers, transcripts, util


# A session cut by a usage limit or an API error (its transcript ends in an API error record) looks finished ("no
# process") but is not: once the limit lifts, nothing resumes it. A session whose newest record is an API error is CUT:
# never closable, and `wait --owner` says CUT once it can be resumed.
CUT_API_MIN_S = 120          # an API error older than this is not a blip the CLI retries: resume it
CUT_RESUME_MAX_S = 48 * 3600  # a cut older than this is no longer announced (the announced pairs are pruned at 48 h)
CUT_BLOCK_EVERY_S = 600


def cut_info(row):
    """{reason, since, text} when the newest record of the session's main transcript is an assistant API error (a usage
    limit or an API failure cut its turn), else None. reason is 'limit' for error == 'rate_limit', else 'api'."""
    main = transcripts.session_files(row.get('cli'), row.get('cwd'))[0] if row.get('cli') else None
    recs = transcripts.conv_records(main) if main else []
    if not recs or recs[-1]['type'] != 'assistant' or not recs[-1].get('isApiErrorMessage'):
        return None
    text = next((it.get('text') for it in transcripts.content_items(recs[-1]) if it.get('type') == 'text'), '')
    return {'reason': 'limit' if recs[-1].get('error') == 'rate_limit' else 'api', 'since': recs[-1]['_ts'],
            'text': str(text or '').strip()[:100]}


def resumable_cuts(cuts, now=None):
    """The cut sessions that can be resumed now: an API error older than CUT_API_MIN_S, or a usage limit while the
    account has usage again. The network is asked (cached) only when a limit cut exists. Cuts older than
    CUT_RESUME_MAX_S are left out: they were announced long ago and would repeat for ever."""
    now = time.time() if now is None else now
    usage = []   # asked lazily, once
    out = []
    for e in cuts:
        age = now - e['since']
        if age > CUT_RESUME_MAX_S:
            continue
        if e['reason'] == 'api':
            if age > CUT_API_MIN_S:
                out.append(e)
            continue
        if not usage:
            usage.append(providers.account_has_usage())
        if usage[0] is True:
            out.append(e)
    return out


def announce_cuts(key, cuts, now=None):
    """`CUT <id> <reason>` lines for the resumable cut sessions not announced yet. Each (id, since) pair is announced
    once (<home>/cuts/<key>.json, entries older than 48 h pruned): a session cut again later has a new `since`."""
    now = time.time() if now is None else now
    path = os.path.join(util.home(), 'cuts', key + '.json')
    lines = []
    with lock_mod.Store():
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        data = {k: v for k, v in (data if isinstance(data, dict) else {}).items()
                if util.num(v) is not None and now - v < closable.HOLD_HISTORY_S}
        changed = False
        for e in cuts:
            pair = f'{e["id"]}@{int(e["since"])}'
            if pair not in data:
                data[pair] = now
                lines.append(f'CUT {e["id"]} {e["reason"]}')
                changed = True
        if changed:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + f'.{os.getpid()}.tmp'
            with open(tmp, 'w') as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
    return lines


def cut_block(owner, local):
    """Stop-hook reason when sessions of the project are cut (usage limit or API error) and can be resumed now, or ''.
    Reads the same cache as closable_block (resumable cuts, written by `wait`, so no network here), re-checks holds, the
    app's archived flag and that the transcript still ends in the error; at most one block per CUT_BLOCK_EVERY_S per
    lock (its own stamp)."""
    key = owner.get('key')
    cache = closable.read_closable_cache(key, local)
    if cache is None:
        return ''
    stamp = os.path.join(util.home(), 'closable', key + '.cutblocked')
    if time.time() - util.file_mtime(stamp) < CUT_BLOCK_EVERY_S:
        return ''
    holds = closable.read_holds(key)
    pending = []
    for e in cache.get('cut') or []:
        if not isinstance(e, dict) or e.get('id') in holds:
            continue
        recs = list(census.read_json_files(os.path.join(os.path.dirname(census.app_glob()), glob.escape(str(e.get('id'))) + '.json')))
        if any(rec.get('isArchived') for rec in recs):
            continue
        if recs and cut_info({'cli': recs[0].get('cliSessionId'), 'cwd': recs[0].get('cwd')}) is None:
            continue  # it moved on since the cache was written (the supervisor or the developer resumed it)
        pending.append(e)
    if not pending:
        return ''
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    open(stamp, 'w').close()
    names = ', '.join(f'«{e.get("title")}» ({e.get("id")})' for e in pending)
    usage = ' La cuenta tiene uso ahora.' if any(e.get('reason') == 'limit' for e in pending) else ''
    return (f'Eres la supervisora de {owner.get("project")} y vas a terminar el turno con sesiones del proyecto cortadas '
            f'por el límite de uso o por un error de la API que ya pueden seguir: {names}.{usage} Antes de terminar, '
            f'mira `get_usage` y envía a cada una un mensaje (SendMessage) para que retome lo que hacía; todas, sin '
            f'escalonarlas por tu cuenta: una sesión cortada no se reanuda sola. Si alguna no debe seguir todavía por una regla escrita, apártala '
            f'con `supervisor-lock hold --session {local} --target <id> --reason \'<la regla>\'`. Una sesión cortada no '
            f'se cierra: no ha terminado.')
