import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'automation/n8n/pilot/safe-diagnostics.cjs'


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is unavailable')
@pytest.mark.parametrize('raw,expected', [
    ('approved_pilot_backend_invalid SECRET', 'APPROVED_PILOT_BACKEND_INVALID'),
    ('approved_pilot_signature_missing SECRET', 'APPROVED_PILOT_SIGNATURE_MISSING'),
    ('approved_pilot_backend_http_401 SECRET', 'PILOT_BACKEND_HTTP_401'),
    ('approved_pilot_backend_http_503 SECRET', 'PILOT_BACKEND_HTTP_503'),
    ('access to env vars denied SECRET', 'N8N_ENV_ACCESS_DENIED'),
    ("Cannot find module 'crypto' SECRET", 'N8N_CRYPTO_UNAVAILABLE'),
    ('SQLITE_CANTOPEN SECRET', 'N8N_TEMP_DATABASE_UNAVAILABLE'),
    ('getaddrinfo ENOTFOUND SECRET', 'PILOT_DNS_UNAVAILABLE'),
    ('connect ECONNREFUSED SECRET', 'PILOT_NETWORK_UNAVAILABLE'),
    ('task request timed out SECRET', 'N8N_TASK_RUNNER_UNAVAILABLE'),
    ('SECRET https://private.invalid/thing Authorization Bearer token', 'PILOT_RUNTIME_UNVERIFIED'),
])
def test_only_fixed_category_is_returned(raw, expected):
    code = "const {classify}=require(process.argv[1]);const i=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(classify({stdout:i.raw},'EXECUTE')));"
    result = subprocess.run(['node','-e',code,str(MODULE)], input=json.dumps({'raw':raw}), text=True, capture_output=True, check=True, timeout=5)
    data = json.loads(result.stdout)
    assert data == {'state':'RUN_UNVERIFIED','phase':'EXECUTE','reason':expected,'reconcile_before_retry':True}
    assert 'SECRET' not in result.stdout and 'private.invalid' not in result.stdout
    assert 'Bearer' not in result.stdout and not result.stderr


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is unavailable')
def test_unknown_phase_and_exec_errors_cannot_echo_input():
    code = "const {classify}=require(process.argv[1]);console.log(JSON.stringify([classify({code:'ENOENT'},'secret-phase'),classify({code:'EACCES'},'IMPORT')]));"
    result = subprocess.run(['node','-e',code,str(MODULE)], text=True, capture_output=True, check=True, timeout=5)
    a,b = json.loads(result.stdout)
    assert a['phase']=='UNKNOWN' and a['reason']=='PILOT_EXECUTABLE_NOT_FOUND'
    assert b['phase']=='IMPORT' and b['reason']=='PILOT_FILESYSTEM_PERMISSION_DENIED'
    assert 'secret-phase' not in result.stdout
