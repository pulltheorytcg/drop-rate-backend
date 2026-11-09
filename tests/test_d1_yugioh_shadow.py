"""Offline real-shaped Yu-Gi-Oh source and D1 staged import proof; no network."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import sqlite3
from pathlib import Path
import sys

import httpx
import pytest

from app import r2_first_catalogue as source_codec

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import d1_yugioh_shadow as runner  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402

UUID = "12345678-1234-1234-1234-1234567890ab"


class FakeD1:
    existing = []
    conn = None
    mutations = 0

    def __init__(self, account, token):
        assert account == "a"*32
        assert token == "dummy-test-token"
        self.path = "/accounts/" + account + "/d1/database"

    def list_databases(self):
        return self.existing[:]

    def call(self, method, path, data=None):
        assert method == "POST" and path == self.path
        assert data == {"name": runner.EXACT_DATABASE_NAME}
        if self.existing:
            raise AssertionError("Must not create duplicate shadow")
        type(self).existing = [{"name":runner.EXACT_DATABASE_NAME, "uuid":UUID}]
        type(self).conn = sqlite3.connect(":memory:", isolation_level=None)
        type(self).conn.row_factory = sqlite3.Row
        type(self).conn.execute("pragma foreign_keys=on")
        return {"name":runner.EXACT_DATABASE_NAME,"uuid":UUID}, 0

    def query(self, uuid, sql, params=()):
        assert uuid == UUID
        # Retained and current source readback must use the indexed
        # (manifest_sha, card_key) cursor, never quadratic OFFSET scans.
        if "from shadow_cards" in sql.lower() and "order by card_key" in sql.lower():
            assert "offset" not in sql.lower()
            assert "card_key>?" in sql.lower()
            assert len(params)==3 and isinstance(params[1],str)
        cur = self.conn.execute(sql, params)
        if sql.lower().strip().startswith("insert"):
            type(self).mutations += 1
        return ({"success":True,
                 "results":[dict(x) for x in cur.fetchall()] if cur.description else []}, 0)

    def batch(self, uuid, queries):
        assert uuid == UUID
        assert 1 <= len(queries) <= 12
        for query in queries:
            assert len(query["params"]) <= 100
            self.query(uuid, query["sql"], query["params"])
        return [{"success":True,"results":[]} for _ in queries]


@pytest.fixture(autouse=True)
def fake_cloud(monkeypatch):
    FakeD1.existing = []
    FakeD1.conn = None
    FakeD1.mutations = 0
    monkeypatch.setattr(runner, "D1Client", FakeD1)
    monkeypatch.setattr(runner, "_oidc_token", lambda: "fake-oidc")
    monkeypatch.setattr(runner, "EXPECTED_RECORDS", 23)
    monkeypatch.setattr(runner, "DAILY_NEW_ROWS", 7)
    yield
    if FakeD1.conn:
        FakeD1.conn.close()
    FakeD1.existing = []
    FakeD1.conn = None


def fixture(count=23, *, tamper=False, name_prefix="Real-shaped",
            renamed_indices=(), rarity="Common", set_id="TST"):
    rows = []
    for i in range(count):
        rows.append({
            "provider":"ygoprodeck", "system_code":"YUGIOH", "language":"English",
            "provider_id":f"ygoprodeck:fixture-{i:05d}",
            "product_type":"CARD",
            "name":f"{'Revised' if i in renamed_indices else name_prefix} Yu-Gi-Oh {i}",
            "set_id":set_id, "set_name":"Synthetic Yu-Gi-Oh",
            "card_number":f"{i:04d}", "rarity":rarity, "finish":None,
            "release_date":"2026-01-01",
            "source_url":"https://db.ygoprodeck.com/api/v7/cardinfo.php",
        })
    bundle=source_codec.prepare_catalogue(
        rows, provider="ygoprodeck",system_code="YUGIOH",language="English",
        source_url="https://db.ygoprodeck.com/api/v7/cardinfo.php",
        source_revision="synthetic-verified",permission_ref="https://ygoprodeck.com/api-guide/")
    raw=bundle._manifest_bytes
    parts=list(bundle.parts)
    def handler(req:httpx.Request):
        assert req.url.host=="drop-rate-api-live-production.up.railway.app"
        assert req.headers["authorization"] == "Bearer fake-oidc"
        if req.url.path==runner.SOURCE_PATH_YUGIOH+"/manifest":
            return httpx.Response(200,content=raw)
        if req.url.path.startswith(runner.SOURCE_PATH_YUGIOH+"/part/"):
            ordinal=int(req.url.path.rsplit("/",1)[-1])
            content=parts[ordinal]
            if tamper and ordinal==0:
                content=content[:-1]+b"!"
            return httpx.Response(200,content=content)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler),
                        follow_redirects=False), bundle


def test_source_readback_is_primary_key_cursor_paged():
    assert "card_key>?" in runner.D1_READBACK_SQL
    assert "offset" not in runner.D1_READBACK_SQL.lower()
    client, _ = fixture(count=301)
    with client:
        for day in range(1,8):
            report=runner.run("a"*32,"dummy-test-token","7070","1",
                client=client,now=datetime(2026,12,day,tzinfo=timezone.utc))
            assert report["no_public_catalogue_cutover"] is True
    assert FakeD1.conn.execute(
        "select count(*) from shadow_cards").fetchone()[0]==49


def test_yugioh_stage_is_immutable_unpublished_until_complete():
    client, _ = fixture()
    with client:
        for day, expected in [(6,7),(6,7),(7,14),(8,21),(9,23)]:
            current = datetime(2026,11,day,tzinfo=timezone.utc)
            report=runner.run("a"*32,"dummy-test-token","1000","1",client=client,now=current)
            assert report["d1_staged_rows" if "d1_staged_rows" in report else "d1_verified_rows"] == expected
            assert report["market_value_writes"] == 0
            assert report["owner_and_settlement_writes"] == 0
            assert report["no_public_catalogue_cutover"] is True
            active=FakeD1.conn.execute("select count(*) from shadow_live_cards").fetchone()[0]
            assert active == (23 if expected == 23 else 0)
        assert report["status"] == "REAL_R2_YUGIOH_TO_ISOLATED_D1_VERIFIED"
        assert report["source_rows"]==23
        assert FakeD1.conn.execute("select count(*) from shadow_daily_write_budget").fetchone()[0]==4
        assert FakeD1.conn.execute("select count(*) from shadow_cards").fetchone()[0]==23


def test_budget_duplicate_day_does_not_write_or_change_staged_rows():
    client,_=fixture()
    with client:
        first=runner.run("a"*32,"dummy-test-token","1100","1",
                         client=client,now=datetime(2026,11,6,tzinfo=timezone.utc))
        before=FakeD1.mutations
        second=runner.run("a"*32,"dummy-test-token","1101","1",
                          client=client,now=datetime(2026,11,6,tzinfo=timezone.utc))
    assert first["status"]=="YUGIOH_D1_SHADOW_PARTIAL_VERIFIED"
    assert second["status"]=="YUGIOH_D1_SHADOW_DAILY_BUDGET_ALREADY_USED"
    assert FakeD1.mutations == before
    assert second["d1_staged_rows"]==7


def test_source_change_mid_migration_fails_without_a_new_generation_or_writes():
    client,_=fixture()
    with client:
        runner.run("a"*32,"dummy-test-token","1102","1",
                   client=client,now=datetime(2026,11,6,tzinfo=timezone.utc))
    staged_before=FakeD1.conn.execute("select count(*) from shadow_cards").fetchone()[0]
    changed,_=fixture(rarity="Rare")
    with changed, pytest.raises(MigrationGuard, match="identities changed") as drift:
        runner.run("a"*32,"dummy-test-token","1103","1",
                   client=changed,now=datetime(2026,11,7,tzinfo=timezone.utc))
    assert '"changed_rows": 7' in str(drift.value)
    assert FakeD1.conn.execute("select count(*) from shadow_cards").fetchone()[0]==staged_before
    assert FakeD1.conn.execute("select count(*) from shadow_active_partitions").fetchone()[0]==0



def test_new_verified_r2_source_growth_retains_older_partial_generation():
    old,_ = fixture()
    with old:
        initial = runner.run("a"*32,"dummy-test-token","1200","1",
            client=old,now=datetime(2026,11,6,tzinfo=timezone.utc))
    assert initial["d1_staged_rows"] == 7
    old_manifest = FakeD1.conn.execute(
        "select manifest_sha from shadow_generations").fetchone()[0]
    updated,_ = fixture(count=24)
    with updated:
        for day, expected in [(7,7),(8,14),(9,21),(10,24)]:
            result = runner.run("a"*32,"dummy-test-token","1201","1",
                client=updated,now=datetime(2026,11,day,tzinfo=timezone.utc))
            assert result.get("d1_staged_rows",result.get("d1_verified_rows")) == expected
            assert FakeD1.conn.execute(
                "select count(*) from shadow_cards where manifest_sha=?",
                (old_manifest,)).fetchone()[0] == 7
            assert FakeD1.conn.execute(
                "select count(*) from shadow_live_cards").fetchone()[0] == (
                    24 if expected==24 else 0)
    assert result["status"] == "REAL_R2_YUGIOH_TO_ISOLATED_D1_VERIFIED"
    assert FakeD1.conn.execute("select count(*) from shadow_generations").fetchone()[0] == 2
    assert FakeD1.conn.execute("select count(*) from shadow_cards").fetchone()[0] == 31
    assert FakeD1.conn.execute("select count(*) from shadow_daily_write_budget").fetchone()[0] == 5



def test_verified_three_name_corrections_create_new_immutable_generation(capsys):
    old,_=fixture()
    with old:
        result=runner.run("a"*32,"dummy-test-token","1230","1",client=old,
                          now=datetime(2026,11,6,tzinfo=timezone.utc))
    assert result["d1_staged_rows"]==7
    old_sha=FakeD1.conn.execute("select manifest_sha from shadow_generations").fetchone()[0]
    original_row=FakeD1.conn.execute(
        "select card_key,name from shadow_cards where manifest_sha=? order by card_key limit 1",
        (old_sha,)).fetchone()
    old_key,original_name=original_row["card_key"],original_row["name"]
    retained_ids={
        int(row[0].rsplit("-",1)[-1]) for row in FakeD1.conn.execute(
            "select provider_id from shadow_cards where manifest_sha=? "
            "order by card_key limit 3",(old_sha,)).fetchall()
    }
    assert len(retained_ids)==3
    corrected,_=fixture(count=24,renamed_indices=retained_ids)
    with corrected:
        first=runner.run("a"*32,"dummy-test-token","1231","1",client=corrected,
                         now=datetime(2026,11,7,tzinfo=timezone.utc))
        assert first["status"]=="YUGIOH_D1_SHADOW_PARTIAL_VERIFIED"
        assert first["d1_staged_rows"]==7
        event=capsys.readouterr().out
        assert "YUGIOH_RETAINED_NAME_ONLY_CORRECTIONS_VERIFIED" in event
        assert '"changed_rows": 3' in event
        assert '"name": 3' in event and '"name_fold": 3' in event
        assert "Revised Yu-Gi-Oh" not in event
        assert "ygoprodeck:fixture-" not in event
        current_sha=FakeD1.conn.execute(
            "select manifest_sha from shadow_generations where manifest_sha!=?",
            (old_sha,)).fetchone()[0]
        assert FakeD1.conn.execute(
            "select name from shadow_cards where manifest_sha=? order by card_key limit 1",
            (old_sha,)).fetchone()[0]==original_name
        assert FakeD1.conn.execute(
            "select name from shadow_cards where manifest_sha=? and card_key=?",
            (current_sha,old_key)).fetchone()[0].startswith("Revised ")
        assert FakeD1.conn.execute(
            "select count(*) from shadow_live_cards").fetchone()[0]==0
        for date,amount in [(8,14),(9,21),(10,24)]:
            result=runner.run("a"*32,"dummy-test-token","1232","1",client=corrected,
                              now=datetime(2026,11,date,tzinfo=timezone.utc))
            assert result.get("d1_staged_rows",result.get("d1_verified_rows"))==amount
        assert result["status"]=="REAL_R2_YUGIOH_TO_ISOLATED_D1_VERIFIED"
        assert result["no_public_catalogue_cutover"] is True
        assert result["market_value_writes"]==0
        assert result["owner_and_settlement_writes"]==0
        assert FakeD1.conn.execute(
            "select count(*) from shadow_live_cards").fetchone()[0]==24
    assert FakeD1.conn.execute("select count(*) from shadow_cards").fetchone()[0]==31
    assert FakeD1.conn.execute(
        "select name from shadow_cards where manifest_sha=? order by card_key limit 1",
        (old_sha,)).fetchone()[0]==original_name


def test_bad_name_fold_never_creates_new_generation():
    old,_=fixture()
    with old:
        runner.run("a"*32,"dummy-test-token","1233","1",client=old,
                   now=datetime(2026,11,6,tzinfo=timezone.utc))
    FakeD1.conn.execute(
        "update shadow_cards set name_fold='INVALID' "
        "where card_key=(select card_key from shadow_cards order by card_key limit 1)")
    before=FakeD1.mutations
    retained_ids={
        int(row[0].rsplit("-",1)[-1]) for row in FakeD1.conn.execute(
            "select provider_id from shadow_cards order by card_key limit 3").fetchall()
    }
    corrected,_=fixture(count=24,renamed_indices=retained_ids)
    with corrected,pytest.raises(MigrationGuard,match="normalization mismatch"):
        runner.run("a"*32,"dummy-test-token","1234","1",client=corrected,
                   now=datetime(2026,11,7,tzinfo=timezone.utc))
    assert FakeD1.mutations==before
    assert FakeD1.conn.execute("select count(*) from shadow_generations").fetchone()[0]==1


def test_bulk_name_changes_fail_closed_without_a_new_generation():
    old,_=fixture()
    with old:
        for d in (6,7):
            runner.run("a"*32,"dummy-test-token","1235","1",client=old,
                       now=datetime(2026,11,d,tzinfo=timezone.utc))
    before=FakeD1.mutations
    changed_ids={
        int(row[0].rsplit("-",1)[-1]) for row in FakeD1.conn.execute(
            "select provider_id from shadow_cards order by card_key limit 14").fetchall()
    }
    assert len(changed_ids)==14
    corrected,_=fixture(count=24,renamed_indices=changed_ids)
    with corrected,pytest.raises(MigrationGuard,match="manual review required") as drift:
        runner.run("a"*32,"dummy-test-token","1236","1",client=corrected,
                   now=datetime(2026,11,8,tzinfo=timezone.utc))
    assert '"changed_rows": 14' in str(drift.value)
    assert FakeD1.mutations==before
    assert FakeD1.conn.execute("select count(*) from shadow_generations").fetchone()[0]==1


def test_changed_existing_identity_blocks_source_growth_without_overwrite():
    old,_ = fixture()
    with old:
        runner.run("a"*32,"dummy-test-token","1202","1",
            client=old,now=datetime(2026,11,6,tzinfo=timezone.utc))
    changed,_ = fixture(count=24,set_id="REVISED")
    with changed, pytest.raises(MigrationGuard,match="identities changed") as drift:
        runner.run("a"*32,"dummy-test-token","1203","1",
            client=changed,now=datetime(2026,11,7,tzinfo=timezone.utc))
    diagnostic = str(drift.value)
    assert '"retained_rows": 7' in diagnostic
    assert '"missing_keys": 0' in diagnostic
    assert '"changed_rows": 7' in diagnostic
    assert '"set_id": 7' in diagnostic
    assert "ygoprodeck:fixture-" not in diagnostic
    assert "REVISED" not in diagnostic
    assert FakeD1.conn.execute("select count(*) from shadow_generations").fetchone()[0]==1
    assert FakeD1.conn.execute("select count(*) from shadow_cards").fetchone()[0]==7
    assert FakeD1.conn.execute("select count(*) from shadow_live_cards").fetchone()[0]==0


def test_wrong_r2_digest_fails_before_any_cloudflare_writes():
    client,_=fixture(tamper=True)
    with client, pytest.raises((ValueError, MigrationGuard)):
        runner.run("a"*32,"dummy-test-token","1104","1",client=client)
    assert FakeD1.conn is None


def test_tampered_staged_record_blocks_resume_and_publication():
    client,_=fixture()
    with client:
        runner.run("a"*32,"dummy-test-token","1105","1",
                   client=client,now=datetime(2026,11,6,tzinfo=timezone.utc))
        FakeD1.conn.execute("update shadow_cards set name='TAMPERED' where "
                            "card_key=(select card_key from shadow_cards limit 1)")
        with pytest.raises(MigrationGuard, match="prefix"):
            runner.run("a"*32,"dummy-test-token","1105","1",
                       client=client,now=datetime(2026,11,7,tzinfo=timezone.utc))
        assert FakeD1.conn.execute("select count(*) from shadow_live_cards").fetchone()[0]==0


def test_cloudflare_database_count_guard_and_duplicate_uuid():
    FakeD1.existing=[{"name":"shadow-"+str(i), "uuid":UUID} for i in range(10)]
    with pytest.raises(MigrationGuard, match="budget"):
        runner._database(FakeD1("a"*32,"dummy-test-token"))
    FakeD1.existing=[{"name":runner.EXACT_DATABASE_NAME,"uuid":"unsafe-path"}]
    with pytest.raises(MigrationGuard, match="UUID"):
        runner._database(FakeD1("a"*32,"dummy-test-token"))



def test_temporary_503_before_railway_ready_retries_without_d1_write(monkeypatch):
    client,_=fixture()
    with client:
        original=runner.load_verified_source
        attempts=[]
        delays=[]
        def temporary(*args,**kwargs):
            attempts.append(FakeD1.conn is None)
            if len(attempts) <= 2:
                raise MigrationGuard("R2 export rejected: HTTP 503")
            return original(*args,**kwargs)
        monkeypatch.setattr(runner,"load_verified_source",temporary)
        monkeypatch.setattr(runner.time,"sleep",lambda seconds:delays.append(seconds))
        result=runner.run("a"*32,"dummy-test-token","1106","1",client=client,
                          now=datetime(2026,11,6,tzinfo=timezone.utc))
    assert attempts==[True,True,True]
    assert delays==[10,10]
    assert result["d1_staged_rows"]==7


def test_unauthorized_r2_export_fails_without_retry_or_cloudflare_creation(monkeypatch):
    client,_=fixture()
    with client:
        delays=[]
        monkeypatch.setattr(runner.time,"sleep",lambda sec:delays.append(sec))
        def refused(*args,**kwargs):
            raise MigrationGuard("R2 export rejected: HTTP 403")
        monkeypatch.setattr(runner,"load_verified_source",refused)
        with pytest.raises(MigrationGuard,match="403"):
            runner.run("a"*32,"dummy-test-token","1107","1",client=client)
    assert FakeD1.conn is None
    assert delays==[]



def test_main_branch_workflow_credentials_are_evaluated_not_literal_backslashes():
    """Run #7 failed D1 and GitHub status HTTP 401 when token strings were prefixed by '\\'."""
    workflow = (Path(__file__).resolve().parents[1]
                / ".github/workflows/d1-yugioh-r2-shadow.yml").read_text()
    assert (chr(92) + "$" + "{{") not in workflow
    assert "CLOUDFARE_D1_PILOT_TOKEN: " + "$" + "{{ secrets.CLOUDFARE_D1_PILOT_TOKEN }}" in workflow
    assert "GITHUB_STATUS_TOKEN: " + "$" + "{{ github.token }}" in workflow
    assert "D1_IMPORT_OUTCOME: " + "$" + "{{ steps.real_import.outcome }}" in workflow
    assert "D1_IMPORT_COMMIT: " + "$" + "{{ github.sha }}" in workflow
    assert "D1_IMPORT_REPOSITORY: " + "$" + "{{ github.repository }}" in workflow
