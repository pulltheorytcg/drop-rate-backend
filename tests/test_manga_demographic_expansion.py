"""Reviewed magazine-demographic expansion; exact series keys only.

No canonical identities, physical stock, prices, artwork or owner state change.
The indexed PostgreSQL predicate and Python display use the same dictionary.
"""
import json

import pytest

from app.catalogue_browse_groups import MANGA_DEMOGRAPHICS, group_for, group_predicate


REVIEWED_ADDITIONS = {
    "SHONEN": (
        "Rave Master", "Rave Master (Rave Master (Graphic Novels))",
        "Steel Angel Kurumi", "Suzuka", "Iron Wok Jan", "A.I. Love You",
        "Flame of Recca", "School Rumble", "Sgt. Frog", "The Law of Ueki",
        "Yakitate!! Japan", "Zatch Bell!", "Shaman King", "Gin Tama",
        "Slam Dunk", "D.Gray-man", "GetBackers", "Case Closed",
        "Hayate The Combat Butler", "The Prince of Tennis",
    ),
    "SEINEN": (
        "Lupin III", "Battle Royale", "Chobits",
        "ES: Eternal Sabbath (ES: Eternal Sabbath)", "Oh My Goddess!",
        "Emma", "Vagabond VIZBIG Edition", "Vagabond", "Mushishi",
    ),
    "SHOJO": (
        "Land of the Blindfolded -", "Vampire Game", "Dragon Knights",
        "From Eroica with Love -", "Gals! (Super Gals)",
        "Fruits Basket Ultimate Edition", "Fruits Basket", "S.A",
        "Wild Act (Wild Act (Graphic Novels))", "Wild Act",
    ),
    "JOSEI": (
        "Happy Mania", "Suppli", "With the Light: Raising an Autistic Child",
    ),
}


@pytest.mark.parametrize(
    "series,expected",
    [(name, group) for group, names in REVIEWED_ADDITIONS.items() for name in names],
)
def test_reviewed_series_demographic_is_exact_and_casefolded(series, expected):
    assert group_for("MANGA", {"series_title": series}) == expected
    assert group_for("MANGA", {"series_title": f" {series.upper()} "}) == expected
    assert MANGA_DEMOGRAPHICS[series.lower()] == expected


def test_all_42_new_keys_are_unique_and_prior_review_is_preserved():
    added = [name.lower() for values in REVIEWED_ADDITIONS.values() for name in values]
    assert len(added) == len(set(added)) == 42
    expected_prior = {
        "one piece": "SHONEN", "naruto": "SHONEN", "dragon ball z": "SHONEN",
        "hunter x hunter": "SHONEN", "jujutsu kaisen": "SHONEN",
        "death note": "SHONEN", "baby & me": "SHOJO",
        "initial d": "SEINEN", "initial d omnibus": "SEINEN",
        "princess jellyfish": "JOSEI",
    }
    assert {k: MANGA_DEMOGRAPHICS[k] for k in expected_prior} == expected_prior
    assert len(MANGA_DEMOGRAPHICS) == 52


@pytest.mark.parametrize("unreviewed", (
    "Priest", "Faeries' Landing", "Chronicles of the Cursed Sword",
    "Rave Master spin-off", "Sgt. Frog: fan edition",
    "Manga called Shonen", "Gals (unreviewed alternate title)",
    "Vagabond artbook", "Case Closed TV guide", "", None, 123,
))
def test_ambiguous_adaptations_and_manhwa_are_not_autoclassified(unreviewed):
    assert group_for("MANGA", {"series_title": unreviewed}) == "UNKNOWN"


def test_sql_predicate_binds_exact_same_reviewed_map_not_inline_user_values():
    bound = []
    def bind(value):
        bound.append(value)
        return f"${len(bound)}"
    predicate = group_predicate("SHOJO", bind)
    assert "browse_book.series_title" in predicate
    assert "$2::jsonb" in predicate
    assert "$5::text" in predicate
    assert bound[4] == "SHOJO"
    assert json.loads(bound[1]) == MANGA_DEMOGRAPHICS
    assert "getbackers" in json.loads(bound[1])
    assert "random child manga" not in json.loads(bound[1])
