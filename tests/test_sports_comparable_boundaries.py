"""Fixture-only regression evidence for sports printing identity."""
import pytest
from app.ebay_sold_pricing import _matches_comp
from app.live_market_refresh import exact_card_match


def target(**changes):
    return dict(dict(game="Sports Cards", name="Fixture Player", set_name="2024 Topps Chrome",
                     card_number="123", variant="Gold · /10", condition=None,
                     grading_company="PSA", grade="10", language="English", rarity=""), **changes)


def row(title):
    return dict(title=title, condition_raw="Near Mint")


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
def test_exact_numbered_sports_parallel_can_match(matcher):
    assert matcher(row("Fixture Player 123 2024 Topps Chrome Gold 03/10 English PSA 10"), target())


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
@pytest.mark.parametrize("title", [
    "Fixture Player 123 2024 Topps Chrome Gold English PSA 10",
    "Fixture Player 123 2024 Topps Chrome Gold /99 English PSA 10",
    "Fixture Player 123 2024 Topps Chrome Base English PSA 10",
    "Fixture Player 123 2023 Topps Chrome Gold /10 English PSA 10",
    "Fixture Player 123 2024 Panini Prizm Gold /10 English PSA 10",
    "Fixture Player 123 2024 Topps Chrome Gold /10 or /99 English PSA 10",
    "Fixture Player 123 2024 Topps Chrome Gold /10 autograph English PSA 10",
    "Fixture Player 123 2024 Topps Chrome Gold /10 patch English PSA 10",
    "Fixture Player 123 2024 Topps Chrome Gold /10 relic English PSA 10",
    "Fixture Player 123 2024 Topps Chrome Gold /10 rookie English PSA 10",
])
def test_base_or_other_sports_editions_are_not_numbered_comparables(matcher, title):
    assert not matcher(row(title), target())


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
def test_unnumbered_base_cannot_borrow_a_numbered_copy(matcher):
    t = target(variant="Base")
    assert matcher(row("Fixture Player 123 2024 Topps Chrome Base English PSA 10"), t)
    assert not matcher(row("Fixture Player 123 2024 Topps Chrome Base /10 English PSA 10"), t)
