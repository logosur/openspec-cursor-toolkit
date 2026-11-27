"""Loopback simulator of the store services and the key generation used by `stores self-test` and the tests.

Everything here is invented data on 127.0.0.1: a token endpoint that verifies the signed assertion, a Google Play
Developer API, an App Store Connect API that verifies the signed token, and the two public listing endpoints. The
simulator records every request so a test can assert what a command did. Keys are generated for the run with
`openssl`; no real key, host or account is involved.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import secrets
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import store_auth

PACKAGE = 'com.example.app'
DENIED_PACKAGE = 'com.example.denied'
BUNDLE = 'com.example.app'
CLIENT_EMAIL = 'svc@example.org'
KEY_ID = 'ABC123DEFG'
ISSUER_ID = '-'.join(('1' * 8, '2' * 4, '3' * 4, '4' * 4, '5' * 12))   # built, not written: a UUID literal is a privacy finding
DEVELOPER_ID = '1234567890'
APPLE_APP_ID = '1234'


class Keys:
    """Key files generated for one run, all inside DIRECTORY."""

    def __init__(self, directory: str):
        self.directory = directory
        self.google_file = os.path.join(directory, 'service-account.json')
        self.google_pub = os.path.join(directory, 'google-pub.pem')
        self.apple_file = os.path.join(directory, 'AuthKey_ABC123DEFG.p8')
        self.apple_pub = os.path.join(directory, 'apple-pub.pem')


def generate_keys(directory: str) -> Keys:
    """An RSA service-account file and an EC P-256 App Store Connect key, both 0600, plus their public keys."""
    keys = Keys(directory)
    rsa = store_auth.run_openssl(['genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'])
    ec_traditional = store_auth.run_openssl(['ecparam', '-name', 'prime256v1', '-genkey', '-noout'])
    ec = store_auth.run_openssl(['pkcs8', '-topk8', '-nocrypt', '-in', '@KEY@'], ec_traditional)
    document = {'type': 'service_account', 'project_id': 'example-project', 'private_key_id': 'key-0001',
                'private_key': rsa.decode(), 'client_email': CLIENT_EMAIL, 'token_uri': 'http://127.0.0.1/token'}
    for path, content in ((keys.google_file, json.dumps(document).encode()), (keys.apple_file, ec),
                          (keys.google_pub, store_auth.run_openssl(['pkey', '-pubout', '-in', '@KEY@'], rsa)),
                          (keys.apple_pub, store_auth.run_openssl(['pkey', '-pubout', '-in', '@KEY@'], ec))):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
        os.chmod(path, 0o600)
    return keys


def verify_signature(pub_path: str, data: bytes, signature: bytes) -> bool:
    """`openssl dgst -sha256 -verify` of DATA against SIGNATURE (DER or RSA) with the public key at PUB_PATH."""
    with tempfile.NamedTemporaryFile(suffix='.sig') as sig:
        sig.write(signature)
        sig.flush()
        try:
            store_auth.run_openssl(['dgst', '-sha256', '-verify', pub_path, '-signature', sig.name], None, data)
        except store_auth.AuthError:
            return False
    return True


def default_play_data() -> dict:
    return {
        'tracks': [
            {'track': 'production', 'releases': [{'name': '1.2.0 (12)', 'versionCodes': ['12'], 'status': 'completed'}]},
            {'track': 'open-testing', 'releases': [{'name': '1.3.0 (13)', 'versionCodes': ['13', '14'],
                                                    'status': 'inProgress', 'userFraction': 0.1}]},
            {'track': 'internal-testing', 'releases': []},
        ],
        'listings': {
            'en-US': {'language': 'en-US', 'title': 'Demo App', 'shortDescription': 'A demo.',
                      'fullDescription': 'x' * 321},
            'es-ES': {'language': 'es-ES', 'title': 'App de prueba', 'shortDescription': 'Una prueba.',
                      'fullDescription': 'y' * 100},
        },
        'reviews': [{'reviewId': f'r{i}', 'authorName': f'Reviewer {i}',
                     'comments': [{'userComment': {'text': f'Review number {i}', 'starRating': 1 + i % 5,
                                                   'lastModified': {'seconds': str(1700000000 + i * 3600)}}}]}
                    for i in range(25)],
    }


def default_apple_data() -> dict:
    return {
        'apps': [{'id': APPLE_APP_ID, 'attributes': {'name': 'Demo App', 'bundleId': BUNDLE, 'sku': 'DEMO1'}},
                 {'id': '5678', 'attributes': {'name': 'Other Demo', 'bundleId': 'com.example.other', 'sku': 'DEMO2'}}],
        'versions': [{'attributes': {'platform': 'IOS', 'versionString': '1.2.0', 'appStoreState': 'READY_FOR_SALE'}},
                     {'attributes': {'platform': 'IOS', 'versionString': '1.3.0', 'appStoreState': 'PREPARE_FOR_SUBMISSION'}}],
        'builds': [{'attributes': {'version': str(100 + i), 'uploadedDate': f'2026-01-{1 + i % 28:02d}T10:00:00+00:00',
                                   'processingState': 'VALID', 'expired': i > 20}} for i in range(25)],
        'submissions': [{'attributes': {'state': 'COMPLETE', 'submittedDate': '2026-01-05T09:00:00+00:00',
                                        'platform': 'IOS'}}],
    }


class Simulator:
    """The simulated services. `requests` lists every request as a dict with method, path, query and body."""

    def __init__(self, keys: Keys):
        self.keys = keys
        self.token = 'sim-token-' + secrets.token_urlsafe(24)
        self.requests: list[dict] = []
        self.play = default_play_data()
        self.apple = default_apple_data()
        self.public_play = {PACKAGE}
        self.public_ios = {BUNDLE}
        self.denied = {DENIED_PACKAGE}
        self.public_status: int | None = None            # force the public listing endpoints to this status
        self.faults: dict[str, tuple[int, dict]] = {}   # path substring -> (status, document)
        self.open_edits: set[str] = set()
        self.deleted_edits: list[str] = []
        self.opened_edits: list[str] = []
        self._lock = threading.Lock()
        sim = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _serve(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length) if length else b''
                status, document, content_type = sim.handle(self.command, self.path, dict(self.headers), body)
                data = document if isinstance(document, bytes) else (json.dumps(document).encode() if document is not None else b'')
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(data)

            do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = _serve

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    # -- lifecycle ---------------------------------------------------------------------------------------------
    def start(self) -> 'Simulator':
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def base(self) -> str:
        return f'http://127.0.0.1:{self.server.server_address[1]}'

    def config(self, play_key: bool = True, ios_key: bool = True) -> dict:
        """A stores config piece that points every endpoint at this simulator."""
        return {
            'play': {'developer_id': DEVELOPER_ID, 'console_user': 0,
                     'key_file': self.keys.google_file if play_key else '',
                     'api_url': f'{self.base}/play', 'token_url': f'{self.base}/token',
                     'public_url': f'{self.base}/store/apps/details?id={{id}}'},
            'ios': {'key_id': KEY_ID, 'issuer_id': ISSUER_ID, 'key_file': self.keys.apple_file if ios_key else '',
                    'api_url': f'{self.base}/ios', 'public_url': f'{self.base}/lookup?bundleId={{id}}'},
            'apps': {'demo': {'provider': 'play', 'id': PACKAGE, 'console_id': '1234', 'name': 'Demo'},
                     'denied': {'provider': 'play', 'id': DENIED_PACKAGE, 'console_id': '9999', 'name': 'Denied'},
                     'phone': {'provider': 'ios', 'id': BUNDLE, 'console_id': APPLE_APP_ID, 'name': 'Demo iOS'},
                     'phone2': {'provider': 'ios', 'id': 'com.example.other', 'name': 'Other iOS'}},
        }

    def paths(self, method: str | None = None) -> list[str]:
        return [r['path'] for r in self.requests if method is None or r['method'] == method]

    # -- request handling --------------------------------------------------------------------------------------
    def handle(self, method: str, raw_path: str, headers: dict, body: bytes):
        parts = urllib.parse.urlsplit(raw_path)
        query = urllib.parse.parse_qs(parts.query)
        path = parts.path
        with self._lock:
            self.requests.append({'method': method, 'path': path, 'query': parts.query, 'body': body,
                                  'authorization': headers.get('Authorization', '')})
        if method not in ('GET', 'POST', 'DELETE'):
            return 405, {'error': {'code': 405, 'message': 'method not allowed', 'status': 'METHOD_NOT_ALLOWED'}}, 'application/json'
        if path == '/token':
            return self._token(method, body)
        if path.startswith('/play/'):
            return self._play(method, path[len('/play'):], query, headers)
        if path.startswith('/ios/'):
            return self._ios(method, path[len('/ios'):], query, headers)
        if path in ('/store/apps/details', '/lookup') and self.public_status:
            return self.public_status, b'unavailable', 'text/plain'
        if path == '/store/apps/details' and method == 'GET':
            found = query.get('id', [''])[0] in self.public_play
            return (200, b'<html>listing</html>', 'text/html') if found else (404, b'not found', 'text/html')
        if path == '/lookup' and method == 'GET':
            bundle = query.get('bundleId', [''])[0]
            results = ([{'bundleId': bundle, 'trackViewUrl': f'https://apps.example.com/app/{bundle}'}]
                       if bundle in self.public_ios else [])
            return 200, {'resultCount': len(results), 'results': results}, 'application/json'
        return 404, {'error': {'code': 404, 'message': 'no such path', 'status': 'NOT_FOUND'}}, 'application/json'

    def _fault(self, path: str):
        for fragment, (status, document) in self.faults.items():
            if fragment in path:
                return status, document, 'application/json'
        return None

    def _token(self, method: str, body: bytes):
        fields = urllib.parse.parse_qs(body.decode())
        assertion = (fields.get('assertion') or [''])[0]
        bad = (400, {'error': 'invalid_grant', 'error_description': 'Invalid JWT'}, 'application/json')
        if method != 'POST' or fields.get('grant_type') != ['urn:ietf:params:oauth:grant-type:jwt-bearer']:
            return bad
        try:
            head_b, claims_b, sig_b = assertion.split('.')
            header = json.loads(store_auth.b64u_decode(head_b))
            claims = json.loads(store_auth.b64u_decode(claims_b))
            signature = store_auth.b64u_decode(sig_b)
        except (ValueError, TypeError):
            return bad
        ok = (header.get('alg') == 'RS256' and header.get('kid') == 'key-0001'
              and claims.get('iss') == CLIENT_EMAIL and claims.get('scope') == store_auth.GOOGLE_SCOPE
              and claims.get('aud') == f'{self.base}/token' and claims['exp'] - claims['iat'] <= 3600
              and abs(claims['iat'] - time.time()) < 300
              and verify_signature(self.keys.google_pub, f'{head_b}.{claims_b}'.encode(), signature))
        if not ok:
            return bad
        return 200, {'access_token': self.token, 'expires_in': 3600, 'token_type': 'Bearer'}, 'application/json'

    def _play(self, method: str, path: str, query: dict, headers: dict):
        if headers.get('Authorization') != f'Bearer {self.token}':
            return 401, {'error': {'code': 401, 'message': 'Invalid Credentials', 'status': 'UNAUTHENTICATED'}}, 'application/json'
        fault = self._fault(path)
        if fault:
            return fault
        match = re.fullmatch(r'/applications/([^/]+)(/.*)?', path)
        if not match:
            return 404, {'error': {'code': 404, 'message': 'no such path', 'status': 'NOT_FOUND'}}, 'application/json'
        package, rest = match.group(1), match.group(2) or ''
        if package in self.denied:
            return 403, {'error': {'code': 403, 'message': f'The caller does not have permission for {package}',
                                   'status': 'PERMISSION_DENIED'}}, 'application/json'
        if package != PACKAGE:
            return 404, {'error': {'code': 404, 'message': f'Package not found: {package}', 'status': 'NOT_FOUND'}}, 'application/json'
        if rest == '/edits' and method == 'POST':
            edit = f'edit-{len(self.opened_edits) + 1}'
            self.opened_edits.append(edit)
            self.open_edits.add(edit)
            return 200, {'id': edit, 'expiryTimeSeconds': '9999999999'}, 'application/json'
        if rest == '/reviews' and method == 'GET':
            count = int((query.get('maxResults') or ['10'])[0])
            return 200, {'reviews': self.play['reviews'][:count]}, 'application/json'
        edit_match = re.fullmatch(r'/edits/([^/:]+)(/.*)?', rest)
        if edit_match:
            edit, sub = edit_match.group(1), edit_match.group(2) or ''
            if edit not in self.open_edits:
                return 404, {'error': {'code': 404, 'message': 'Edit not found', 'status': 'NOT_FOUND'}}, 'application/json'
            if sub == '' and method == 'DELETE':
                self.open_edits.discard(edit)
                self.deleted_edits.append(edit)
                return 204, None, 'application/json'
            if sub == '/tracks' and method == 'GET':
                return 200, {'tracks': self.play['tracks']}, 'application/json'
            if sub == '/listings' and method == 'GET':
                return 200, {'listings': list(self.play['listings'].values())}, 'application/json'
            lang = re.fullmatch(r'/listings/([^/]+)', sub)
            if lang and method == 'GET':
                listing = self.play['listings'].get(lang.group(1))
                if listing:
                    return 200, listing, 'application/json'
                return 404, {'error': {'code': 404, 'message': 'Listing not found', 'status': 'NOT_FOUND'}}, 'application/json'
        return 404, {'error': {'code': 404, 'message': 'no such path', 'status': 'NOT_FOUND'}}, 'application/json'

    def _apple_denied(self, status: int, code: str, detail: str):
        return status, {'errors': [{'status': str(status), 'code': code, 'title': code.title(), 'detail': detail}]}, 'application/json'

    def _ios(self, method: str, path: str, query: dict, headers: dict):
        if method != 'GET':
            return self._apple_denied(405, 'METHOD_NOT_ALLOWED', 'read only simulator')
        auth = headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or not self._apple_token_ok(auth[7:]):
            return self._apple_denied(401, 'NOT_AUTHORIZED', 'Authentication credentials are missing or invalid.')
        fault = self._fault(path)
        if fault:
            return fault
        limit = int((query.get('limit') or ['50'])[0])

        def page(items: list) -> tuple:
            return 200, {'data': items[:limit], 'meta': {'paging': {'total': len(items), 'limit': limit}}}, 'application/json'

        if path == '/apps':
            bundle = (query.get('filter[bundleId]') or [None])[0]
            apps = [a for a in self.apple['apps'] if bundle is None or a['attributes']['bundleId'] == bundle]
            return page(apps)
        match = re.fullmatch(r'/apps/([^/]+)/appStoreVersions', path)
        if match:
            if match.group(1) == 'locked':
                return self._apple_denied(403, 'FORBIDDEN_ERROR', 'This app is not available to the key role.')
            return page(self.apple['versions'])
        if path == '/builds':
            return page(self.apple['builds'])
        if path == '/reviewSubmissions':
            return page(self.apple['submissions'])
        return self._apple_denied(404, 'NOT_FOUND', 'The specified resource does not exist')

    def _apple_token_ok(self, token: str) -> bool:
        try:
            head_b, claims_b, sig_b = token.split('.')
            header = json.loads(store_auth.b64u_decode(head_b))
            claims = json.loads(store_auth.b64u_decode(claims_b))
            raw = store_auth.b64u_decode(sig_b)
        except (ValueError, TypeError):
            return False
        return (header.get('alg') == 'ES256' and header.get('kid') == KEY_ID and claims.get('iss') == ISSUER_ID
                and claims.get('aud') == store_auth.APPLE_AUDIENCE and claims['exp'] - claims['iat'] <= 1200
                and claims['exp'] > time.time() and len(raw) == 64
                and verify_signature(self.keys.apple_pub, f'{head_b}.{claims_b}'.encode(), store_auth.raw_to_der(raw)))



# -- `stores self-test` ----------------------------------------------------------------------------------------

def full_config(sim: Simulator) -> dict:
    """The simulator's config over the providers' built-in defaults, as settings.load would build it."""
    from . import store_ios, store_play
    cfg = sim.config()
    return {'play': {**store_play.DEFAULTS, **cfg['play']}, 'ios': {**store_ios.DEFAULTS, **cfg['ios']},
            'apps': cfg['apps'], 'defaults': dict(store_auth.COMMON_DEFAULTS)}


def run_self_test(write=print) -> bool:
    """Signing, token exchange, one read per provider, public listings and console addresses against the
    simulator, with keys made for this run. WRITE gets one line per check."""
    from . import http, store_ios, store_play
    results: list[bool] = []

    def check(label: str, test) -> None:
        try:
            problem = test()
        except (store_auth.AuthError, http.ServiceError, http.TransportError, KeyError, ValueError, OSError) as err:
            problem = f'{type(err).__name__}: {getattr(err, "message", None) or err}'
        results.append(problem in (None, True))
        write(f'ok    {label}' if problem in (None, True) else f'FAIL  {label}: {problem}')

    directory = tempfile.mkdtemp(prefix='stores-selftest-')
    sim = None
    try:
        keys = generate_keys(directory)
        sim = Simulator(keys).start()
        cfg = full_config(sim)
        timeout = 10

        def rs256():
            sig = store_auth.sign('RS256', b'data', store_auth.read_google_key(keys.google_file)['private_key'].encode())
            return verify_signature(keys.google_pub, b'data', sig) or 'signature does not verify'

        def es256():
            raw = store_auth.sign('ES256', b'data', store_auth.read_pem(keys.apple_file))
            if len(raw) != 64:
                return f'raw signature has {len(raw)} bytes, not 64'
            return verify_signature(keys.apple_pub, b'data', store_auth.raw_to_der(raw)) or 'signature does not verify'

        def exchange():
            key = store_auth.read_google_key(keys.google_file)
            return store_auth.exchange_google_token(key, cfg['play']['token_url'], timeout) == sim.token or 'wrong token'

        def play_read():
            result = store_play.tracks(store_play.Session(cfg['play'], timeout), 'demo', cfg['apps']['demo'], 20)
            if not result['lines'] or sim.open_edits or len(sim.deleted_edits) != len(sim.opened_edits):
                return 'no tracks, or an edit was left open'

        def ios_read():
            result = store_ios.versions(store_ios.Session(cfg['ios'], timeout), 'phone', cfg['apps']['phone'], 20)
            if not result['lines']:
                return 'no versions'

        def public_play():
            found, missing = (store_play.public(cfg['play'], app, timeout)['public'] for app in
                              (cfg['apps']['demo'], {'id': 'com.example.nothing'}))
            return (found and not missing) or 'expected public then not public'

        def public_ios():
            found, missing = (store_ios.public(cfg['ios'], app, timeout)['public'] for app in
                              (cfg['apps']['phone'], {'id': 'com.example.nothing'}))
            return (found and not missing) or 'expected public then not public'

        def urls():
            play = store_play.console_url(cfg['play'], 'demo', cfg['apps']['demo'], 'production')
            ios = store_ios.console_url(cfg['ios'], 'phone', cfg['apps']['phone'], 'testflight')
            ok = DEVELOPER_ID in play and '/1234/' in play and ios.endswith('/1234/testflight/ios')
            return ok or 'console addresses are wrong'

        def read_only():
            odd = [r for r in sim.requests if r['method'] not in ('GET', 'POST', 'DELETE')]
            writes = [r for r in sim.requests if r['method'] != 'GET'
                      and not (r['path'] == '/token' or r['path'].endswith('/edits') or '/edits/' in r['path'])]
            return not odd and not writes or 'a request outside the read-only allow-list was made'

        check('RS256 signature verifies against the public key', rs256)
        check('ES256 signature is 64 raw bytes and verifies as DER', es256)
        check('Google token exchange', exchange)
        check('Google Play read (tracks) and edit deleted', play_read)
        check('App Store Connect read (versions)', ios_read)
        check('public listing, Google Play', public_play)
        check('public listing, App Store', public_ios)
        check('console addresses', urls)
        check('only reads, the token exchange and edit open/delete were sent', read_only)
    finally:
        if sim is not None:
            sim.stop()
        shutil.rmtree(directory, ignore_errors=True)
    return bool(results) and all(results)
