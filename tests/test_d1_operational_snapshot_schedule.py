"""Fail-closed contract for the protected D1 operational snapshot schedule."""
from pathlib import Path
from types import SimpleNamespace
import pytest


WF=Path(".github/workflows/d1-operational-real-source-stage.yml")


def test_real_d1_staging_requires_main_branch_and_protected_event():
    src=WF.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in src
    assert "cron: '37 3 * * *'" in src
    assert "github.ref == 'refs/heads/main'" in src
    assert "github.event_name == 'schedule'" in src
    assert "github.event_name == 'workflow_dispatch'" in src
    assert "if: >-" in src
    assert "environment: production" in src
    assert "group: private-operational-d1-real-source-single-writer" in src
    assert "cancel-in-progress: false" in src
    assert "SUPABASE_DB_PASSWORD: ${{ secrets.SUPABASE_DB_PASSWORD }}" in src
    assert "CLOUDFARE_D1_PILOT_TOKEN: ${{ secrets.CLOUDFARE_D1_PILOT_TOKEN }}" in src
    assert "readonly" in Path("tools/d1_operational_source_stage.py").read_text()
    assert "INVENTORY_REPLAY_SNAPSHOT_PARITY_VERIFIED" in src
    assert "production_reads_switched" in src
    assert "payment_or_settlement_executed" in src


def test_d1_snapshot_daily_is_not_live_seller_traffic_or_auth_migration():
    src=WF.read_text(encoding="utf-8")
    assert "shopify" not in src.lower().split("stage-real-private-d1:")[1].split("      - name:")[0]
    assert "postgres w" not in src.lower()
    # The release gate asserts no cutover, no payments, no Supabase retirement.
    for clause in ("r['production_reads_switched'] is False",
                   "r['payment_or_settlement_executed'] is False",
                   "r['supabase_source_retired'] is False"):
        assert clause in src


@pytest.mark.parametrize('event,ref,approved_sha,approved_run,expected',[
    ('push','refs/heads/main','','',False),
    ('schedule','refs/heads/main','','',False),
    ('workflow_dispatch','refs/heads/main','','',False),
    ('push','refs/heads/main','a'*40,'',False),
    ('push','refs/heads/main','','123',False),
    ('push','refs/heads/main','b'*40,'123',False),
    ('schedule','refs/heads/main','a'*40,'122',False),
    ('pull_request','refs/heads/main','a'*40,'123',False),
    ('push','refs/heads/feature','a'*40,'123',False),
    ('push','refs/heads/main','a'*40,'123',True),
    ('schedule','refs/heads/main','a'*40,'123',True),
    ('workflow_dispatch','refs/heads/main','a'*40,'123',True),
])
def test_all_operational_shadow_writes_require_exact_release_approval(event,ref,approved_sha,approved_run,expected):
    src=WF.read_text()
    job=src.split('  stage-real-private-d1:\n',1)[1]
    condition=job.split('    if: >-\n',1)[1].split('    needs:',1)[0]
    expression=' '.join(condition.split()).replace('&&','and').replace('||','or')
    actual=eval(expression,{'__builtins__':{}},{
        'github':SimpleNamespace(event_name=event,ref=ref,sha='a'*40,run_id='123'),
        'vars':SimpleNamespace(DR_D1_OPERATIONAL_STAGE_APPROVED_SHA=approved_sha,
                               DR_D1_OPERATIONAL_STAGE_APPROVED_RUN_ID=approved_run),
    })
    assert actual is expected
    assert 'needs: offline-shadow-parity' in job
    assert 'environment: production' in job
