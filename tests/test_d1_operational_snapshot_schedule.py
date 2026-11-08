"""Fail-closed contract for the protected D1 operational snapshot schedule."""
from pathlib import Path


WF=Path(".github/workflows/d1-operational-real-source-stage.yml")


def test_real_d1_staging_requires_main_branch_and_protected_event():
    src=WF.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in src
    assert "cron: '37 3 * * *'" in src
    assert "github.ref == 'refs/heads/main'" in src
    assert "github.event_name == 'schedule'" in src
    assert "github.event_name == 'workflow_dispatch'" in src
    assert "if: github.ref == 'refs/heads/main'" in src
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
