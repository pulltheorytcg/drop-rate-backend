"""Validate Cloudflare-only artwork staging without Postgres/Shopify."""
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cloudflare_worker_exact_print_and_r2_sha_contract() -> None:
    job = subprocess.run(["node", "--test", str(ROOT / "tests/cloudflare_artwork_shadow.test.mjs")],
                         capture_output=True, text=True, timeout=30, check=False)
    assert job.returncode == 0, job.stdout + "\n" + job.stderr


def test_cloudflare_d1_artwork_index_is_private_and_consistent() -> None:
    schema = (ROOT / "database/cloudflare_d1/0003_artwork_shadow.sql").read_text()
    database = sqlite3.connect(":memory:")
    database.executescript(schema)
    identity = "x:" + "a" * 64
    manifest = "b" * 64
    digest = "c" * 64
    params = (identity, "ygoprodeck", "YUGIOH", "English", "123ABC",
              "SET01", "001", "Rare", "Normal", manifest,
              "drop-rate/private-media/" + digest + ".webp",
              digest, 500, "licence-test", "STAGED_PRIVATE")
    sql = """insert into artwork_shadow_candidates
             (reference_key,provider,system_code,language,provider_id,set_id,card_number,
              rarity,finish,source_manifest_sha256,object_key,content_sha256,
              size_bytes,rights_review_id,state)
             values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    database.execute(sql,params)
    assert database.execute("select state from artwork_shadow_candidates").fetchone() == ("STAGED_PRIVATE",)
    for field_index, replacement in (
        (10, "drop-rate/private-media/" + "d" * 64 + ".webp"),  # image hash/key mismatch
        (14, "PUBLISHED"),  # only staging state is permitted
    ):
        corrupt = list(params)
        corrupt[0] = "x:" + ("d" if field_index == 10 else "e") * 64
        corrupt[field_index] = replacement
        try:
            database.execute(sql,corrupt)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("D1 schema accepted unverified or published metadata")
    try:
        database.execute(sql, params)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("D1 schema allowed duplicated source printing")
    assert database.execute("select count(*) from artwork_shadow_candidates").fetchone()[0] == 1
    database.close()
