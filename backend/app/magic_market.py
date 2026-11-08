"""Magic-specific comparable boundaries for the existing sold-price routes.

This is identity validation, not a price estimator or source permission grant.
Unknown or ambiguous finishes remain unmatched; signed copies need a separate
authenticated-signature strategy before they can enter an ordinary price pool.
"""
import re

from .ebay_uk_parse_adapter import _contains_term, _normalise_text


def is_magic(game):
    return _normalise_text(game) == "magic the gathering"


def _without_name(title, name):
    text = _normalise_text(title)
    name = _normalise_text(name)
    return (f" {text} ".replace(f" {name} ", " ", 1).strip()
            if name else text)


def finish_matches(title, variant, *, name=None):
    expected = _normalise_text(variant)
    expected = {"non foil": "nonfoil", "foil etched": "etched",
                "etched foil": "etched"}.get(expected, expected)
    if expected not in {"foil", "nonfoil", "etched"}:
        return False
    text = _without_name(title, name)
    # These treatments are not ordinary foil, even when the title says foil.
    if any(_contains_term(text, marker) for marker in (
            "textured", "surge", "gilded", "galaxy", "ripple", "confetti",
            "fracture", "mana foil", "halo foil", "raised foil", "serialized")):
        return False
    kinds = set()
    if re.search(r"\bnon\s*foil\b", text):
        kinds.add("nonfoil")
        text = re.sub(r"\bnon\s*foil\b", " ", text)
    if re.search(r"\b(?:foil\s+etched|etched(?:\s+foil)?)\b", text):
        kinds.add("etched")
        text = re.sub(r"\b(?:foil\s+etched|etched(?:\s+foil)?)\b", " ", text)
    if _contains_term(text, "foil"):
        kinds.add("foil")
    return kinds == {expected}


def printing_matches(title, target):
    text = _normalise_text(title)
    set_name = _normalise_text(target.get("set_name"))
    # Do not borrow a token from the card name to complete a different set.
    if not set_name or f" {set_name} " not in f" {text} ":
        return False
    text = _without_name(title, target.get("name"))
    if re.search(r"\b(?:signed|signature|autograph|autographed|altered)\b", text):
        return False
    # A different art/frame treatment is not rescued by a matching set/number.
    identity = _normalise_text(" ".join(str(target.get(k) or "")
                                       for k in ("name", "variant")))
    for marker in ("borderless", "showcase", "extended art", "retro frame", "old border"):
        if _contains_term(text, marker) != _contains_term(identity, marker):
            return False
    return finish_matches(title, target.get("variant"), name=target.get("name"))
