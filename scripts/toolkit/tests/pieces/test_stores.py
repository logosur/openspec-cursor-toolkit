"""Tests for global/scripts/stores and global/scripts/lib/access/store_*.py (read-only store access).

Run:  python3 -m unittest scripts.toolkit.tests.pieces.test_stores -v   (from the repository root)

Nothing here reaches a real service: a loopback simulator (store_selftest.Simulator) plays the token endpoint, the
two store APIs and the two public listings, and the key pairs are generated with `openssl` for each run. The command
is run as a subprocess in a temporary HOME with its own config directory; no real key file or config is read.
"""
import base64
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

LIB = str(REPO_ROOT / 'global/scripts/lib')
sys.path.insert(0, LIB)
from access import http, store_auth, store_selftest  # noqa: E402

SCRIPT = os.environ.get('STORES_SCRIPT') or str(REPO_ROOT / 'global/scripts/stores')
HAS_OPENSSL = shutil.which('openssl') is not None
PEM_MARK = b'-----%s PRIVATE KEY-----'    # filled at run time: a key header written out is a privacy finding


def b64u_json(segment: str) -> dict:
    return json.loads(store_auth.b64u_decode(segment))


def openssl_verify(pub: str, data: bytes, signature: bytes) -> bool:
    """Ask openssl itself, outside the code under test, whether SIGNATURE (DER or RSA) is valid for DATA."""
    with tempfile.NamedTemporaryFile() as sig:
        sig.write(signature)
        sig.flush()
        proc = subprocess.run(['openssl', 'dgst', '-sha256', '-verify', pub, '-signature', sig.name],
                              input=data, capture_output=True)
    return proc.returncode == 0


class KeyedCase(unittest.TestCase):
    """A class with generated keys and a simulator for the whole class."""
    keys_dir = None

    @classmethod
    def setUpClass(cls):
        if not HAS_OPENSSL:
            raise unittest.SkipTest('openssl is not installed')
        cls.keys_dir = tempfile.mkdtemp(prefix='stores-test-keys-')
        cls.keys = store_selftest.generate_keys(cls.keys_dir)

    @classmethod
    def tearDownClass(cls):
        if cls.keys_dir:
            shutil.rmtree(cls.keys_dir, ignore_errors=True)


class DerConversionTest(unittest.TestCase):
    """Task 5.1: the DER to raw conversion on its own, without openssl."""

    def test_short_integers_are_left_padded(self):
        der = bytes([0x30, 0x06, 0x02, 0x01, 0x01, 0x02, 0x01, 0x02])
        self.assertEqual(store_auth.der_to_raw(der), b'\0' * 31 + b'\x01' + b'\0' * 31 + b'\x02')

    def test_sign_padding_byte_is_removed(self):
        r = b'\x80' + b'\x11' * 31          # high bit set: DER prefixes a zero byte
        s = b'\x7f' + b'\x22' * 31
        der = bytes([0x30, 0x45, 0x02, 0x21, 0x00]) + r + bytes([0x02, 0x20]) + s
        self.assertEqual(store_auth.der_to_raw(der), r + s)

    def test_long_form_length_is_read(self):
        r, s = b'\xff' * 32, b'\xfe' * 32
        body = bytes([0x02, 0x21, 0x00]) + r + bytes([0x02, 0x21, 0x00]) + s
        der = bytes([0x30, 0x81, len(body)]) + body
        self.assertEqual(store_auth.der_to_raw(der), r + s)

    def test_roundtrip_and_zero(self):
        for raw in (b'\0' * 64, b'\xff' * 64, bytes(range(64)), b'\0' * 31 + b'\x01' + b'\x80' + b'\0' * 31):
            self.assertEqual(store_auth.der_to_raw(store_auth.raw_to_der(raw)), raw)

    def test_garbage_is_refused(self):
        for bad in (b'', b'\x30', b'\x31\x00', bytes([0x30, 0x03, 0x02, 0x01, 0x01]), b'\x30\x06\x02\x01\x01\x02\x01\x02\x00'):
            with self.assertRaises(store_auth.AuthError):
                store_auth.der_to_raw(bad)

    def test_base64url_has_no_padding(self):
        self.assertEqual(store_auth.b64u(b'\xfb\xff'), '-_8')
        self.assertEqual(store_auth.b64u(b'a'), 'YQ')
        self.assertEqual(store_auth.b64u_decode('YQ'), b'a')


