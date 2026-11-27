"""One small HTTP helper over urllib, plus the error type and address helpers the store providers share.

Only GET, POST and DELETE exist here: the store reads never need another verb, so another verb is refused at
the lowest level. Requests to the loopback interface never go through a proxy. A request that carries credentials
(an Authorization header or a body) never follows a redirect: urllib would forward the header to the new host, so
the answer is returned as it is and the caller turns it into an error. Anything registered with add_secret()
(tokens, signed assertions, key lines) is removed from every message this module produces.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = 'claude-toolkit-stores/1'
METHODS = ('GET', 'POST', 'DELETE')
_SECRETS: set[str] = set()


def add_secret(value: str) -> None:
    if value and len(value) >= 8:
        _SECRETS.add(value)


def scrub(text: str) -> str:
    """One line, with every registered secret replaced."""
    for secret in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(secret, '[redacted]')
    return ' '.join(text.split())


class TransportError(Exception):
    """The service could not be reached at all (refused, timed out, bad address)."""


class ServiceError(Exception):
    """The service answered with an error status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    @property
    def exit_code(self) -> int:
        """3 for a permission or credential error, 4 for not found, 1 otherwise."""
        if self.status in (401, 403):
            return 3
        return 4 if self.status == 404 else 1


class Response:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        return json.loads(self.body.decode('utf-8'))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Returning None makes urllib raise the 3xx as an HTTPError, which `request` hands back as a response."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_loopback(url: str) -> bool:
    host = urllib.parse.urlsplit(url).hostname or ''
    return host in ('127.0.0.1', 'localhost', '::1')


def request(method: str, url: str, headers: dict | None = None, body: bytes | None = None,
            timeout: float = 20) -> Response:
    """Send one request. An error status is returned, not raised; an unreachable service raises TransportError."""
    if method not in METHODS:
        raise ValueError(f'method {method} is not allowed')
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise TransportError('the address is not an http(s) address')
    handlers = [urllib.request.ProxyHandler({})] if _is_loopback(url) else []
    credentials = body is not None or any(key.lower() == 'authorization' for key in headers or {})
    if credentials:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('User-Agent', USER_AGENT)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return Response(resp.status, dict(resp.headers), resp.read())
    except urllib.error.HTTPError as err:
        try:
            data = err.read()
        except OSError:
            data = b''
        return Response(err.code, dict(err.headers or {}), data)
    except (urllib.error.URLError, OSError, ValueError) as err:
        reason = getattr(err, 'reason', err)
        raise TransportError(scrub(f'cannot reach {parts.hostname}: {reason}')) from None


def get(url: str, headers: dict | None = None, timeout: float = 20) -> Response:
    return request('GET', url, headers, None, timeout)


def post_form(url: str, fields: dict, timeout: float = 20) -> Response:
    body = urllib.parse.urlencode(fields).encode()
    return request('POST', url, {'Content-Type': 'application/x-www-form-urlencoded'}, body, timeout)


def post_json(url: str, document: dict, headers: dict | None = None, timeout: float = 20) -> Response:
    merged = dict(headers or {}, **{'Content-Type': 'application/json'})
    return request('POST', url, merged, json.dumps(document).encode(), timeout)


def delete(url: str, headers: dict | None = None, timeout: float = 20) -> Response:
    return request('DELETE', url, headers, None, timeout)


def service_error(resp: Response) -> ServiceError:
    """The one-line error for a failed response: Google style, token style, App Store Connect style or bare status."""
    message = ''
    try:
        doc = resp.json()
    except (ValueError, UnicodeDecodeError):
        doc = None
    if isinstance(doc, dict):
        err = doc.get('error')
        if isinstance(err, dict):
            code = err.get('status') or ''
            text = err.get('message') or ''
            message = f'{code}: {text}'.strip(': ')
        elif isinstance(err, str):
            message = f'{err}: {doc.get("error_description") or ""}'.strip(': ')
        elif isinstance(doc.get('errors'), list) and doc['errors'] and isinstance(doc['errors'][0], dict):
            first = doc['errors'][0]
            message = f'{first.get("code") or ""}: {first.get("detail") or first.get("title") or ""}'.strip(': ')
    return ServiceError(resp.status, scrub(f'HTTP {resp.status} {message}'.strip()))


def quote(value) -> str:
    return urllib.parse.quote(str(value), safe='')


def fill(template: str, _raw: tuple = (), **values) -> str:
    """Fill {name} placeholders with url-quoted values; names in _raw are inserted as they are (a path with slashes)."""
    return template.format(**{k: (str(v) if k in _raw else quote(v)) for k, v in values.items()})
