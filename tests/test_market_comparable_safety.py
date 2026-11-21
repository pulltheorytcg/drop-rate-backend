from __future__ import annotations

from app.ebay_batch_budget import plan_daily_batch, prioritize_refresh_items
from app.market_comparable_safety import (
    asking_price_diagnostics, evaluate_treatment, sealed_product_type,
    treatment_signals, verify_sealed_product,
)


def comparable(price: int, item: str, seller: str, **overrides):
    result = dict(
        source="EBAY_BROWSE",
        source_item_id=item,
        seller_id=seller,
        match_status="EXACT_MATCH",
        observation_type="ACTIVE",
        currency="GBP",
        asking_price_gbp=str(price),
        actual_paid_price_verified=False,
    )
    return {**result, **overrides}


def test_rogue_700_pound_listing_excluded_from_50_pound_asking_context():
    rows = [comparable(p, str(i), f"seller{i}") for i, p in enumerate([45, 48, 50, 52, 55, 700])]
    report = asking_price_diagnostics(rows)
    assert report["status"] == "ASKING_CONTEXT_ONLY"
    assert 49 <= float(report["asking_price_median_gbp"]) <= 53
    assert report["market_value_gbp"] is None
    assert report["market_value_eligible"] is False
    assert report["verified_sold_count"] == 0
    assert report["accepted_listing_count"] == 5
    assert [x["asking_price_gbp"] for x in report["outliers"]] == ["700.00"]


def test_insufficient_and_unverified_asks_never_become_market_values():
    rows = [
        comparable(45, "1", "a"),
        comparable(50, "2", "b"),
        comparable(700, "3", "c"),
        comparable(50, "4", "d", match_status="REVIEW_REQUIRED"),
        comparable(60, "5", "e", observation_type="SOLD"),
    ]
    report = asking_price_diagnostics(rows)
    assert report["status"] == "INSUFFICIENT_EXACT_ASKS"
    assert report["asking_price_median_gbp"] is None
    assert report["market_value_gbp"] is None
    assert report["rejected_input_count"] == 2


def test_one_seller_cannot_create_fake_independent_market_context():
    rows = [comparable(p, str(i), "same") for i, p in enumerate([45, 48, 50, 51, 52, 53])]
    report = asking_price_diagnostics(rows)
    assert report["status"] == "INSUFFICIENT_EXACT_ASKS"
    assert report["source_seller_count"] == 1


def test_duplicate_item_id_with_conflicting_price_is_quarantined():
    rows = [comparable(p, str(i), f"s{i}") for i, p in enumerate([45, 48, 50, 52, 55, 60])]
    rows.append(comparable(1000, "0", "different_seller"))
    report = asking_price_diagnostics(rows)
    assert report["source_listing_count"] == 5
    assert report["rejected_input_count"] == 1
    assert report["market_value_gbp"] is None


def test_missing_currency_or_unknown_marketplace_is_not_accepted():
    rows = [comparable(p, str(i), f"s{i}") for i, p in enumerate([45, 48, 50, 52, 55])]
    rows[0]["currency"] = "USD"
    rows[1]["source"] = "UNKNOWN"
    report = asking_price_diagnostics(rows)
    assert report["status"] == "INSUFFICIENT_EXACT_ASKS"


def test_pokemon_secret_illustration_rarity_is_not_ordinary_illustration():
    result = evaluate_treatment(game="Pokémon", requested_name="Charizard",
        requested_variant="Special Illustration Rare", requested_rarity="SAR",
        listing_title="Pokemon Charizard SIR 223/197")
    assert result.status == "NO_TREATMENT_CONFLICT"
    assert "SPECIAL_ILLUSTRATION_RARE" in result.target
    assert "ILLUSTRATION_RARE" not in result.target
    mismatch = evaluate_treatment(game="Pokémon", requested_name="Charizard",
        requested_variant="Normal", requested_rarity="Common",
        listing_title="Charizard 223/197 Special Illustration Rare")
    assert mismatch.status == "REJECTED"


def test_one_piece_manga_and_parallel_cannot_be_flattened_into_base_card():
    no = evaluate_treatment(game="One Piece", requested_name="Luffy",
        requested_variant="Base", requested_rarity="SEC",
        listing_title="One Piece Monkey D Luffy Manga Rare OP05-119")
    assert no.status == "REJECTED"
    yes = evaluate_treatment(game="One Piece", requested_name="Luffy (Manga)",
        requested_variant="Manga Rare", requested_rarity="SEC",
        listing_title="One Piece Luffy OP05-119 Manga Rare")
    assert yes.status == "REVIEW_REQUIRED"  # Seller omits SEC; manga identity alone does not prove rarity.
    assert "SECRET_RARE" in yes.missing_evidence


def test_secret_rare_abbreviation_is_game_scoped():
    assert "SECRET_RARE" in treatment_signals("One Piece", "SEC")
    assert "SECRET_RARE" not in treatment_signals("Pokemon", "SEC")
    assert "SPECIAL_RARE" in treatment_signals("Dragon Ball Fusion World", "SPR")


def test_yugioh_qcr_is_not_regular_secret_rare():
    result = evaluate_treatment(game="Yu-Gi-Oh!", requested_name="Blue-Eyes",
        requested_variant="Secret Rare", requested_rarity=None,
        listing_title="Blue Eyes Quarter Century Secret Rare")
    assert result.status == "REJECTED"
    assert "QUARTER_CENTURY_SECRET" in result.conflicts


def test_lorcana_mtg_and_other_foil_treatments_kept_separate():
    assert "ENCHANTED" in treatment_signals("Disney Lorcana", "Enchanted")
    assert "ETCHED_FOIL" in treatment_signals("MTG", "Etched Foil")
    assert "BORDERLESS" in treatment_signals("Magic", "Borderless")
    assert "ALT_ART" in treatment_signals("One Piece", "Alternate Art")