class SigningTest(KeyedCase):
    """Task 5.1: both algorithms through openssl, verified against the matching public key."""

    def setUp(self):
        self.google = store_auth.read_google_key(self.keys.google_file)
        self.apple_pem = store_auth.read_pem(self.keys.apple_file)

    def test_rs256_signature_verifies(self):
        data = b'header.claims'
        sig = store_auth.sign('RS256', data, self.google['private_key'].encode())
        self.assertEqual(len(sig), 256)
        self.assertTrue(openssl_verify(self.keys.google_pub, data, sig))
        self.assertFalse(openssl_verify(self.keys.google_pub, data + b'x', sig))

    def test_es256_signature_is_64_raw_bytes_that_verify_as_der(self):
        for index in range(25):   # r and s vary in length and sign bit between runs
            data = f'header.claims.{index}'.encode()
            raw = store_auth.sign('ES256', data, self.apple_pem)
            self.assertEqual(len(raw), 64)
            self.assertTrue(openssl_verify(self.keys.apple_pub, data, store_auth.raw_to_der(raw)), index)
            self.assertFalse(openssl_verify(self.keys.apple_pub, data + b'x', store_auth.raw_to_der(raw)))

    def test_es256_token_signature_segment_decodes_to_64_bytes(self):
        token = store_auth.apple_token(store_selftest.KEY_ID, store_selftest.ISSUER_ID, self.apple_pem)
        head, claims, sig = token.split('.')
        self.assertNotIn('=', token)
        self.assertEqual(len(store_auth.b64u_decode(sig)), 64)
        self.assertTrue(openssl_verify(self.keys.apple_pub, f'{head}.{claims}'.encode(),
                                       store_auth.raw_to_der(store_auth.b64u_decode(sig))))

    def test_rs256_token_has_the_google_claims(self):
        token = store_auth.google_assertion(self.google, 'http://127.0.0.1:1/token', now=1000)
        head, claims, sig = token.split('.')
        self.assertEqual(b64u_json(head), {'alg': 'RS256', 'typ': 'JWT', 'kid': 'key-0001'})
        self.assertEqual(b64u_json(claims), {'iss': store_selftest.CLIENT_EMAIL, 'scope': store_auth.GOOGLE_SCOPE,
                                             'aud': 'http://127.0.0.1:1/token', 'iat': 1000, 'exp': 4600})
        self.assertTrue(openssl_verify(self.keys.google_pub, f'{head}.{claims}'.encode(), store_auth.b64u_decode(sig)))

    def test_apple_token_lifetime_is_at_most_15_minutes(self):
        token = store_auth.apple_token(store_selftest.KEY_ID, store_selftest.ISSUER_ID, self.apple_pem, now=5000)
        head, claims, _ = token.split('.')
        self.assertEqual(b64u_json(head), {'alg': 'ES256', 'kid': store_selftest.KEY_ID, 'typ': 'JWT'})
        doc = b64u_json(claims)
        self.assertLessEqual(doc['exp'] - doc['iat'], 900)
        self.assertEqual((doc['iss'], doc['aud'], doc['iat']), (store_selftest.ISSUER_ID, 'appstoreconnect-v1', 5000))

    def test_key_material_never_goes_in_the_argument_list(self):
        seen = []
        real = subprocess.run

        def spy(cmd, *a, **kw):
            seen.append(list(cmd))
            return real(cmd, *a, **kw)

        with mock.patch.object(subprocess, 'run', spy):
            store_auth.sign('ES256', b'x', self.apple_pem)
        self.assertEqual(len(seen), 1)
        text = self.apple_pem.decode()
        for arg in seen[0]:
            self.assertNotIn('PRIVATE KEY', arg)
            for line in text.splitlines()[1:-2]:
                self.assertNotIn(line, arg)
        self.assertTrue(any(a.startswith('/dev/fd/') for a in seen[0]))
        self.assertNotIn(self.keys.apple_file, seen[0])   # not even the path of a key file

    def test_key_types_are_told_apart(self):
        self.assertEqual(store_auth.key_type(self.apple_pem), 'ec-p256')
        self.assertEqual(store_auth.key_type(self.google['private_key'].encode()), 'rsa')

    def test_openssl_absent_is_a_plain_error(self):
        with mock.patch.object(store_auth.shutil, 'which', return_value=None):
            with self.assertRaises(store_auth.AuthError) as ctx:
                store_auth.sign('ES256', b'x', self.apple_pem)
        self.assertIn('openssl', str(ctx.exception))

    def test_broken_key_is_a_one_line_error_without_key_text(self):
        with self.assertRaises(store_auth.AuthError) as ctx:
            store_auth.sign('RS256', b'x', PEM_MARK % b'BEGIN' + b'\nAAAA\n' + PEM_MARK % b'END' + b'\n')
        self.assertNotIn('\n', str(ctx.exception))
        self.assertNotIn('AAAA', str(ctx.exception))

    def test_key_files_are_checked_for_their_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in (('a.json', '{not json'), ('b.json', '[]'), ('c.json', '{"client_email": "x"}'),
                                  ('d.json', '{"client_email": "x", "private_key": "nope"}')):
                path = os.path.join(tmp, name)
                with open(path, 'w') as handle:
                    handle.write(content)
                with self.assertRaises(store_auth.AuthError):
                    store_auth.read_google_key(path)
            with self.assertRaises(store_auth.AuthError):
                store_auth.read_pem(os.path.join(tmp, 'a.json'))
            with self.assertRaises(store_auth.AuthError):
                store_auth.read_pem(os.path.join(tmp, 'missing.p8'))


class TokenExchangeTest(KeyedCase):
    """Task 5.1: the Google token exchange against the simulator."""

    def setUp(self):
        self.sim = store_selftest.Simulator(self.keys).start()
        self.addCleanup(self.sim.stop)
        self.google = store_auth.read_google_key(self.keys.google_file)

    def test_exchange_returns_the_token_and_posts_a_form(self):
        token = store_auth.exchange_google_token(self.google, f'{self.sim.base}/token')
        self.assertEqual(token, self.sim.token)
        self.assertEqual([(r['method'], r['path']) for r in self.sim.requests], [('POST', '/token')])

    def test_rejected_assertion_is_a_not_connected_error(self):
        bad = dict(self.google, private_key_id='other-key')
        with self.assertRaises(http.ServiceError) as ctx:
            store_auth.exchange_google_token(bad, f'{self.sim.base}/token')
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertNotIn(self.sim.token, ctx.exception.message)

    def test_assertion_issued_long_ago_is_rejected(self):
        with self.assertRaises(http.ServiceError):
            store_auth.exchange_google_token(self.google, f'{self.sim.base}/token', now=1)   # long expired

    def test_unreachable_endpoint_is_a_transport_error(self):
        self.sim.stop()
        with self.assertRaises(http.TransportError):
            store_auth.exchange_google_token(self.google, f'{self.sim.base}/token', timeout=2)

    def test_only_get_post_and_delete_exist(self):
        for method in ('PUT', 'PATCH'):
            with self.assertRaises(ValueError):
                http.request(method, f'{self.sim.base}/x')
        self.assertEqual(self.sim.requests, [])


