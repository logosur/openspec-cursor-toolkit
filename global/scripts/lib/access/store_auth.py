"""Store authentication without a third-party library: token signing through `openssl`, token building, exchange.

Google: service-account key file -> RS256 assertion -> token endpoint -> access token.
App Store Connect: key id, issuer id and a private key -> ES256 token (15 minutes), sent as it is.

The key never goes in an argument list: it is handed to `openssl` through an inherited pipe (/dev/fd/N). A token is
held in memory by the caller and is never printed or passed to another program.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time

from . import http

COMMON_DEFAULTS = {'limit': 20, 'line_width': 160, 'timeout_seconds': 20}
GOOGLE_SCOPE = 'https://www.googleapis.com/auth/androidpublisher'
APPLE_AUDIENCE = 'appstoreconnect-v1'
APPLE_LIFETIME = 900          # seconds; the service refuses more than 20 minutes
GOOGLE_LIFETIME = 3600
_KEY_PLACEHOLDER = '@KEY@'
_PIPE_LIMIT = 60000


class AuthError(Exception):
    """A key or signing problem, in one line without any key material."""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def der_to_raw(der: bytes, size: int = 32) -> bytes:
    """ECDSA signature DER (SEQUENCE of two INTEGERs) -> r and s as `size`-byte big-endian integers, concatenated."""
    def length(buf: bytes, pos: int) -> tuple[int, int]:
        first = buf[pos]
        if first < 0x80:
            return first, pos + 1
        count = first & 0x7F
        return int.from_bytes(buf[pos + 1:pos + 1 + count], 'big'), pos + 1 + count

    try:
        if der[0] != 0x30:
            raise ValueError
        seq_len, pos = length(der, 1)
        if pos + seq_len != len(der):
            raise ValueError
        numbers = []
        for _ in range(2):
            if der[pos] != 0x02:
                raise ValueError
            n_len, pos = length(der, pos + 1)
            numbers.append(int.from_bytes(der[pos:pos + n_len], 'big'))
            pos += n_len
        if pos != len(der):
            raise ValueError
        return b''.join(n.to_bytes(size, 'big') for n in numbers)
    except (ValueError, IndexError, OverflowError):
        raise AuthError('the signature from openssl is not a valid ECDSA signature') from None


def raw_to_der(raw: bytes) -> bytes:
    """The inverse of der_to_raw: 2*size raw bytes -> DER."""
    if not raw or len(raw) % 2:
        raise AuthError('a raw signature has an even, non-zero length')
    half = len(raw) // 2

    def integer(chunk: bytes) -> bytes:
        body = chunk.lstrip(b'\0') or b'\0'
        if body[0] & 0x80:
            body = b'\0' + body
        return b'\x02' + _der_len(len(body)) + body

    content = integer(raw[:half]) + integer(raw[half:])
    return b'\x30' + _der_len(len(content)) + content


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(body)]) + body


def openssl_bin() -> str | None:
    return shutil.which('openssl')


def run_openssl(args: list[str], key_pem: bytes | None = None, stdin: bytes = b'') -> bytes:
    """Run openssl with ARGS; the argument `@KEY@` becomes /dev/fd/N of a pipe that carries KEY_PEM."""
    binary = openssl_bin()
    if binary is None:
        raise AuthError('openssl is not installed')
    read_fd = write_fd = None
    pass_fds: tuple[int, ...] = ()
    cmd = [binary]
    try:
        if key_pem is not None:
            if len(key_pem) > _PIPE_LIMIT:
                raise AuthError('the key is too large')
            read_fd, write_fd = os.pipe()
            os.write(write_fd, key_pem)
            os.close(write_fd)
            write_fd = None
            pass_fds = (read_fd,)
        cmd += [f'/dev/fd/{read_fd}' if a == _KEY_PLACEHOLDER else a for a in args]
        try:
            proc = subprocess.run(cmd, input=stdin, capture_output=True, pass_fds=pass_fds, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise AuthError(http.scrub(f'openssl could not run: {err}')) from None
    finally:
        for fd in (read_fd, write_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
    if proc.returncode != 0:
        first = (proc.stderr.decode('utf-8', 'replace').strip().splitlines() or ['failed'])[0]
        raise AuthError(http.scrub(f'openssl failed: {first}'))
    return proc.stdout


def sign(alg: str, data: bytes, key_pem: bytes) -> bytes:
    """RS256: the signature as openssl makes it. ES256: the raw 64-byte form a token needs."""
    out = run_openssl(['dgst', '-sha256', '-sign', _KEY_PLACEHOLDER], key_pem, data)
    if alg == 'RS256':
        return out
    if alg == 'ES256':
        return der_to_raw(out)
    raise AuthError(f'unknown algorithm {alg}')


def _segment(document: dict) -> str:
    return b64u(json.dumps(document, separators=(',', ':'), sort_keys=False).encode())


def make_jwt(header: dict, claims: dict, key_pem: bytes) -> str:
    signing_input = f'{_segment(header)}.{_segment(claims)}'
    token = f'{signing_input}.{b64u(sign(header["alg"], signing_input.encode("ascii"), key_pem))}'
    http.add_secret(token)
    return token


def key_type(key_pem: bytes) -> str:
    """'rsa', 'ec-p256' or the reason it is neither; openssl must accept the key."""
    text = run_openssl(['pkey', '-noout', '-text', '-in', _KEY_PLACEHOLDER], key_pem).decode('utf-8', 'replace')
    if 'modulus' in text.lower():
        return 'rsa'
    if 'prime256v1' in text or 'P-256' in text:
        return 'ec-p256'
    return 'other'


def register_key(key_pem: bytes) -> None:
    for line in key_pem.decode('utf-8', 'replace').splitlines():
        if line and not line.startswith('-----'):
            http.add_secret(line.strip())


def read_google_key(path: str) -> dict:
    """The service-account JSON, checked for its fields. Messages never carry its content."""
    try:
        with open(path, encoding='utf-8') as handle:
            key = json.load(handle)
    except OSError:
        raise AuthError('the key file cannot be read') from None
    except ValueError:
        raise AuthError('the key file is not a service-account JSON file') from None
    if not isinstance(key, dict):
        raise AuthError('the key file is not a service-account JSON file')
    missing = [name for name in ('client_email', 'private_key') if not isinstance(key.get(name), str) or not key[name]]
    if missing:
        raise AuthError(f'the key file lacks {", ".join(missing)}')
    if 'PRIVATE KEY' not in key['private_key']:
        raise AuthError('the private_key field is not a PEM key')
    register_key(key['private_key'].encode())
    return key


def read_pem(path: str) -> bytes:
    try:
        with open(path, 'rb') as handle:
            data = handle.read(_PIPE_LIMIT + 1)
    except OSError:
        raise AuthError('the key file cannot be read') from None
    if b'PRIVATE KEY' not in data:
        raise AuthError('the key file is not a PEM private key')
    register_key(data)
    return data


def google_assertion(key: dict, token_url: str, now: float | None = None) -> str:
    iat = int(now if now is not None else time.time())
    header = {'alg': 'RS256', 'typ': 'JWT'}
    if key.get('private_key_id'):
        header['kid'] = key['private_key_id']
    claims = {'iss': key['client_email'], 'scope': GOOGLE_SCOPE, 'aud': token_url,
              'iat': iat, 'exp': iat + GOOGLE_LIFETIME}
    return make_jwt(header, claims, key['private_key'].encode())


def apple_token(key_id: str, issuer_id: str, key_pem: bytes, now: float | None = None) -> str:
    iat = int(now if now is not None else time.time())
    header = {'alg': 'ES256', 'kid': key_id, 'typ': 'JWT'}
    claims = {'iss': issuer_id, 'iat': iat, 'exp': iat + APPLE_LIFETIME, 'aud': APPLE_AUDIENCE}
    return make_jwt(header, claims, key_pem)


def exchange_google_token(key: dict, token_url: str, timeout: float = 20, now: float | None = None) -> str:
    """Signed assertion -> access token. A rejected exchange raises http.ServiceError."""
    assertion = google_assertion(key, token_url, now)
    resp = http.post_form(token_url, {'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                      'assertion': assertion}, timeout)
    if not resp.ok:
        err = http.service_error(resp)
        # a rejected credential is "not connected", whatever the status the token endpoint used
        raise http.ServiceError(403 if err.status in (400, 401) else err.status, err.message)
    try:
        token = resp.json()['access_token']
    except (ValueError, KeyError, TypeError):
        raise http.ServiceError(1, 'the token endpoint answered without an access token') from None
    http.add_secret(token)
    return token


# -- prerequisites shared by both providers (the `doctor` lines) ---------------------------------------------------

class Check:
    """One prerequisite: its name, whether it holds, and the single action that fixes it.

    `reads` is False for what only the console addresses need (a read does not wait for it)."""

    def __init__(self, name: str, ok: bool, action: str = '', reads: bool = True):
        self.name, self.ok, self.action, self.reads = name, ok, action, reads

    def as_dict(self) -> dict:
        return {'check': self.name, 'status': 'ok' if self.ok else 'missing', 'action': '' if self.ok else self.action}


def require_private(path: str) -> None:
    """Refuse a key file that is not private: it is never opened."""
    from . import settings
    ok, reason = settings.is_private(path)
    if not ok:
        raise AuthError(f'the key file is not private ({reason}); run chmod 600 on it')


def key_checks(setting: str, path: str, kind: str) -> list[Check]:
    """configured / exists / private / parsable for the key file named by SETTING (`play.key_file`), KIND `rsa` or `ec-p256`.

    The list stops at the first one that is missing: a check that depends on it would only repeat "fix it first"."""
    from . import settings
    if not path:
        return [Check(f'{setting} configured', False, f'set {setting} in the config piece stores to the key file path')]
    expanded = str(settings.expand(path))
    checks = [Check(f'{setting} configured', True)]
    if not os.path.isfile(expanded):
        return checks + [Check(f'{setting} exists', False, f'put the key file at {path} or fix {setting}')]
    checks.append(Check(f'{setting} exists', True))
    private, _reason = settings.is_private(expanded)
    if not private:
        mode = f'{os.stat(expanded).st_mode & 0o777:04o}'
        return checks + [Check(f'{setting} private', False, f'chmod 600 {path} (mode is {mode}, owner only is required); the key is not used until then')]
    checks.append(Check(f'{setting} private', True))
    try:
        if kind == 'rsa':
            pem = read_google_key(expanded)['private_key'].encode()
        else:
            pem = read_pem(expanded)
        found = key_type(pem) if openssl_bin() else kind
        if found != kind:
            raise AuthError(f'the key is {found}, this provider needs {kind}')
        checks.append(Check(f'{setting} parsable', True))
    except AuthError as err:
        what = 'the service-account JSON key file' if kind == 'rsa' else 'the .p8 private key'
        checks.append(Check(f'{setting} parsable', False, f'download {what} again ({err})'))
    return checks


def openssl_check() -> Check:
    return Check('openssl present', openssl_bin() is not None, 'install the openssl package (it signs the tokens)')
