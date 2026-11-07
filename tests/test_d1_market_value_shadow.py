"""Private D1 current Market Value SQL contract (synthetic SQLite only)."""
import sqlite3
from pathlib import Path

import pytest

SQL = Path("database/cloudflare_d1/0002_market_value_shadow.sql").read_text()
H = "a"*64


@pytest.fixture()
def db():
    con = sqlite3.connect(":memory:")
    con.executescript(SQL)
    con.execute("""INSERT INTO market_shadow_generations
        (generation_id,r2_source_manifest_sha256)
        VALUES('generation-1',?)""", (H,))
    con.execute("""INSERT INTO market_shadow_profiles
        (generation_id,profile_key,provider,system_code,language,provider_id,
         product_kind,finish,condition,source_identity_sha256)
        VALUES('generation-1','raw-1','tcg','POKEMON','English',
         'exact-raw-001','RAW_CARD','normal','NM',?)""", (H,))
    con.execute("""INSERT INTO market_shadow_profiles
        (generation_id,profile_key,provider,system_code,language,provider_id,
         product_kind,finish,condition,grading_company,grade,source_identity_sha256)
        VALUES('generation-1','slab-1','tcg','POKEMON','English',
         'exact-raw-001','GRADED_CARD','normal','NM','PSA','10',?)""", (H,))
    yield con
    con.close()


def proof(db, *, proof_id, profile="raw-1", evidence="VERIFIED_SOLD",
          country="GB", rights="DISPLAY_APPROVED", comps=2, sellers=2,
          source="ebay-sold"):
    db.execute("""INSERT INTO market_shadow_source_proofs
      (generation_id,proof_id,profile_key,r2_evidence_sha256,evidence_type,
       source_name,source_run_key,observed_at,source_country,
       distinct_comparables,distinct_sellers,usage_rights)
      VALUES('generation-1',?,?,?,?,?,?,?,
       ?,?,?,?)""",
       (proof_id, profile, H, evidence, source, "run-"+proof_id,
        "2026-11-06T17:00:00Z", country, comps, sellers, rights))


def price(db, *, profile="raw-1", status="ELIGIBLE_MARKET_VALUE", proof_id="proof-1",
          amount=500, rule="sold-rule-v1"):
    db.execute("""INSERT INTO market_shadow_current_values
      (generation_id,profile_key,price_status,market_value_gbp_minor,
       source_proof_id,calculated_at,deterministic_rule_version,original_record_sha256)
      VALUES('generation-1',?,?,?,?,'2026-11-06T18:00:00Z',?,?)""",
      (profile, status, amount, proof_id, rule, H))


def test_verified_raw_market_value_appears_in_public_eligible_view(db):
    proof(db, proof_id="proof-1")
    price(db)
    values=db.execute("""SELECT profile_key,market_value_gbp_minor
      FROM market_shadow_eligible_values""").fetchall()
    assert values==[("raw-1",500)]


@pytest.mark.parametrize("evidence", ["ACTIVE_ASKING","STATISTICAL_GUIDE","MODEL_ESTIMATE"])
def test_no_listing_guide_or_ai_model_price_can_be_market_value(db,evidence):
    proof(db,proof_id="proof-1",evidence=evidence)
    with pytest.raises(sqlite3.IntegrityError,match="sold-grade"):
        price(db)


@pytest.mark.parametrize("rights", ["PENDING","BLOCKED"])
def test_unapproved_source_cannot_become_eligible_value(db,rights):
    proof(db,proof_id="proof-1",rights=rights)
    with pytest.raises(sqlite3.IntegrityError,match="sold-grade"):
        price(db)


def test_internal_approved_evidence_is_not_exposed_for_public_display(db):
    proof(db,proof_id="proof-1",rights="INTERNAL_APPROVED")
    price(db)
    assert db.execute("SELECT count(*) FROM market_shadow_eligible_values").fetchone()==(0,)


def test_non_gb_sold_comps_do_not_appear_as_uk_market_value(db):
    proof(db,proof_id="proof-1",country="US")
    with pytest.raises(sqlite3.IntegrityError,match="sold-grade"):
        price(db)


def test_graded_needs_five_independent_exact_sellers(db):
    proof(db,proof_id="graded-4",profile="slab-1",comps=4,sellers=4)
    with pytest.raises(sqlite3.IntegrityError,match="sold-grade"):
        price(db,profile="slab-1",proof_id="graded-4",amount=25000)