class RedirectingServers:
    """Mixin: `origin` answers every GET with a redirect to `target`, which records what it receives."""

    def start_redirecting_servers(self):
        import http.server as server
        import threading
        self.seen = []
        seen = self.seen

        class Target(server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append((self.server.server_port, self.headers.get('Authorization')))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        class Origin(Target):
            def do_GET(self):
                seen.append((self.server.server_port, self.headers.get('Authorization')))
                self.send_response(302)
                self.send_header('Location', f'http://localhost:{self.server.target_port}/x')
                self.end_headers()

        self.target = server.HTTPServer(('127.0.0.1', 0), Target)
        self.origin = server.HTTPServer(('127.0.0.1', 0), Origin)
        self.origin.target_port = self.target.server_port
        for httpd in (self.target, self.origin):
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.addCleanup(httpd.server_close)
            self.addCleanup(httpd.shutdown)


class RedirectTest(RedirectingServers, unittest.TestCase):
    """A request that carries credentials never follows a redirect: urllib would forward the Authorization header
    to the new host, and a store token must reach only the configured service."""

    def setUp(self):
        self.start_redirecting_servers()

    def test_a_redirect_is_not_followed_when_credentials_are_sent(self):
        resp = http.get(f'http://127.0.0.1:{self.origin.server_port}/y', {'Authorization': 'Bearer ' + 'secret-token-value'})
        self.assertEqual(resp.status, 302)
        self.assertFalse(resp.ok)
        self.assertEqual(self.seen, [(self.origin.server_port, 'Bearer ' + 'secret-token-value')], 'the target never saw the token')
        self.assertEqual(http.service_error(resp).exit_code, 1)

    def test_a_public_page_without_credentials_still_follows_a_redirect(self):
        resp = http.get(f'http://127.0.0.1:{self.origin.server_port}/y')
        self.assertEqual(resp.status, 200)
        self.assertEqual([port for port, _ in self.seen], [self.origin.server_port, self.target.server_port])


# -- command level: the entry script against the simulator --------------------------------------------------------

def load_entry():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader('stores_script', SCRIPT)
    spec = importlib.util.spec_from_loader('stores_script', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CliCase(KeyedCase):
    """Runs `stores` as a subprocess in a temporary HOME whose config piece is written by the test."""

    def setUp(self):
        self.sim = store_selftest.Simulator(self.keys).start()
        self.addCleanup(self.sim.stop)
        self.home = tempfile.mkdtemp(prefix='stores-test-home-')
        self.addCleanup(shutil.rmtree, self.home, True)
        self.config_dir = os.path.join(self.home, 'config')
        os.makedirs(self.config_dir)
        self.outputs = []      # every (stdout, stderr) of this test, for the leak checks

    def write_config(self, document=None, raw=None):
        with open(os.path.join(self.config_dir, 'stores.json'), 'w') as handle:
            handle.write(raw if raw is not None else json.dumps(document if document is not None else self.sim.config()))

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
        env.update(HOME=self.home, CLAUDE_TOOLKIT_CONFIG_DIR=self.config_dir, XDG_CACHE_HOME=os.path.join(self.home, 'cache'),
                   PYTHONDONTWRITEBYTECODE='1')
        env.update(extra)
        return env

    def run_stores(self, *args, env=None):
        proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env or self.env(),
                              cwd=self.home, timeout=60)
        self.outputs.append((args, proc.stdout, proc.stderr))
        self.assertNotIn('Traceback', proc.stderr, f'{args}: {proc.stderr}')
        return proc

    def config_with(self, mutate):
        document = self.sim.config()
        mutate(document)
        self.write_config(document)


class ConfigAndAppsTest(CliCase):
    """Requirement: providers and apps are named in configuration."""

    def test_apps_listed_without_credentials(self):
        self.write_config(self.sim.config(play_key=False, ios_key=False))
        proc = self.run_stores('apps')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f'demo play {store_selftest.PACKAGE}', proc.stdout)
        self.assertIn('phone ios com.example.app', proc.stdout)
        self.assertEqual(self.sim.requests, [])
        document = json.loads(self.run_stores('apps', '--json').stdout)
        self.assertEqual({a['alias'] for a in document['apps']}, {'demo', 'denied', 'phone', 'phone2'})

    def test_nothing_configured_with_the_shipped_defaults(self):
        shutil.copy(REPO_ROOT / 'global/config/stores.json', os.path.join(self.config_dir, 'stores.json'))
        proc = self.run_stores('apps')
        self.assertEqual(proc.returncode, 0)
        self.assertIn('no app is configured', proc.stdout)
        self.assertIn('stores.json', proc.stdout)

    def test_no_config_file_at_all(self):
        proc = self.run_stores('apps')
        self.assertEqual((proc.returncode, proc.stderr), (0, ''))
        self.assertIn('no app is configured', proc.stdout)

    def test_unreadable_configuration_is_named_and_treated_as_empty(self):
        self.write_config(raw='{not json')
        proc = self.run_stores('apps')
        self.assertEqual(proc.returncode, 0)
        self.assertIn('stores.json', proc.stderr)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
        self.assertIn('no app is configured', proc.stdout)

    def test_shipped_config_is_minimal_and_holds_no_secret_or_app(self):
        shipped = json.loads((REPO_ROOT / 'global/config/stores.json').read_text())
        self.assertEqual(shipped.get('apps'), {})
        self.assertTrue(all(not v for section in ('play', 'ios') for v in shipped.get(section, {}).values()))

    def test_partial_provider_object_keeps_the_built_in_defaults(self):
        self.write_config({'play': {'developer_id': store_selftest.DEVELOPER_ID, 'console_user': 2},
                           'apps': {'demo': {'provider': 'play', 'id': 'com.example.app', 'console_id': '1234'}}})
        with mock.patch.dict(os.environ, self.env()):
            entry = load_entry()
            cfg, problem = entry.load_config()
        self.assertIsNone(problem)
        self.assertEqual(cfg['play']['api_url'], 'https://androidpublisher.googleapis.com/androidpublisher/v3')
        self.assertEqual(cfg['play']['token_url'], 'https://oauth2.googleapis.com/token')
        self.assertEqual(cfg['play']['pages']['production'], 'tracks/production')
        self.assertEqual(cfg['ios']['api_url'], 'https://api.appstoreconnect.apple.com/v1')
        proc = self.run_stores('url', 'play', 'demo', 'production')
        self.assertEqual(proc.stdout.strip(), 'https://play.google.com/console/u/2/developers/1234567890/app/1234/tracks/production')

    def test_apps_remote_lists_the_team_through_the_service(self):
        self.write_config()
        proc = self.run_stores('apps', '--remote')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('apps of the team', proc.stdout)
        self.assertIn('1234 com.example.app Demo App', proc.stdout)
        self.assertEqual({r['method'] for r in self.sim.requests}, {'GET'})


