from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from scripts import tier1_fresh_sold_preview as pilot


def comp(sold_at, *, evidence=True):
    return SimpleNamespace(
        sold_at=sold_at, provider_evidence={"proof": True} if evidence else None,
        item_id="private-id", title="<not-public>", url="https://private.example/item"
    )


def test_sold_preview_requires_five_fresh_normalized_evidence_rows():
    now = datetime(2026, 11, 10, 20, 30, tzinfo=timezone.utc)
    data = {"status": "READY", "market_value_minor": 120,
            "comps": [comp(now - timedelta(days=x)) for x in (1, 4, 9, 18, 55)]}
    with patch.object(pilot, "has_normalized_uk_evidence", return_value=True):
        report = pilot.safe_receipt(data, now=now)
    assert report["status"] == "READY_FOR_SEPARATE_MANUAL_REVIEW"
    assert report["normalized_uk_sold_count"] == 5
    assert report["recent_14d_count"] == 3
    assert report["candidate_market_value_minor"] == 120
    assert report["result_is_not_a_current_market_value"]
    assert report["applied"] is False
    assert report["sql_or_r2_writes"] is False
    assert report["shopify_or_store_price_writes"] is False
    assert "private-id" not in repr(report) and "private.example" not in repr(report)


def test_stale_sales_never_unlock_current_market_value():
    now = datetime(2026, 11, 10, 20, 30, tzinfo=timezone.utc)
    data = {"status": "READY", "market_value_minor": 143,
            "comps": [comp(now - timedelta(days=x)) for x in (41, 43, 46, 50, 52)]}
    with patch.object(pilot, "has_normalized_uk_evidence", return_value=True):
        report = pilot.safe_receipt(data, now=now)
    assert report["status"] == "BLOCKED_INSUFFICIENT_OR_STALE_EVIDENCE"
    assert report["candidate_market_value_minor"] is None


def test_missing_or_partial_normalized_evidence_is_fail_closed():
    now = datetime(2026, 11, 10, 20, 30, tzinfo=timezone.utc)
    data = {"status": "READY", "market_value_minor": 250,
            "comps": [comp(now - timedelta(days=1)) for _ in range(5)]}
    with patch.object(pilot, "has_normalized_uk_evidence", side_effect=[True, True, False, True, True]):
        report = pilot.safe_receipt(data, now=now)
    assert report["status"] == "BLOCKED_INSUFFICIENT_OR_STALE_EVIDENCE"
    assert report["candidate_market_value_minor"] is None
    data["comps"] = data["comps"][:4]
    with patch.object(pilot, "has_normalized_uk_evidence", return_value=True):
        report = pilot.safe_receipt(data, now=now)
    assert report["status"] == "BLOCKED_INSUFFICIENT_OR_STALE_EVIDENCE"


def test_blocked_provider_response_never_leaks_a_price():
    now = datetime(2026, 11, 10, 20, 30, tzinfo=timezone.utc)
    result = pilot.safe_receipt({"status": "BLOCKED", "comps": [], "market_value_minor": 123}, now=now)
    assert result["candidate_market_value_minor"] is None
    assert result["applied"] is False


def test_fixed_target_exact_identity_and_read_only_query():
    assert pilot.IDENTITY["name"] == "Charmander"
    assert pilot.IDENTITY["card_number"] == "011/094"
    assert pilot.IDENTITY["variant"] == "Normal"
    assert pilot.IDENTITY["condition"] == "Near Mint"
    assert pilot.READ_SQL.strip().upper().startswith("SELECT ")
    assert "PUBLISHED" in pilot.READ_SQL and "market_value_minor IS NULL" in pilot.READ_SQL
    assert "--apply" not in open(pilot.__file__, encoding="utf-8").read()


def test_explicit_transaction_readonly_is_required():
    import inspect
    source = inspect.getsource(pilot.run)
    assert "readonly_snapshot=True" in source
    assert 'SHOW transaction_read_only' in source
    assert "TRANSACTION_NOT_READ_ONLY" in source
    # A read-only *session default* may remain as a second safeguard; what
    # matters is that the tested transaction checks its actual read-only mode.
    assert 'SHOW default_transaction_read_only' not in source


def test_safety_error_code_is_static_without_private_owner_data():
    exc = pilot.PilotSafetyError("TARGET_NO_LONGER_ELIGIBLE")
    assert type(exc).__name__ == "PilotSafetyError"
    assert str(exc) == "TARGET_NO_LONGER_ELIGIBLE"
