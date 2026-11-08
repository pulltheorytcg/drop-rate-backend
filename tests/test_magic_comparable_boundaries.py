"""Deterministic fixture checks, not live prices or provider permission proof."""
import pytest

from app.ebay_sold_pricing import _matches_comp
from app.live_market_refresh import exact_card_match


def target(finish="foil"):
    return dict(game="Magic: The Gathering", name="Fixture Mage", set_name="Fixture Expansion",
                card_number="123", variant=finish, language="English", condition="Near Mint",
                grading_company=None, grade=None, rarity="Rare")


def row(finish="foil", expansion="Fixture Expansion"):
    return dict(title=f"Fixture Mage 123 {expansion} English {finish} NM", condition_raw="Near Mint")


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
@pytest.mark.parametrize("expected", ["foil", "etched", "nonfoil"])
@pytest.mark.parametrize("observed", ["foil", "etched", "nonfoil"])
def test_magic_finishes_do_not_mix(matcher, expected, observed):
    assert matcher(row(observed), target(expected)) is (expected == observed)


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
@pytest.mark.parametrize("observed", ["etched foil", "foil etched", "foil nonfoil", "foil or non-foil",
                                     "textured foil", "surge foil", "gilded foil"])
def test_plain_foil_cannot_borrow_special_or_ambiguous_finish(matcher, observed):
    assert not matcher(row(observed), target())


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
@pytest.mark.parametrize("finish", ["foil", "etched", "nonfoil"])
def test_same_name_and_number_in_another_printing_is_not_a_comparable(matcher, finish):
    assert not matcher(row(finish, "Different Expansion"), target(finish))
    assert not matcher(row(finish, ""), target(finish))


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
def test_nonfoil_spelling_and_etched_aliases(matcher):
    assert matcher(row("non-foil"), target("nonfoil"))
    assert matcher(row("non foil"), target("nonfoil"))
    assert matcher(row("foil etched"), target("etched"))
    assert matcher(row("etched foil"), target("etched"))


@pytest.mark.parametrize("matcher", [_matches_comp, exact_card_match])
def test_signed_and_unsigned_magic_do_not_mix(matcher):
    assert not matcher(row("foil signed"), target())
    assert not matcher(row("foil artist autograph"), target())