class UrlTest(CliCase):
    """Requirement: console addresses are built, not remembered."""

    def setUp(self):
        super().setUp()
        self.write_config(self.sim.config(play_key=False, ios_key=False))

    def test_app_page_contains_user_developer_and_console_id(self):
        self.config_with(lambda c: c['play'].update(console_user=3))
        proc = self.run_stores('url', 'play', 'demo', 'publishing')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), 'https://play.google.com/console/u/3/developers/1234567890/app/1234/publishing')

    def test_default_page_is_the_dashboard_and_account_address_needs_no_app(self):
        self.assertTrue(self.run_stores('url', 'play', 'demo').stdout.strip().endswith('/app/1234/app-dashboard'))
        self.assertEqual(self.run_stores('url', 'play').stdout.strip(),
                         'https://play.google.com/console/u/0/developers/1234567890')

    def test_unknown_page_is_appended_unchanged(self):
        self.assertTrue(self.run_stores('url', 'play', 'demo', 'releases/overview').stdout.strip().endswith('/app/1234/releases/overview'))

    def test_ios_address(self):
        self.assertEqual(self.run_stores('url', 'ios', 'phone', 'testflight').stdout.strip(),
                         'https://appstoreconnect.apple.com/apps/1234/testflight/ios')
        self.assertEqual(self.run_stores('url', 'ios').stdout.strip(), 'https://appstoreconnect.apple.com/apps')

    def test_missing_developer_id_names_the_setting(self):
        self.config_with(lambda c: c['play'].update(developer_id=''))
        proc = self.run_stores('url', 'play', 'demo')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('play.developer_id', proc.stderr)

    def test_missing_console_id_names_the_setting(self):
        proc = self.run_stores('url', 'ios', 'phone2')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('apps.phone2.console_id', proc.stderr)

    def test_unknown_app_and_wrong_provider_are_usage_errors(self):
        for args in (('url', 'play', 'nope'), ('url', 'play', 'phone'), ('url', 'amazon')):
            self.assertEqual(self.run_stores(*args).returncode, 2, args)
        self.assertEqual(self.sim.requests, [])


