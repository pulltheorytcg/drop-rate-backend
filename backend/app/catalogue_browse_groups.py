"""Reviewed display facets; never canonical identity or physical-stock approval.

The SQL and disposable R2 search index use the same exact reviewed values.
See docs/CATALOGUE_BROWSE_GROUPS_20261104.md for evidence and unknown handling.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping

BROWSE_GROUPS = {
    "COMICS": ("MARVEL", "DC", "INDIE", "OTHER"),
    "MANGA": ("SHONEN", "SHOJO", "SEINEN", "JOSEI", "KODOMO", "UNKNOWN"),
    "SPORTS": ("PANINI", "TOPPS", "OTHER"),
    "FIGURES": ("FUNKO_POP", "FIGURINES", "OTHER"),
}
SYSTEM_CATEGORIES = {
    "COMICS": "COMICS", "MARVEL_COMICS": "COMICS", "DC_COMICS": "COMICS",
    "OTHER_COMICS": "COMICS", "MANGA": "MANGA",
    "SPORTS_CARDS": "SPORTS", "FIGURES": "FIGURES",
}

# This is a shop-browsing publisher grouping, not a claim about corporate
# independence or the ownership of a character/licence. Unknown is not Indie.
INDIE_PUBLISHERS = frozenset({
    "image comics", "image", "dark horse comics", "dark horse",
    "idw publishing", "idw",
})

# Exact reviewed series only. Publisher, age rating, genre, or a title containing
# "Shonen" cannot establish a demographic. New aliases need source review.
# Original Japanese serialization demographic, not English imprint or genre.
# Each exact series/edition alias below has publication evidence in
# docs/MANGA_DEMOGRAPHIC_REVIEW_20261104.md. Unknowns stay UNKNOWN.
MANGA_DEMOGRAPHICS = {
    # Previously reviewed exact-series rules.
    "one piece": "SHONEN", "naruto": "SHONEN", "dragon ball z": "SHONEN",
    "hunter x hunter": "SHONEN", "jujutsu kaisen": "SHONEN",
    "death note": "SHONEN", "baby & me": "SHOJO",
    "initial d": "SEINEN", "initial d omnibus": "SEINEN",
    "princess jellyfish": "JOSEI",

    # Reviewed Japanese shōnen magazine publication.
    "rave master": "SHONEN",
    "rave master (rave master (graphic novels))": "SHONEN",
    "steel angel kurumi": "SHONEN", "suzuka": "SHONEN",
    "iron wok jan": "SHONEN", "a.i. love you": "SHONEN",
    "flame of recca": "SHONEN", "school rumble": "SHONEN",
    "sgt. frog": "SHONEN", "the law of ueki": "SHONEN",
    "yakitate!! japan": "SHONEN", "zatch bell!": "SHONEN",
    "shaman king": "SHONEN", "gin tama": "SHONEN",
    "slam dunk": "SHONEN", "d.gray-man": "SHONEN",
    "getbackers": "SHONEN", "case closed": "SHONEN",
    "hayate the combat butler": "SHONEN",
    "the prince of tennis": "SHONEN",

    # Reviewed Japanese seinen magazine publication.
    "lupin iii": "SEINEN", "battle royale": "SEINEN",
    "chobits": "SEINEN", "es: eternal sabbath (es: eternal sabbath)": "SEINEN",
    "oh my goddess!": "SEINEN", "emma": "SEINEN",
    "vagabond vizbig edition": "SEINEN", "vagabond": "SEINEN",
    "mushishi": "SEINEN",

    # Reviewed Japanese shōjo magazine publication.
    "land of the blindfolded -": "SHOJO", "vampire game": "SHOJO",
    "dragon knights": "SHOJO", "from eroica with love -": "SHOJO",
    "gals! (super gals)": "SHOJO",
    "fruits basket ultimate edition": "SHOJO", "fruits basket": "SHOJO",
    "s.a": "SHOJO",
    "wild act (wild act (graphic novels))": "SHOJO",
    "wild act": "SHOJO",

    # Reviewed Japanese josei magazine publication.
    "happy mania": "JOSEI", "suppli": "JOSEI",
    "with the light: raising an autistic child": "JOSEI",
}

SPORTS_MANUFACTURERS = {"panini": "PANINI", "panini america": "PANINI", "topps": "TOPPS"}
FIGURE_LINES = {
    "funko": {"pop!": "FUNKO_POP", "pop": "FUNKO_POP"},
    "good smile company": {"nendoroid": "FIGURINES"},
}


def _normal(value) -> str:
    # Match PostgreSQL btrim/lower exactly for the reviewed ASCII facts. Do not
    # collapse punctuation, prefixes, transliterations, or unreviewed aliases.
    return value.strip(" ").lower() if isinstance(value, str) and value.isascii() else ""


def validate_browse_group(value: str, *, category: str = "", system_code: str = "") -> str:
    """Require a closed group and unambiguous matching category/system context."""
    if not isinstance(value, str):
        raise ValueError("Invalid catalogue browse group")
    if not value:
        return ""
    system_category = SYSTEM_CATEGORIES.get(system_code)
    if system_code and not system_category:
        raise ValueError("This system does not support catalogue browse groups")
    if category and category not in BROWSE_GROUPS:
        raise ValueError("This category does not support catalogue browse groups")
    if category and system_category and category != system_category:
        raise ValueError("Catalogue category and system do not match")
    selected = category or system_category
    if not selected or value not in BROWSE_GROUPS[selected]:
        raise ValueError("Browse group requires a matching category or system")
    allowed_system_groups = {
        "MARVEL_COMICS": ("MARVEL",), "DC_COMICS": ("DC",),
        "OTHER_COMICS": ("INDIE", "OTHER"),
    }
    if system_code in allowed_system_groups and value not in allowed_system_groups[system_code]:
        raise ValueError("Browse group does not match the selected comic system")
    return value


def group_for(system_code: str, facts: Mapping | None = None) -> str:
    """Derive a display group from allowlisted facts; do not mutate the row."""
    facts = facts if isinstance(facts, Mapping) else {}
    if system_code == "MARVEL_COMICS":
        return "MARVEL"
    if system_code == "DC_COMICS":
        return "DC"
    if system_code in {"OTHER_COMICS", "COMICS"}:
        return "INDIE" if _normal(facts.get("publisher")) in INDIE_PUBLISHERS else "OTHER"
    if system_code == "MANGA":
        return MANGA_DEMOGRAPHICS.get(_normal(facts.get("series_title")), "UNKNOWN")
    if system_code == "SPORTS_CARDS":
        return SPORTS_MANUFACTURERS.get(_normal(facts.get("manufacturer")), "OTHER")
    if system_code == "FIGURES":
        return FIGURE_LINES.get(_normal(facts.get("manufacturer")), {}).get(
            _normal(facts.get("product_line")), "OTHER")
    return ""


def group_predicate(group: str, bind: Callable, entry_alias: str = "e") -> str:
    """Bound SQL facet over approved canonical facts, applied before pagination.

    Callers first validate category/system context. The predicate itself also
    rejects non-enumerated groups and never interpolates request input.
    """
    if group not in {value for values in BROWSE_GROUPS.values() for value in values}:
        raise ValueError("Unknown catalogue browse group")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", entry_alias):
        raise ValueError("Invalid SQL entry alias")
    indie = bind(sorted(INDIE_PUBLISHERS))
    manga = bind(json.dumps(MANGA_DEMOGRAPHICS, sort_keys=True))
    sports = bind(json.dumps(SPORTS_MANUFACTURERS, sort_keys=True))
    figures = bind(json.dumps(FIGURE_LINES, sort_keys=True))
    wanted = bind(group)

    def json_text(expression: str) -> str:
        text = f"({expression} #>> '{{}}')"
        return (f"case when jsonb_typeof({expression})='string' "
                f"and octet_length({text})=length({text}) "
                f"then lower(btrim({text})) else '' end")

    publisher = json_text("browse_book.attributes->'publisher'")
    maker = json_text("browse_profile.attributes->'sports_card'->'manufacturer'")
    figure_maker = json_text("browse_profile.attributes->'figure_details'->'manufacturer'")
    figure_line = json_text("browse_profile.attributes->'figure_details'->'product_line'")
    series = ("case when octet_length(browse_book.series_title)=length(browse_book.series_title) "
              "then lower(btrim(browse_book.series_title)) else '' end")
    return f"""exists (
      select 1 from tcg.catalogue_product_profiles browse_profile
      left join tcg.comic_printing_details browse_book
        on browse_book.catalogue_id=browse_profile.catalogue_id
        and browse_book.system_code=browse_profile.system_code
        and browse_profile.collectible_type='COMIC'
      where browse_profile.catalogue_id={entry_alias}.catalogue_id
        and browse_profile.system_code={entry_alias}.system_code
        and (case browse_profile.system_code
          when 'MARVEL_COMICS' then 'MARVEL'
          when 'DC_COMICS' then 'DC'
          when 'OTHER_COMICS' then case when ({publisher})=any({indie}::text[])
            then 'INDIE' else 'OTHER' end
          when 'MANGA' then coalesce({manga}::jsonb->>({series}), 'UNKNOWN')
          when 'SPORTS_CARDS' then coalesce({sports}::jsonb->>({maker}), 'OTHER')
          when 'FIGURES' then coalesce({figures}::jsonb->({figure_maker})->>({figure_line}), 'OTHER')
          else '' end)={wanted}::text
    )"""
