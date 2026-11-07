"""No credentials/network: test the actual production probe with bounded fixtures."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('business_readback', ROOT / 'scripts/business_readback.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ReadbackTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'report.json'
        self.entry, _ = probe.expectations(ROOT)
        shell = ('<script src="' + self.entry + '" defer></script>').encode()
        self.responses = {path: (200, shell, {}) for path in ('/app', '/owner')}
        self.responses['/health/ready'] = (200, b'{"database":"connected"}', {})
        for name in probe.ASSETS:
            self.responses['/assets/' + name + '?readback=business'] = (200, (ROOT / 'backend/app/static' / name).read_bytes(), {})
        for path in probe.APIS:
            self.responses[path] = (401, b'private error content', {'Cache-Control': 'no-store'})
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return self.responses[path]

    def run_probe(self, get=None, attempts=1):
        ok = probe.run(ROOT, self.output, get or self.get, attempts=attempts, sleep=lambda _: None)
        return ok, json.loads(self.output.read_text())

    def test_current_shared_shell_passes_but_old_assertion_rejects_it(self):
        self.assertIn(b'founder-accounts.js', self.responses['/owner'][1])
        ok, report = self.run_probe()
        self.assertTrue(ok)
        self.assertFalse(report['normal_seller_login_tested'])
        self.assertFalse(report['authenticated_owner_isolation_tested'])
        self.assertEqual(report['mutations'], 0)
        self.assertEqual(set(report['anonymous_api_status'].values()), {401})

    def test_missing_wrong_duplicate_or_comment_only_script_fails(self):
        for path in ('/app', '/owner'):
            for body in (b'', b'<script src="/assets/founder-accounts.js?v=old"></script>',
                         self.responses['/app'][1] * 2,
                         b'<!--' + self.responses['/app'][1] + b'-->'):
                with self.subTest(path=path, body=body):
                    original = self.responses[path]
                    self.responses[path] = (200, body, {})
                    ok, report = self.run_probe()
                    self.assertFalse(ok)
                    self.assertEqual(report['failure'], 'SHARED_ENTRY_RELEASE_MISMATCH')
                    self.responses[path] = original

    def test_stale_asset_fails(self):
        self.responses['/assets/founder-accounts.js?readback=business'] = (200, b'old', {})
        self.assertFalse(self.run_probe()[0])

    def test_asset_and_shell_http_errors_fail(self):
        for path in ('/owner', '/app', '/assets/business-area.css?readback=business'):
            with self.subTest(path=path):
                original = self.responses[path]
                self.responses[path] = (503, original[1], {})
                self.assertFalse(self.run_probe()[0])
                self.responses[path] = original

    def test_database_http_body_and_shape_fail_closed(self):
        for value in ((503, b'{"database":"connected"}', {}), (200, b'{"database":"unavailable"}', {}),
                      (200, b'not json', {}), (200, b'[]', {})):
            self.responses['/health/ready'] = value
            self.assertFalse(self.run_probe()[0])

    def test_every_founder_api_requires_401_and_no_store(self):
        for path in probe.APIS:
            for status, headers, reason in ((200, {'Cache-Control':'no-store'}, 'ANONYMOUS_FOUNDER_API_NOT_DENIED'),
                                            (403, {'Cache-Control':'no-store'}, 'ANONYMOUS_FOUNDER_API_NOT_DENIED'),
                                            (401, {}, 'PRIVATE_CACHE_PROTECTION_MISSING')):
                with self.subTest(path=path,status=status,headers=headers):
                    original = self.responses[path]
                    self.responses[path] = (status, b'SECRET_SENTINEL', headers)
                    ok, report = self.run_probe(attempts=3)
                    self.assertFalse(ok)
                    self.assertEqual(report['attempts'], 1)
                    self.assertEqual(report['failure'], reason)
                    self.assertNotIn('SECRET_SENTINEL', self.output.read_text())
                    self.responses[path] = original

    def test_transient_retry_recovers_and_clears_failure(self):
        first = True
        def get(path):
            nonlocal first
            if first:
                first = False
                raise urllib.error.URLError('SECRET_SENTINEL')
            return self.get(path)
        ok, report = self.run_probe(get, attempts=2)
        self.assertTrue(ok)
        self.assertEqual(report['attempts'], 2)
        self.assertNotIn('failure', report)

    def test_network_failure_writes_redacted_report(self):
        def get(path): raise urllib.error.URLError('SECRET_SENTINEL')
        ok, report = self.run_probe(get, attempts=2)
        self.assertFalse(ok)
        self.assertEqual(report['attempts'], 2)
        self.assertNotIn('SECRET_SENTINEL', self.output.read_text())

    def test_invalid_source_still_writes_report(self):
        ok = probe.run(Path(self.directory.name), self.output, self.get)
        self.assertFalse(ok)
        self.assertEqual(json.loads(self.output.read_text())['failure'], 'SOURCE_OR_PROBE_ERROR')


if __name__ == '__main__':
    unittest.main()