class DoctorTest(CliCase):
    """Requirement: doctor names exactly what is missing."""

    def test_everything_in_place_is_ok_and_sends_nothing(self):
        self.write_config()
        proc = self.run_stores('doctor')
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertNotIn('missing', proc.stdout)
        self.assertIn('play ok play.key_file private', proc.stdout)
        self.assertIn('ios ok ios.key_file parsable', proc.stdout)
        self.assertEqual(self.sim.requests, [])

    def test_no_key_file_names_the_setting_and_sends_nothing_even_live(self):
        self.write_config(self.sim.config(play_key=False))
        proc = self.run_stores('doctor', 'play', '--live')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('missing play.key_file configured -> set play.key_file', proc.stdout)
        self.assertNotIn('play.key_file exists', proc.stdout)       # a check that depends on a missing one is not printed
        self.assertNotIn('play.key_file parsable', proc.stdout)
        self.assertEqual(self.sim.requests, [])

    def test_key_file_that_does_not_exist(self):
        self.config_with(lambda c: c['play'].update(key_file=os.path.join(self.home, 'absent.json')))
        proc = self.run_stores('doctor', 'play')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('missing play.key_file exists', proc.stdout)
        self.assertIn('ok play.key_file configured', proc.stdout)

    def test_key_readable_by_others_is_missing_and_never_used(self):
        loose = os.path.join(self.home, 'loose.json')
        shutil.copy(self.keys.google_file, loose)
        os.chmod(loose, 0o644)
        self.config_with(lambda c: c['play'].update(key_file=loose))
        proc = self.run_stores('doctor', 'play', '--live')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('missing play.key_file private -> chmod 600', proc.stdout)
        self.assertIn('0644', proc.stdout)
        self.assertNotIn('parsable', proc.stdout)      # nothing after the first missing key check
        self.assertEqual(self.sim.requests, [])
        read = self.run_stores('tracks', 'demo')
        self.assertEqual(read.returncode, 3)
        self.assertIn('stores doctor play', read.stderr)
        self.assertEqual(self.sim.requests, [])

    def test_unparsable_and_wrong_kind_keys(self):
        junk = os.path.join(self.home, 'junk.json')
        with open(junk, 'w') as handle:
            handle.write('{"client_email": "x"}')
        os.chmod(junk, 0o600)
        self.config_with(lambda c: (c['play'].update(key_file=junk), c['ios'].update(key_file=self.keys.google_file)))
        proc = self.run_stores('doctor')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('missing play.key_file parsable', proc.stdout)
        self.assertIn('missing ios.key_file parsable', proc.stdout)

    def test_openssl_absent_is_missing(self):
        self.write_config()
        empty = os.path.join(self.home, 'empty-bin')
        os.makedirs(empty)
        proc = self.run_stores('doctor', 'ios', env=self.env(PATH=empty))
        self.assertEqual(proc.returncode, 3)
        self.assertIn('missing openssl present -> install the openssl package', proc.stdout)

    def test_live_names_the_grant_when_access_is_refused(self):
        self.write_config()
        proc = self.run_stores('doctor', 'play', '--live')
        self.assertEqual(proc.returncode, 3, proc.stdout)
        self.assertIn('ok token exchange accepted', proc.stdout)
        self.assertIn(f'ok access to {store_selftest.PACKAGE} (demo)', proc.stdout)
        self.assertIn(f'missing access to {store_selftest.DENIED_PACKAGE} (denied)', proc.stdout)
        self.assertIn('users and permissions', proc.stdout)
        self.assertEqual({r['method'] for r in self.sim.requests}, {'POST', 'DELETE'})

    def test_live_ios_proves_the_key_and_each_app(self):
        self.write_config()
        proc = self.run_stores('doctor', 'ios', '--live')
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn('ok token accepted by the service', proc.stdout)
        self.assertIn('access to com.example.other (phone2)', proc.stdout)

    def test_missing_ids_are_reported_in_order_and_json_works(self):
        self.config_with(lambda c: (c['ios'].update(key_id='', issuer_id=''), c['play'].update(developer_id='')))
        proc = self.run_stores('doctor', '--json')
        self.assertEqual(proc.returncode, 3)
        document = json.loads(proc.stdout)
        self.assertFalse(document['ok'])
        missing = [(c['provider'], c['check']) for c in document['checks'] if c['status'] == 'missing']
        self.assertEqual(missing, [('play', 'play.developer_id configured'), ('ios', 'ios.key_id configured'),
                                   ('ios', 'ios.issuer_id configured')])
        self.assertTrue(all(c['action'] for c in document['checks'] if c['status'] == 'missing'))


