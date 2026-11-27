"""Google Play provider: tracks, reviews and store listing through the Developer API, read-only.

Requests: the token exchange (POST), opening an edit (POST) and deleting it (DELETE, always, in a `finally`) for
the reads that need an edit, and GETs. An edit is never committed. The API cannot list a developer's apps, so the
apps come from the config piece.
"""
from __future__ import annotations

import datetime as dt

from . import http, store_auth

NAME = 'play'
LABEL = 'Google Play'
READS = ('tracks', 'reviews', 'listing')
DEFAULTS = {
    'developer_id': '', 'console_user': 0, 'key_file': '',
    'api_url': 'https://androidpublisher.googleapis.com/androidpublisher/v3',
    'token_url': 'https://oauth2.googleapis.com/token',
    'public_url': 'https://play.google.com/store/apps/details?id={id}',
    'console_url': 'https://play.google.com/console/u/{user}/developers/{developer}',
    'app_path': 'app/{console_id}/{page}',
    'pages': {'dashboard': 'app-dashboard', 'production': 'tracks/production', 'open-testing': 'tracks/open-testing',
              'closed-testing': 'tracks/closed-testing', 'internal-testing': 'tracks/internal-testing',
              'publishing': 'publishing', 'listing': 'main-store-listing', 'reviews': 'user-feedback/reviews'},
}
REVIEW_WINDOW = 'the service returns only the last week of reviews'


class Session:
    """One run's connection: the token is obtained on first use and kept in memory only."""

    def __init__(self, cfg: dict, timeout: float):
        self.cfg, self.timeout = cfg, timeout
        self._token: str | None = None
        self.warnings: list[str] = []

    def token(self) -> str:
        if self._token is None:
            from . import settings
            path = str(settings.expand(self.cfg['key_file']))
            store_auth.require_private(path)
            key = store_auth.read_google_key(path)
            self._token = store_auth.exchange_google_token(key, self.cfg['token_url'], self.timeout)
        return self._token

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = self.cfg['api_url'].rstrip('/') + path
        if params:
            url += '?' + '&'.join(f'{k}={http.quote(v)}' for k, v in params.items())
        headers = {'Authorization': f'Bearer {self.token()}', 'Accept': 'application/json'}
        if method == 'POST':
            resp = http.post_json(url, body or {}, headers, self.timeout)
        elif method == 'DELETE':
            resp = http.delete(url, headers, self.timeout)
        else:
            resp = http.get(url, headers, self.timeout)
        if not resp.ok:
            raise http.service_error(resp)
        return resp.json() if resp.body.strip() else {}

    def with_edit(self, package: str, work):
        """Open an edit, run WORK(edit_path), delete the edit whatever happens. The edit is never committed."""
        edit = self.call('POST', f'/applications/{http.quote(package)}/edits')['id']
        path = f'/applications/{http.quote(package)}/edits/{http.quote(edit)}'
        try:
            return work(path)
        finally:
            try:
                self.call('DELETE', path)
            except (http.ServiceError, http.TransportError, store_auth.AuthError):
                self.warnings.append(f'edit {edit} could not be deleted; the service drops it by itself')


def read_checks(cfg: dict, apps: dict) -> list[store_auth.Check]:
    mine = [a for a in apps.values() if a.get('provider') == NAME and a.get('id')]
    checks = [store_auth.Check('an app is configured for play', bool(mine),
                               'add an app with provider play and its package id under apps in the config piece stores')]
    checks += store_auth.key_checks('play.key_file', cfg.get('key_file') or '', 'rsa')
    checks.append(store_auth.openssl_check())
    checks.append(store_auth.Check('play.developer_id configured', bool(cfg.get('developer_id')),
                                   'set play.developer_id (the number in the console address) for console addresses',
                                   reads=False))
    return checks


def live_checks(cfg: dict, apps: dict, timeout: float) -> list[store_auth.Check]:
    session = Session(cfg, timeout)
    try:
        session.token()
        checks = [store_auth.Check('token exchange accepted', True)]
    except (store_auth.AuthError, http.ServiceError, http.TransportError) as err:
        message = getattr(err, 'message', None) or str(err)
        return [store_auth.Check('token exchange accepted', False,
                                 f'the service refused the key or could not be reached ({message}); check the key file and play.token_url')]
    for alias, app in sorted(apps.items()):
        if app.get('provider') != NAME or not app.get('id'):
            continue
        name = f'access to {app["id"]} ({alias})'
        try:
            session.with_edit(app['id'], lambda _path: None)
            checks.append(store_auth.Check(name, True))
        except http.ServiceError as err:
            action = (f'the account owner must grant this service account its role in the console, on the users and '
                      f'permissions page ({err.message})' if err.status == 403 else f'the service answered: {err.message}')
            checks.append(store_auth.Check(name, False, action))
        except http.TransportError as err:
            checks.append(store_auth.Check(name, False, str(err)))
    return checks


