"""App Store Connect provider: versions, builds and review submissions through the API, read-only.

Every request is a GET. The token is a signed ES256 JWT built per run (15 minutes) and sent as a bearer; there is
no token exchange. The numeric app id comes from the app's console_id in the config piece or is resolved from its
bundle id.
"""
from __future__ import annotations

from . import http, store_auth

NAME = 'ios'
LABEL = 'App Store Connect'
READS = ('versions', 'builds', 'review')
DEFAULTS = {
    'key_id': '', 'issuer_id': '', 'key_file': '',
    'api_url': 'https://api.appstoreconnect.apple.com/v1',
    'public_url': 'https://itunes.apple.com/lookup?bundleId={id}',
    'console_url': 'https://appstoreconnect.apple.com/apps',
    'app_path': '{console_id}/{page}',
    'pages': {'distribution': 'distribution', 'testflight': 'testflight/ios'},
}


class Session:
    def __init__(self, cfg: dict, timeout: float):
        self.cfg, self.timeout = cfg, timeout
        self._token: str | None = None
        self.warnings: list[str] = []

    def token(self) -> str:
        if self._token is None:
            from . import settings
            path = str(settings.expand(self.cfg['key_file']))
            store_auth.require_private(path)
            self._token = store_auth.apple_token(self.cfg['key_id'], self.cfg['issuer_id'], store_auth.read_pem(path))
        return self._token

    def get(self, path: str, params: dict | None = None) -> dict:
        url = self.cfg['api_url'].rstrip('/') + path
        if params:
            url += '?' + '&'.join(f'{http.quote(k)}={http.quote(v)}' for k, v in params.items())
        resp = http.get(url, {'Authorization': f'Bearer {self.token()}', 'Accept': 'application/json'}, self.timeout)
        if not resp.ok:
            raise http.service_error(resp)
        return resp.json()

    def app_id(self, alias: str, app: dict) -> str:
        if app.get('console_id'):
            return str(app['console_id'])
        found = (self.get('/apps', {'filter[bundleId]': app['id'], 'limit': 1}).get('data') or [])
        if not found:
            raise http.ServiceError(404, f'no app with bundle id {app["id"]} in this team')
        return str(found[0]['id'])


def _total(doc: dict, shown: int) -> int:
    paging = (doc.get('meta') or {}).get('paging') or {}
    total = paging.get('total')
    return total if isinstance(total, int) and total >= shown else shown


def read_checks(cfg: dict, apps: dict) -> list[store_auth.Check]:
    mine = [a for a in apps.values() if a.get('provider') == NAME and a.get('id')]
    checks = [store_auth.Check('an app is configured for ios', bool(mine),
                               'add an app with provider ios and its bundle id under apps in the config piece stores'),
              store_auth.Check('ios.key_id configured', bool(cfg.get('key_id')), 'set ios.key_id to the API key id'),
              store_auth.Check('ios.issuer_id configured', bool(cfg.get('issuer_id')), 'set ios.issuer_id to the issuer id of the API keys page')]
    checks += store_auth.key_checks('ios.key_file', cfg.get('key_file') or '', 'ec-p256')
    checks.append(store_auth.openssl_check())
    return checks


def live_checks(cfg: dict, apps: dict, timeout: float) -> list[store_auth.Check]:
    session = Session(cfg, timeout)
    grant = ('the account owner must grant this API key a role in the console, on the users and access page '
             'under integrations')
    try:
        session.get('/apps', {'limit': 1})
        checks = [store_auth.Check('token accepted by the service', True)]
    except http.ServiceError as err:
        return [store_auth.Check('token accepted by the service', False,
                                 grant + f' ({err.message})' if err.status in (401, 403) else f'the service answered: {err.message}')]
    except (store_auth.AuthError, http.TransportError) as err:
        return [store_auth.Check('token accepted by the service', False, f'could not call the service ({err})')]
    for alias, app in sorted(apps.items()):
        if app.get('provider') != NAME or not app.get('id'):
            continue
        name = f'access to {app["id"]} ({alias})'
        try:
            app_id = session.app_id(alias, app)
            session.get(f'/apps/{http.quote(app_id)}/appStoreVersions', {'limit': 1})
            checks.append(store_auth.Check(name, True))
        except http.ServiceError as err:
            checks.append(store_auth.Check(name, False, (grant if err.status == 403 else f'the service answered') + f' ({err.message})'))
        except http.TransportError as err:
            checks.append(store_auth.Check(name, False, str(err)))
    return checks