def test_graded_five_exact_sellers_stays_separate_from_raw_price(db):
    proof(db,proof_id="graded-5",profile="slab-1",comps=5,sellers=5)
    price(db,profile="slab-1",proof_id="graded-5",amount=25000)
    assert db.execute("SELECT profile_key,grade FROM market_shadow_eligible_values").fetchall()==[("slab-1","10")]
    assert db.execute("""SELECT count(*) FROM market_shadow_eligible_values
       WHERE profile_key='raw-1'""").fetchone()==(0,)


def test_graded_cannot_borrow_raw_sold_evidence(db):
    proof(db,proof_id="raw-proof",comps=10,sellers=10)
    with pytest.raises(sqlite3.IntegrityError):
        price(db,profile="slab-1",proof_id="raw-proof",amount=20000)


@pytest.mark.parametrize("status", ["GUIDE_ONLY","ASKING_ONLY","STALE","REVIEW_REQUIRED","MISSING"])
def test_missing_or_unverified_price_is_null_not_zero(db,status):
    price(db,status=status,proof_id=None,amount=None,rule=None)
    assert db.execute("SELECT market_value_gbp_minor FROM market_shadow_current_values").fetchone()==(None,)
    assert db.execute("SELECT count(*) FROM market_shadow_eligible_values").fetchone()==(0,)


def test_noneligible_price_cannot_smuggle_amount(db):
    with pytest.raises(sqlite3.IntegrityError):
        price(db,status="GUIDE_ONLY",proof_id=None,amount=2999)


def test_zero_or_negative_market_value_not_allowed(db):
    proof(db,proof_id="proof-1")
    for amount in (0,-100):
        with pytest.raises(sqlite3.IntegrityError):
            price(db,amount=amount)


def test_invalid_evidence_fails_closed(db):
    with pytest.raises(sqlite3.IntegrityError):
        proof(db,proof_id="proof-1",evidence="RRP")


def test_immutable_source_provenance_and_values(db):
    proof(db,proof_id="proof-1")
    price(db)
    with pytest.raises(sqlite3.IntegrityError,match="immutable"):
        db.execute("UPDATE market_shadow_current_values SET market_value_gbp_minor=9999")
    with pytest.raises(sqlite3.IntegrityError,match="immutable"):
        db.execute("DELETE FROM market_shadow_source_proofs")
    with pytest.raises(sqlite3.IntegrityError,match="immutable"):
        db.execute("DELETE FROM market_shadow_current_values")


def test_duplicate_profile_or_proof_cannot_create_duplicate_coverage(db):
    proof(db,proof_id="proof-1")
    price(db)
    with pytest.raises(sqlite3.IntegrityError):
        price(db)
    with pytest.raises(sqlite3.IntegrityError):
        proof(db,proof_id="proof-1")


def test_no_live_publish_pointer_created_by_shadow(db):
    tables={name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert all(name.startswith("market_shadow_") for name in tables)
    assert "market_active_generation" not in tables


def test_duplicate_raw_printing_with_nullable_grade_rejected(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("""INSERT INTO market_shadow_profiles
          (generation_id,profile_key,provider,system_code,language,provider_id,
           product_kind,finish,condition,source_identity_sha256)
          VALUES('generation-1','raw-duplicate','tcg','POKEMON','English',
          'exact-raw-001','RAW_CARD','normal','NM',?)""",(H,))


def test_old_sold_evidence_cannot_be_current_market_value(db):
    db.execute("""INSERT INTO market_shadow_source_proofs
      (generation_id,proof_id,profile_key,r2_evidence_sha256,evidence_type,
       source_name,source_run_key,observed_at,source_country,
       distinct_comparables,distinct_sellers,usage_rights)
      VALUES('generation-1','old','raw-1',?,'VERIFIED_SOLD',
       'ebay-sold','run-old','2025-01-01T00:00:00Z','GB',5,5,
       'DISPLAY_APPROVED')""",(H,))
    with pytest.raises(sqlite3.IntegrityError,match="sold-grade"):
        price(db,proof_id="old")


def test_market_profile_identity_cannot_be_changed_to_slab(db):
    with pytest.raises(sqlite3.IntegrityError,match="immutable"):
        db.execute("UPDATE market_shadow_profiles SET product_kind='GRADED_CARD' WHERE profile_key='raw-1'")


def test_manifest_source_digest_cannot_be_swapped(db):
    with pytest.raises(sqlite3.IntegrityError,match="immutable"):
        db.execute("UPDATE market_shadow_generations SET r2_source_manifest_sha256=?",
                   ("b"*64,))
