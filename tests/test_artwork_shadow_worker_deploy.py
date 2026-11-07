"""Synthetic-only DR101 Worker deployment preflight regression tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import artwork_shadow_worker_deploy as stage


class FakeCloudflare:
    account_id = stage.ACCOUNT

    def __init__(self, *, db_id="12345678-1234-1234-1234-123456789abc",
                 name=stage.DB_NAME, columns=True, rows=0):
        self.db_id, self.name, self.columns, self.rows = db_id, name, columns, rows
        self.calls = []

    def list_databases(self):
        self.calls.append(("GET", "list_databases"))
        return [{"name": self.name, "uuid": self.db_id}]

    def query(self, dbid, sql):
        self.calls.append(("QUERY", sql))
        assert dbid == self.db_id
        if "sqlite_master" in sql:
            objects = [
                {"type": "table", "name": "artwork_shadow_candidates"},
                {"type": "index", "name": "artwork_shadow_by_scope"},
            ]
            if not self.columns:
                objects.pop()
            return {"results": objects}, 0
        if "count(*)" in sql:
            return {"results": [{"total": self.rows}]}, 0
        raise AssertionError("Preflight attempted an unexpected SQL operation")


def test_exact_existing_d1_config_and_read_only_calls():
    fake = FakeCloudflare()
    result = stage.prepare(fake, bucket="drop-rate-existing-r2", account=stage.ACCOUNT)
    config = result["config"]
    assert config["main"] == "worker.mjs"
    assert config["name"] == "drop-rate-artwork-shadow"
    assert config["workers_dev"] is True  # HMAC-only endpoint; no image GET routes
    assert config["r2_buckets"] == [
        {"binding": "ARTWORK_R2", "bucket_name": "drop-rate-existing-r2",\n         "jurisdiction": "eu"}]
    assert config["d1_databases"][0]["database_name"] == stage.DB_NAME
    assert config["d1_databases"][0]["binding"] == "ARTWORK_D1"
    assert result["existing_staged_rows"] == 0
    assert all(method in ("GET", "QUERY") for method, _ in fake.calls)
    assert all(not any(word in sql.upper() for word in ("INSERT", "UPDATE", "DELETE", "DROP"))
               for method, sql in fake.calls if method == "QUERY")


@pytest.mark.parametrize("bad_bucket", [
    "", "Uppercase", "bucket/other", "another.bucket", "has spaces", "a" * 90,
])
def test_unapproved_bucket_names_fail_closed(bad_bucket):
    with pytest.raises(stage.ArtworkDeploymentBlocked):
        stage.build_config(
            database_id="12345678-1234-1234-1234-123456789abc",
            bucket=bad_bucket)


def test_exact_eu_r2_jurisdiction_is_pinned_in_generated_worker_config():
    # Actual Cloudflare R2 bucket 'drop-rate-private' is jurisdiction EU;
    # omitting the binding jurisdiction causes remote error code 10085.
    config = stage.build_config(
        database_id="12345678-1234-1234-1234-123456789abc",
        bucket="drop-rate-private",
    )
    assert config["r2_buckets"] == [{
        "binding": "ARTWORK_R2",
        "bucket_name": "drop-rate-private",
        "jurisdiction": "eu",
    }]
    assert len(config["r2_buckets"]) == 1
    assert config["d1_databases"][0]["binding"] == "ARTWORK_D1"


def test_wrong_account_or_wrong_d1_schema_fails_closed():
    fake = FakeCloudflare()
    with pytest.raises(stage.ArtworkDeploymentBlocked):
        stage.prepare(fake, bucket="drop-rate-existing-r2", account="0" * 32)
    for modified in (FakeCloudflare(name="production-finance"),
                     FakeCloudflare(columns=False),
                     FakeCloudflare(db_id="not-uuid")):
        with pytest.raises(stage.ArtworkDeploymentBlocked):
            stage.prepare(modified, bucket="drop-rate-existing-r2", account=stage.ACCOUNT)


def test_existing_rows_are_read_but_never_modified():
    fake = FakeCloudflare(rows=21)
    result = stage.prepare(fake, bucket="drop-rate-existing-r2", account=stage.ACCOUNT)
    assert result["existing_staged_rows"] == 21
    assert len(fake.calls) == 3


@pytest.mark.parametrize("url", [
    "https://another-worker.example.com",
    "http://drop-rate-artwork-shadow.x.workers.dev",
    "https://drop-rate-artwork-shadow.x.workers.dev.evil.org",
    "https://drop-rate-artwork-shadow.x.workers.dev:8443",
    "https://user:pass@drop-rate-artwork-shadow.x.workers.dev",
    "https://drop-rate-artwork-shadow.x.workers.dev?token=leak",
])
def test_smoke_rejects_unrelated_or_insecure_origins_before_network(url):
    with pytest.raises(stage.ArtworkDeploymentBlocked):
        stage.smoke_url(url)