def console_url(cfg: dict, alias: str | None, app: dict | None, page: str | None) -> str:
    base = cfg['console_url'].rstrip('/')
    if app is None:
        return base
    if not app.get('console_id'):
        raise KeyError(f'apps.{alias}.console_id')
    pages = cfg['pages']
    page = page or next(iter(pages))
    return base + '/' + http.fill(cfg['app_path'], _raw=('page',), console_id=app['console_id'], page=pages.get(page, page))


def public(cfg: dict, app: dict, timeout: float) -> dict:
    url = http.fill(cfg['public_url'], id=app['id'])
    resp = http.get(url, None, timeout)
    if not resp.ok:
        raise http.service_error(resp)
    try:
        doc = resp.json()
    except ValueError:
        raise http.ServiceError(1, 'the lookup answered with something that is not JSON') from None
    results = doc.get('results') or []
    if not doc.get('resultCount') or not results:
        return {'public': False, 'url': url}
    return {'public': True, 'url': (results[0] or {}).get('trackViewUrl') or url}


def team_apps(session: Session, limit: int) -> dict:
    doc = session.get('/apps', {'limit': max(1, min(limit, 200))})
    lines = [f'{a.get("id")}  {(a.get("attributes") or {}).get("bundleId")}  {(a.get("attributes") or {}).get("name")}'
             for a in doc.get('data') or []]
    return {'header': 'apps of the team', 'lines': lines, 'total': _total(doc, len(lines)),
            'data': {'apps': [{'id': a.get('id'), **(a.get('attributes') or {})} for a in doc.get('data') or []]}}


def versions(session: Session, alias: str, app: dict, limit: int) -> dict:
    app_id = session.app_id(alias, app)
    doc = session.get(f'/apps/{http.quote(app_id)}/appStoreVersions', {'limit': max(1, min(limit, 200))})
    rows = [a.get('attributes') or {} for a in doc.get('data') or []]
    lines = [f'{r.get("platform")}  {r.get("versionString")}  {r.get("appStoreState")}' for r in rows]
    return {'header': f'versions of {app["id"]} ({alias})', 'lines': lines, 'total': _total(doc, len(lines)),
            'data': {'app': alias, 'versions': [{'platform': r.get('platform'), 'version': r.get('versionString'),
                                                 'state': r.get('appStoreState')} for r in rows]}}


def builds(session: Session, alias: str, app: dict, limit: int) -> dict:
    app_id = session.app_id(alias, app)
    doc = session.get('/builds', {'filter[app]': app_id, 'sort': '-uploadedDate', 'limit': max(1, min(limit, 200))})
    rows = [a.get('attributes') or {} for a in doc.get('data') or []]
    lines = [f'{r.get("version")}  {r.get("uploadedDate")}  {r.get("processingState")}  '
             f'expired {"yes" if r.get("expired") else "no"}' for r in rows]
    return {'header': f'builds of {app["id"]} ({alias})', 'lines': lines, 'total': _total(doc, len(lines)),
            'data': {'app': alias, 'builds': [{'build': r.get('version'), 'uploaded': r.get('uploadedDate'),
                                               'state': r.get('processingState'), 'expired': bool(r.get('expired'))}
                                              for r in rows]}}


def review(session: Session, alias: str, app: dict, limit: int) -> dict:
    app_id = session.app_id(alias, app)
    doc = session.get('/reviewSubmissions', {'filter[app]': app_id, 'limit': max(1, min(limit, 200))})
    rows = [a.get('attributes') or {} for a in doc.get('data') or []]
    lines = [f'{r.get("submittedDate") or "(not submitted)"}  {r.get("platform")}  {r.get("state")}' for r in rows]
    return {'header': f'review submissions of {app["id"]} ({alias})', 'lines': lines, 'total': _total(doc, len(lines)),
            'data': {'app': alias, 'submissions': [{'platform': r.get('platform'), 'state': r.get('state'),
                                                    'submitted': r.get('submittedDate')} for r in rows]}}
