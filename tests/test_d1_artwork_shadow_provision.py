"""No network: artwork-only D1 schema creation and readback are fail-closed."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "artwork_provision", ROOT / "tools/d1_artwork_shadow_provision.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SCHEMA = (ROOT / "database/cloudflare_d1/0003_artwork_shadow.sql").read_text()


class FakeD1:
    account_id = mod.ACCOUNT
    path = "/accounts/test/d1/database"

    def __init__(self, count=5, existing=False, drift=False):
        self.databases = [{"name": f"other-{i}", "uuid": f"00000000-0000-0000-0000-{i:012d}"}
                          for i in range(count)]
        self.created = False
        self.writes = []
        self.object_names = set(mod.ALLOWED) if not drift else {("table", "artwork_shadow_candidates")}
        if existing:
            self.databases.append({"name": mod.DB_NAME,
                "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"})

    def list_databases(self):
        return self.databases

    def call(self, method, path, body):
        assert method == "POST" and path == self.path and body == {"name": mod.DB_NAME}
        self.created = True
        row = {"name": mod.DB_NAME, "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}
        self.databases.append(row)
        return row, None

    def query(self, dbid, sql):
        self.writes.append(sql)
        if sql.lower().startswith("select"):
            return {"results": [
                {"type": kind, "name": name} for kind, name in sorted(self.object_names)
            ]}, None
        assert sql.strip().upper().startswith("CREATE ")
        return {"results": []}, None


def test_schema_is_exact_two_artwork_only_objects():
    statements = mod.parse_schema(SCHEMA)
    assert len(statements) == 2
    assert "STAGED_PRIVATE" in SCHEMA
    assert "shopify_" not in SCHEMA.lower().split("create table", 1)[1]
    for malicious in (
        SCHEMA + "\nDROP TABLE tcg.owners;",
        SCHEMA.replace("artwork_shadow_by_scope", "ops_shadow_ledger"),
        SCHEMA.replace("artwork_shadow_candidates", "tcg_inventory"),
    ):
        with pytest.raises(mod.ArtworkShadowProvisionError):
            mod.parse_schema(malicious)


def test_new_artwork_d1_provision_proves_schema_only_and_no_cutover():
    client = FakeD1()
    result = mod.provision(client, SCHEMA, account_id=mod.ACCOUNT)
    assert client.created and len(client.writes) == 3
    assert result["status"] == "EMPTY_ARTWORK_D1_SHADOW_VERIFIED"
    assert result["artwork_rows_inserted"] == 0
    assert result["production_database_cutover"] is False
    assert result["production_media_pointer_changed"] is False
    assert result["supabase_writes"] == result["shopify_writes"] == 0


def test_existing_artwork_shadow_is_verified_without_ddl():
    client = FakeD1(existing=True)
    result = mod.provision(client, SCHEMA, account_id=mod.ACCOUNT)
    assert not result["created_new"] and not client.created
    assert len(client.writes) == 1


def test_wrong_account_slots_and_source_drift_fail_before_creation():
    clients = [FakeD1(count=8), FakeD1(existing=True, drift=True)]
    for client in clients:
        with pytest.raises(mod.ArtworkShadowProvisionError):
            mod.provision(client, SCHEMA, account_id=mod.ACCOUNT)
        assert not client.created
    with pytest.raises(mod.ArtworkShadowProvisionError):
        mod.provision(FakeD1(), SCHEMA, account_id="wrong-account")
