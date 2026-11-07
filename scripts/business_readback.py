"""Read-only, credential-free release evidence for the existing shared hub."""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

BASE = 'https://drop-rate-api-live-production.up.railway.app'
ASSETS = ('founder-accounts.js', 'business-area.css', 'workspace-shell.js')
APIS = ('/api/v1/founder/accounts', '/api/v1/founder/accounts/inventory', '/api/v1/founder/accounts/activity')


class CheckFailure(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            for key, value in attrs:
                if key == 'src' and value and 'founder-accounts.js' in value:
                    self.entries.append(value)


def script_entries(body):
    parser = Scripts()
    parser.feed(body.decode('utf-8'))
    return parser.entries


def expectations(root):
    static = root / 'backend/app/static'
    entries = re.findall(r'(/assets/founder-accounts\.js\?v=[A-Za-z0-9._-]+)',
                         (root / 'backend/app/main.py').read_text())
    if len(entries) != 1 or script_entries((static / 'owner.html').read_bytes()) != entries:
        raise CheckFailure('SOURCE_SHARED_ENTRY_INVALID')
    return entries[0], {name: hashlib.sha256((static / name).read_bytes()).hexdigest() for name in ASSETS}


def fetch(path):
    request = urllib.request.Request(BASE + path, headers={'Cache-Control': 'no-cache'})
    try:
        response = urllib.request.urlopen(request, timeout=12)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), response.headers


def verify(get, entry, expected, report):
    actual = {}
    report['asset_sha256'] = actual
    for name in ASSETS:
        status, body, _ = get('/assets/' + name + '?readback=business')
        if status != 200:
            raise CheckFailure('ASSET_UNAVAILABLE', True)
        actual[name] = hashlib.sha256(body).hexdigest()
    if actual != expected:
        raise CheckFailure('ASSET_RELEASE_MISMATCH', True)
    status, body, _ = get('/health/ready')
    report['readiness'] = status
    try:
        connected = json.loads(body).get('database') == 'connected'
    except (ValueError, AttributeError):
        connected = False
    if status != 200 or not connected:
        raise CheckFailure('DATABASE_NOT_READY', True)
    for path in ('/app', '/owner'):
        status, body, _ = get(path)
        if status != 200 or script_entries(body) != [entry]:
            raise CheckFailure('SHARED_ENTRY_RELEASE_MISMATCH', True)
    denied = {}
    report['anonymous_api_status'] = denied
    for path in APIS:
        status, _, headers = get(path)
        denied[path] = status
        if status != 401:
            raise CheckFailure('ANONYMOUS_FOUNDER_API_NOT_DENIED')
        if headers.get('Cache-Control') != 'no-store':
            raise CheckFailure('PRIVATE_CACHE_PROTECTION_MISSING')


def run(root, output, get=fetch, attempts=36, delay=5, sleep=time.sleep):
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'verified': False,
              'normal_seller_login_tested': False, 'founder_login_tested': False,
              'authenticated_owner_isolation_tested': False, 'mutations': 0}
    try:
        entry, expected = expectations(root)
        report['expected_entry'] = entry
        for attempt in range(attempts):
            report['attempts'] = attempt + 1
            try:
                verify(get, entry, expected, report)
                report['verified'] = True
                report.pop('failure', None)
                break
            except CheckFailure as error:
                report['failure'] = error.code
                if not error.retryable:
                    break
            except (OSError, urllib.error.URLError, UnicodeError):
                report['failure'] = 'NETWORK_OR_ENCODING_ERROR'
            if attempt + 1 < attempts:
                sleep(delay)
    except CheckFailure as error:
        report['failure'] = error.code
    except Exception:
        # Do not emit exception messages: upstream content may contain sensitive data.
        report['failure'] = 'SOURCE_OR_PROBE_ERROR'
    finally:
        output.write_text(json.dumps(report, indent=2) + '\n')
    return report['verified']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('business-readback.json'))
    parser.add_argument('--attempts', type=int, default=36)
    args = parser.parse_args()
    if not 1 <= args.attempts <= 36:
        parser.error('--attempts must be between 1 and 36')
    ok = run(Path(__file__).resolve().parents[1], args.output, attempts=args.attempts)
    print('PASS: shared release assets/entries, readiness and anonymous founder denial. No signed-in permissions or transactions tested.' if ok else 'FAIL: release not accepted; see redacted business-readback report.')
    raise SystemExit(0 if ok else 1)