def test_sealed_pack_box_case_and_repack_distinguished():
    assert sealed_product_type("Factory sealed booster box") == {"BOOSTER_BOX"}
    assert verify_sealed_product(expected_type="BOOSTER_PACK", title="Factory sealed booster box") == "REJECTED_WRONG_SEALED_TYPE"
    assert verify_sealed_product(expected_type="BOOSTER_BOX", title="Factory sealed booster box") == "POTENTIAL_MATCH_REQUIRES_IDENTITY_REVIEW"
    assert verify_sealed_product(expected_type="BOOSTER_BOX", title="Empty booster box only") == "REJECTED_UNSAFE_SEAL"
    assert verify_sealed_product(expected_type="CASE", title="Sealed booster pack") == "REJECTED_WRONG_SEALED_TYPE"
    assert verify_sealed_product(expected_type="BOOSTER_BOX", title="Booster box") == "REVIEW_SEAL_NOT_VERIFIED"


def test_50_day_plan_requires_under_three_calls_with_reserved_quota():
    plan = plan_daily_batch(remaining=73760, actual_daily_limit=5000,
        used_today=0, reserved_for_app=1000, measured_calls_per_item=3.0)
    assert plan.target_items_per_day == 1476
    assert plan.calls_per_item_needed_for_target < 3
    assert plan.estimated_daily_item_capacity == 1333
    assert plan.fifty_day_target_feasible is False
    assert plan.estimated_days_at_current_rate == 56


def test_50_day_plan_possible_with_measured_2_point_5_calls():
    plan = plan_daily_batch(remaining=73760, actual_daily_limit=5000,
        used_today=0, reserved_for_app=1000, measured_calls_per_item=2.5)
    assert plan.estimated_daily_item_capacity == 1600
    assert plan.scheduled_items == 1476
    assert plan.fifty_day_target_feasible is True


def test_budget_is_clamped_and_safely_exhausts():
    plan = plan_daily_batch(remaining=300, actual_daily_limit=5000,
        used_today=4800, reserved_for_app=500, measured_calls_per_item=2.0)
    assert plan.available_browse_calls == 0
    assert plan.scheduled_items == 0
    assert plan.state == "NO_AVAILABLE_QUOTA"


def test_prioritise_unpriced_then_oldest_and_deduplicate_physical_copies():
    items = [
        dict(pricing_identity="x", market_value_minor=100, last_checked_at="2026-11-11"),
        dict(pricing_identity="y", market_value_minor=None, last_checked_at="2026-11-10"),
        dict(pricing_identity="x", market_value_minor=None, last_checked_at=None),
        dict(pricing_identity="z", market_value_minor=None, review_status="IDENTITY_CONFLICT"),
        dict(pricing_identity="w", market_value_minor=100, last_checked_at="2026-01-01"),
    ]
    selected = prioritize_refresh_items(items, limit=2)
    assert [v["pricing_identity"] for v in selected] == ["x", "y"]
    assert selected[0]["market_value_minor"] is None


def test_comics_issue_variant_and_grade_cannot_cross_identify():
    from app.market_comparable_safety import review_noncard_identity
    requested = {"issue_number": "300", "variant": "Cover A", "printing": "First", "grading_company": "CGC", "grade": "9.8"}
    assert review_noncard_identity("comic", requested, "Amazing Spider-Man #301 CGC 9.8 Cover A").status == "REJECTED"
    assert review_noncard_identity("comic", requested, "Amazing Spider-Man #300 CGC 9.6 Cover A").status == "REJECTED"
    assert review_noncard_identity("comic", requested, "Amazing Spider-Man #300 CGC 9.8 Cover B").status == "REJECTED"
    assert review_noncard_identity("comic", requested, "Amazing Spider-Man #300 CGC 9.8 Facsimile").status == "REJECTED"


def test_manga_individual_volume_is_not_other_volume_or_omnibus():
    from app.market_comparable_safety import review_noncard_identity
    requested = {"volume": "12"}
    assert review_noncard_identity("manga", requested, "Naruto Vol 13 Paperback").status == "REJECTED"
    assert review_noncard_identity("manga", requested, "Naruto Vol 12 Omnibus").status == "REJECTED"
    assert review_noncard_identity("manga", requested, "Naruto Vol 12 Paperback").status == "REVIEW_REQUIRED"


def test_funko_chase_exclusive_box_damage_and_product_numbers():
    from app.market_comparable_safety import review_noncard_identity
    base = {"product_number": "98", "variant": "Common", "box_condition": "Mint", "product_type": "Pop"}
    assert review_noncard_identity("funko", base, "Funko Pop Luffy #99").status == "REJECTED"
    assert review_noncard_identity("funko", base, "Funko Pop Luffy #98 Chase").status == "REJECTED"
    assert review_noncard_identity("funko", base, "Funko Pop Luffy #98 Damaged Box").status == "REJECTED"
    assert review_noncard_identity("funko", base, "Funko Soda Luffy #98").status == "REJECTED"
    assert review_noncard_identity("funko", base, "Funko Pop Luffy #98").status == "REVIEW_REQUIRED"


def test_unknown_sealed_product_type_must_never_confirm_identity():
    from app.market_comparable_safety import review_noncard_identity
    actual = review_noncard_identity("sealed", {"product_type": "BOOSTER_CASE"}, "Factory sealed booster case")
    assert actual.status == "REVIEW_REQUIRED"
    assert "REVIEW_UNKNOWN_SEALED_TYPE" in actual.missing