class GooglePlayReadsTest(CliCase):
    def setUp(self):
        super().setUp()
        self.write_config()

    def test_tracks(self):
        proc = self.run_stores('tracks', 'demo')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('production 1.2.0 (12) completed codes 12', proc.stdout)
        self.assertIn('open-testing 1.3.0 (13) inProgress codes 13,14 rollout 10%', proc.stdout)
        self.assertIn('internal-testing (no release)', proc.stdout)
        document = json.loads(self.run_stores('tracks', 'demo', '--json').stdout)
        self.assertEqual(document['tracks'][0]['track'], 'production')

    def test_tracks_open_and_delete_an_edit_and_never_commit(self):
        self.run_stores('tracks', 'demo')
        self.assertEqual([(r['method'], r['path'].split('/')[-1]) for r in self.sim.requests],
                         [('POST', 'token'), ('POST', 'edits'), ('GET', 'tracks'), ('DELETE', 'edit-1')])
        self.assertEqual(self.sim.open_edits, set())

    def test_edit_is_deleted_when_the_read_fails_midway(self):
        self.sim.faults['/tracks'] = (500, {'error': {'code': 500, 'message': 'backend exploded', 'status': 'INTERNAL'}})
        proc = self.run_stores('tracks', 'demo')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('HTTP 500', proc.stderr)
        self.assertIn('backend exploded', proc.stderr)
        self.assertEqual(self.sim.opened_edits, ['edit-1'])
        self.assertEqual(self.sim.deleted_edits, ['edit-1'])

    def test_reviews_state_the_one_week_window_and_obey_the_limit(self):
        proc = self.run_stores('reviews', 'demo')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('only the last week of reviews', proc.stdout)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1 + 20 + 1)
        self.assertEqual(lines[-1], '20 of 25 shown')
        self.assertRegex(lines[1], r'^\d{4}-\d\d-\d\d \d\d:\d\d 1/5 Reviewer 0: Review number 0$')
        short = self.run_stores('reviews', 'demo', '--limit', '2')
        self.assertEqual(short.stdout.strip().splitlines()[-1], '2 of 25 shown')
        document = json.loads(self.run_stores('reviews', 'demo', '--limit', '2', '--json').stdout)
        self.assertEqual(len(document['reviews']), 2)
        self.assertIn('last week', document['note'])

    def test_listing_for_a_language(self):
        proc = self.run_stores('listing', 'demo', '--lang', 'en-US')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('en-US title: Demo App short: A demo. full: 321 characters', proc.stdout)
        self.assertNotIn('es-ES', proc.stdout)
        self.assertNotIn('xxxx', proc.stdout)

    def test_listing_without_a_language_lists_all_and_unknown_language_is_not_found(self):
        proc = self.run_stores('listing', 'demo')
        self.assertIn('es-ES title: App de prueba', proc.stdout)
        self.assertIn('en-US', proc.stdout)
        missing = self.run_stores('listing', 'demo', '--lang', 'fr-FR')
        self.assertEqual(missing.returncode, 4)
        self.assertEqual(self.sim.open_edits, set())

    def test_service_error_codes(self):
        denied = self.run_stores('tracks', 'denied')
        self.assertEqual(denied.returncode, 3)
        self.assertIn('HTTP 403 PERMISSION_DENIED', denied.stderr)
        self.assertEqual(len(denied.stderr.strip().splitlines()), 1)
        self.config_with(lambda c: c['apps'].update(ghost={'provider': 'play', 'id': 'com.example.ghost'}))
        self.assertEqual(self.run_stores('reviews', 'ghost').returncode, 4)

    def test_a_read_of_the_other_provider_names_the_ones_that_exist(self):
        proc = self.run_stores('versions', 'demo')
        self.assertEqual(proc.returncode, 2)
        self.assertIn('tracks, reviews, listing', proc.stderr)
        self.assertEqual(self.sim.requests, [])

    def test_unknown_app_is_a_usage_error(self):
        proc = self.run_stores('tracks', 'nope')
        self.assertEqual(proc.returncode, 2)
        self.assertIn('demo', proc.stderr)


class AppStoreReadsTest(CliCase):
    def setUp(self):
        super().setUp()
        self.write_config()

    def test_versions(self):
        proc = self.run_stores('versions', 'phone')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('IOS 1.2.0 READY_FOR_SALE', proc.stdout)
        self.assertIn('IOS 1.3.0 PREPARE_FOR_SUBMISSION', proc.stdout)

    def test_builds_with_limit_and_total(self):
        proc = self.run_stores('builds', 'phone')
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1 + 20 + 1)
        self.assertEqual(lines[-1], '20 of 25 shown')
        self.assertIn('100 2026-01-01T10:00:00+00:00 VALID expired no', lines[1])
        self.assertEqual(self.run_stores('builds', 'phone', '--limit', '3').stdout.strip().splitlines()[-1], '3 of 25 shown')
        self.assertIn('expired yes', self.run_stores('builds', 'phone', '--limit', '25').stdout)
        document = json.loads(self.run_stores('builds', 'phone', '--json').stdout)
        self.assertEqual(document['total'], 25)
        build_request = [r for r in self.sim.requests if r['path'] == '/ios/builds'][0]
        self.assertIn('filter%5Bapp%5D=1234', build_request['query'])
        self.assertIn('sort=-uploadedDate', build_request['query'])

    def test_review_submissions(self):
        proc = self.run_stores('review', 'phone')
        self.assertIn('2026-01-05T09:00:00+00:00 IOS COMPLETE', proc.stdout)

    def test_app_id_is_resolved_from_the_bundle_id_without_a_console_id(self):
        proc = self.run_stores('versions', 'phone2')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([r['path'] for r in self.sim.requests], ['/ios/apps', '/ios/apps/5678/appStoreVersions'])

    def test_bundle_id_that_is_not_in_the_team_is_not_found(self):
        self.config_with(lambda c: c['apps'].update(lost={'provider': 'ios', 'id': 'com.example.lost'}))
        self.assertEqual(self.run_stores('versions', 'lost').returncode, 4)

    def test_token_is_signed_elliptic_curve_and_lives_at_most_15_minutes(self):
        self.run_stores('versions', 'phone')
        bearer = [r['authorization'] for r in self.sim.requests][0].split(' ', 1)[1]
        head, claims, sig = bearer.split('.')
        self.assertEqual(len(store_auth.b64u_decode(sig)), 64)
        self.assertEqual(b64u_json(head)['alg'], 'ES256')
        document = b64u_json(claims)
        self.assertLessEqual(document['exp'] - document['iat'], 900)

    def test_service_error_is_one_plain_line(self):
        self.sim.faults['/builds'] = (403, {'errors': [{'status': '403', 'code': 'FORBIDDEN', 'title': 'Forbidden',
                                                        'detail': 'The key role cannot read builds.'}]})
        proc = self.run_stores('builds', 'phone')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('HTTP 403 FORBIDDEN: The key role cannot read builds.', proc.stderr)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1)

    def test_a_google_read_on_an_ios_app_is_a_usage_error(self):
        proc = self.run_stores('tracks', 'phone')
        self.assertEqual(proc.returncode, 2)
        self.assertIn('versions, builds, review', proc.stderr)

    def test_not_connected_points_to_doctor(self):
        self.write_config(self.sim.config(ios_key=False))
        proc = self.run_stores('versions', 'phone')
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
        self.assertIn('stores doctor ios', proc.stderr)
        self.assertEqual(self.sim.requests, [])