def console_url(cfg: dict, alias: str | None, app: dict | None, page: str | None) -> str:
    """The console address of the developer account, an app or one of its pages. Raises KeyError(setting name)."""
    if not cfg.get('developer_id'):
        raise KeyError('play.developer_id')
    base = http.fill(cfg['console_url'], user=cfg.get('console_user', 0), developer=cfg['developer_id'])
    if app is None:
        return base
    if not app.get('console_id'):
        raise KeyError(f'apps.{alias}.console_id')
    pages = cfg['pages']
    page = page or next(iter(pages))
    return base + '/' + http.fill(cfg['app_path'], _raw=('page',), console_id=app['console_id'],
                                  page=pages.get(page, page))


def public(cfg: dict, app: dict, timeout: float) -> dict:
    url = http.fill(cfg['public_url'], id=app['id'])
    resp = http.get(url, None, timeout)
    if resp.status == 200:
        return {'public': True, 'url': url}
    if resp.status == 404:
        return {'public': False, 'url': url}
    raise http.service_error(resp)


def _when(seconds) -> str:
    try:
        return dt.datetime.fromtimestamp(int(seconds), dt.timezone.utc).strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError, OverflowError, OSError):
        return '?'


def tracks(session: Session, alias: str, app: dict, limit: int) -> dict:
    doc = session.with_edit(app['id'], lambda path: session.call('GET', f'{path}/tracks'))
    lines, out = [], []
    for track in doc.get('tracks') or []:
        releases = track.get('releases') or []
        out.append({'track': track.get('track'), 'releases': releases})
        if not releases:
            lines.append(f'{track.get("track")}  (no release)')
        for rel in releases:
            codes = ','.join(str(c) for c in rel.get('versionCodes') or []) or '-'
            line = f'{track.get("track")}  {rel.get("name") or "(unnamed)"}  {rel.get("status")}  codes {codes}'
            if rel.get('userFraction') is not None:
                line += f'  rollout {float(rel["userFraction"]) * 100:g}%'
            lines.append(line)
    return {'header': f'tracks of {app["id"]} ({alias})', 'lines': lines, 'total': len(lines),
            'data': {'app': alias, 'package': app['id'], 'tracks': out}}


def reviews(session: Session, alias: str, app: dict, limit: int) -> dict:
    doc = session.call('GET', f'/applications/{http.quote(app["id"])}/reviews',
                       {'maxResults': 100})
    lines, out = [], []
    for review in doc.get('reviews') or []:
        comment = ((review.get('comments') or [{}])[0]).get('userComment') or {}
        stars = comment.get('starRating')
        when = _when((comment.get('lastModified') or {}).get('seconds'))
        lines.append(f'{when}  {stars if stars is not None else "?"}/5  {review.get("authorName") or "anonymous"}: '
                     f'{comment.get("text") or ""}')
        out.append({'reviewId': review.get('reviewId'), 'author': review.get('authorName'), 'stars': stars,
                    'date': when, 'text': comment.get('text')})
    out = out[:limit]
    header = f'reviews of {app["id"]} ({alias}); {REVIEW_WINDOW}'
    if (doc.get('tokenPagination') or {}).get('nextPageToken'):
        header += '; the service has more than the 100 fetched'
    return {'header': header, 'lines': lines, 'total': len(lines),
            'data': {'app': alias, 'package': app['id'], 'note': REVIEW_WINDOW, 'reviews': out}}


def listing(session: Session, alias: str, app: dict, language: str | None, limit: int) -> dict:
    def work(path: str) -> list:
        if language:
            return [session.call('GET', f'{path}/listings/{http.quote(language)}')]
        return session.call('GET', f'{path}/listings').get('listings') or []

    items = session.with_edit(app['id'], work)
    lines, out = [], []
    for item in items:
        full = item.get('fullDescription') or ''
        lines.append(f'{item.get("language") or language}  title: {item.get("title") or ""}  '
                     f'short: {item.get("shortDescription") or ""}  full: {len(full)} characters')
        out.append({'language': item.get('language') or language, 'title': item.get('title'),
                    'shortDescription': item.get('shortDescription'), 'fullDescriptionLength': len(full)})
    return {'header': f'store listing of {app["id"]} ({alias})', 'lines': lines, 'total': len(lines),
            'data': {'app': alias, 'package': app['id'], 'listings': out}}