class PublicListingTest(CliCase):
    """Task 5.4: the public listing needs no key."""

    def setUp(self):
        super().setUp()
        document = self.sim.config(play_key=False, ios_key=False)
        document['apps'].update(gone={'provider': 'play', 'id': 'com.example.gone'},
                                gone_ios={'provider': 'ios', 'id': 'com.example.gone'})
        self.write_config(document)

    def test_published_play_app(self):
        proc = self.run_stores('public', 'demo')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), f'public {self.sim.base}/store/apps/details?id=com.example.app')
        self.assertEqual([r['authorization'] for r in self.sim.requests], [''])

    def test_play_404_is_not_public(self):
        proc = self.run_stores('public', 'gone')
        self.assertEqual(proc.returncode, 4)
        self.assertTrue(proc.stdout.startswith('not public'))

    def test_app_store_found_and_empty_lookup(self):
        found = self.run_stores('public', 'phone')
        self.assertEqual(found.returncode, 0)
        self.assertEqual(found.stdout.strip(), 'public https://apps.example.com/app/com.example.app')
        empty = self.run_stores('public', 'gone_ios')
        self.assertEqual(empty.returncode, 4)
        self.assertTrue(empty.stdout.startswith('not public'))

    def test_json(self):
        document = json.loads(self.run_stores('public', 'gone', '--json').stdout)
        self.assertEqual((document['public'], document['provider']), (False, 'play'))

    def test_unexpected_status_is_an_error_line(self):
        self.sim.public_status = 503
        for alias in ('demo', 'phone'):
            proc = self.run_stores('public', alias)
            self.assertEqual(proc.returncode, 1, alias)
            self.assertIn('HTTP 503', proc.stderr)
            self.assertEqual(proc.stdout, '')

    def test_service_unreachable_is_an_error_line(self):
        self.sim.stop()
        proc = self.run_stores('public', 'demo')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('cannot reach 127.0.0.1', proc.stderr)


class ReadOnlyAndSecretsTest(CliCase):
    """Requirements: nothing in a store is changed; keys and tokens never reach the output."""

    def exercise_everything(self):
        self.write_config()
        self.config_with(lambda c: c['apps'].update(ghost={'provider': 'play', 'id': 'com.example.ghost'},
                                                    lost={'provider': 'ios', 'id': 'com.example.lost'}))
        commands = [('apps',), ('apps', '--remote'), ('doctor',), ('doctor', '--live'), ('doctor', 'play', '--live'),
                    ('url', 'play', 'demo', 'production'), ('url', 'ios', 'phone'), ('public', 'demo'),
                    ('public', 'phone'), ('self-test',)]
        for read in (('tracks', 'demo'), ('reviews', 'demo'), ('listing', 'demo', '--lang', 'en-US'), ('listing', 'demo'),
                     ('versions', 'phone'), ('builds', 'phone'), ('review', 'phone'), ('versions', 'phone2'),
                     ('tracks', 'denied'), ('reviews', 'ghost'), ('versions', 'lost'), ('tracks', 'phone')):
            commands += [read, read + ('--json',)]
        commands += [('doctor', '--json'), ('apps', '--json')]
        self.sim.faults['/tracks'] = (500, {'error': {'code': 500, 'message': 'boom', 'status': 'INTERNAL'}})
        commands.append(('tracks', 'demo'))
        return commands

    def test_allow_list_edit_cleanup_and_no_secret_in_any_output(self):
        for args in self.exercise_everything():
            self.run_stores(*args)
        # -- requests: only reads, the token exchange, and opening and deleting an edit
        self.assertGreater(len(self.sim.requests), 40)
        self.assertLessEqual({r['method'] for r in self.sim.requests}, {'GET', 'POST', 'DELETE'})
        for request in self.sim.requests:
            path = request['path']
            self.assertNotIn(':', path, 'no commit, validate or other custom method')
            if request['method'] == 'POST':
                self.assertRegex(path, r'^/(token|play/applications/[^/]+/edits)$')
            if request['method'] == 'DELETE':
                self.assertRegex(path, r'^/play/applications/[^/]+/edits/edit-\d+$')
            if path.startswith('/ios'):
                self.assertEqual(request['method'], 'GET')
        self.assertEqual(sorted(self.sim.opened_edits), sorted(self.sim.deleted_edits))
        self.assertEqual(self.sim.open_edits, set())
        # -- secrets: the simulator's token, every signed token and assertion, every line of both key files
        secrets_seen = [self.sim.token]
        for request in self.sim.requests:
            if request['authorization'].startswith('Bearer ') and request['authorization'] != f'Bearer {self.sim.token}':
                secrets_seen.append(request['authorization'].split(' ', 1)[1])
            if request['path'] == '/token':
                secrets_seen.append(request['body'].decode().split('assertion=')[1])
        for path in (self.keys.google_file, self.keys.apple_file):
            with open(path) as handle:
                text = handle.read()
            if path.endswith('.json'):
                text = json.loads(text)['private_key']
            secrets_seen += [line.strip() for line in text.splitlines() if len(line.strip()) > 8]
        self.assertGreater(len(secrets_seen), 10)
        self.assertGreater(len(self.outputs), 30)
        for args, out, err in self.outputs:
            for secret in secrets_seen:
                self.assertNotIn(secret, out, args)
                self.assertNotIn(secret, err, args)
            if '--json' not in args and args[0] not in ('url', 'self-test'):
                self.assertTrue(all(len(line) <= 160 for line in out.splitlines()), args)

    def test_text_lines_are_bounded_to_160_characters(self):
        self.write_config()
        self.sim.play['reviews'][0]['comments'][0]['userComment']['text'] = 'long ' * 100
        proc = self.run_stores('reviews', 'demo')
        self.assertTrue(all(len(line) <= 160 for line in proc.stdout.splitlines()))
        self.assertTrue(any(line.endswith('…') for line in proc.stdout.splitlines()))

    def test_there_is_no_subcommand_that_prints_or_lends_a_token_or_writes(self):
        self.write_config()
        for word in ('token', 'exec', 'upload', 'release', 'rollout', 'submit', 'reply', 'commit', 'publish'):
            proc = self.run_stores(word)
            self.assertEqual(proc.returncode, 2, word)
        self.assertEqual(self.sim.requests, [])


class RedirectCommandTest(RedirectingServers, CliCase):
    """The same, through the command: one error line, exit 1, and the other host never sees the token."""

    def test_a_read_whose_service_redirects_is_one_error_line_and_the_token_goes_nowhere_else(self):
        self.start_redirecting_servers()
        self.config_with(lambda c: c['ios'].update(api_url=f'http://127.0.0.1:{self.origin.server_port}/v1'))
        proc = self.run_stores('versions', 'phone')
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1, proc.stderr)
        self.assertIn('HTTP 302', proc.stderr)
        self.assertEqual([port for port, _ in self.seen], [self.origin.server_port], 'the target host was never contacted')


class ContractTest(CliCase):
    """The probes of global/contracts/stores.yaml, run against the script with the shipped defaults and with a corrupt config."""

    def test_every_probe_passes(self):
        import yaml
        contract = yaml.safe_load((REPO_ROOT / 'global/contracts/stores.yaml').read_text())
        self.assertEqual((contract['piece'], contract['dest'], contract['kind']), ('stores', 'scripts/stores', 'cli'))
        self.write_config(raw=(REPO_ROOT / 'global/config/stores.json').read_text())
        corrupt = os.path.join(self.home, 'corrupt')
        os.makedirs(corrupt)
        with open(os.path.join(corrupt, 'stores.json'), 'w') as handle:
            handle.write('{not json')
        for probe in contract['probes']:
            env = self.env(CLAUDE_TOOLKIT_CONFIG_DIR=corrupt) if probe.get('corrupt_config') else self.env()
            proc = subprocess.run([sys.executable, SCRIPT, *map(str, probe['args'])], capture_output=True, text=True,
                                  env=env, cwd=self.home, timeout=probe.get('timeout', 60))
            self.assertIn(proc.returncode, probe.get('exit', [0]), (probe['name'], proc.stderr))
            if probe.get('stdout') == 'empty':
                self.assertEqual(proc.stdout, '', probe['name'])
            if probe.get('contains'):
                self.assertIn(probe['contains'], proc.stdout, probe['name'])
            self.assertNotIn('Traceback', proc.stderr, probe['name'])
        self.assertGreaterEqual(len(contract['probes']), 6)
        self.assertTrue(any(p.get('corrupt_config') for p in contract['probes']))
        self.assertTrue(any(p['args'] == ['self-test'] for p in contract['probes']))


class SelfTestTest(CliCase):
    def test_self_test_passes_without_any_configuration_and_reads_none(self):
        proc = self.run_stores('self-test')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(proc.stdout.strip().endswith('self-test: ok'))
        self.assertGreaterEqual(proc.stdout.count('\nok '), 8)
        self.assertEqual(self.sim.requests, []) # the self-test runs its own simulator

    def test_self_test_ignores_a_broken_config(self):
        self.write_config(raw='{not json')
        proc = self.run_stores('self-test')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, '')

    def test_self_test_without_openssl_says_so(self):
        empty = os.path.join(self.home, 'empty-bin')
        os.makedirs(empty)
        proc = self.run_stores('self-test', env=self.env(PATH=empty))
        self.assertEqual(proc.returncode, 3)
        self.assertIn('openssl', proc.stderr)

    def test_help_is_the_module_docstring(self):
        proc = self.run_stores('--help')
        self.assertEqual(proc.returncode, 0)
        self.assertIn('stores doctor [play|ios] [--live] [--json]', proc.stdout)
        self.assertEqual(self.run_stores().returncode, 2)

    def test_files_pass_the_privacy_patterns(self):
        for rel in ('global/scripts/stores', 'global/scripts/lib/access/http.py', 'global/scripts/lib/access/store_auth.py',
                    'global/scripts/lib/access/store_play.py', 'global/scripts/lib/access/store_ios.py',
                    'global/scripts/lib/access/store_selftest.py', 'global/config/stores.json', 'global/contracts/stores.yaml'):
            text = (REPO_ROOT / rel).read_text()
            self.assertNotIn('/home/', text, rel)
            self.assertIsNone(__import__('re').search(r'[A-Za-z0-9._-]+@(?!example)[A-Za-z0-9-]+\.[a-z]{2,}', text), rel)
