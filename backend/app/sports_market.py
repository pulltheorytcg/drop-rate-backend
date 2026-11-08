"""Sports-specific printing boundaries; no scarcity premium is inferred."""
import re

from .ebay_uk_parse_adapter import _contains_term, _normalise_text


def sports_printing_matches(title, target):
    text = _normalise_text(title)
    set_name = _normalise_text(target.get("set_name"))
    if not set_name or f" {set_name} " not in f" {text} ":
        return False
    variant = str(target.get("variant") or "")
    if not variant.strip():
        return False
    # The catalogue variant records edition scarcity (/10), not this copy's
    # serial numerator. A PSA 10 token cannot prove a /10 print run.
    expected_runs = re.findall(r"/\s*(\d+)\b", variant)
    observed_runs = re.findall(r"/\s*(\d+)\b", str(title))
    if expected_runs:
        if len(expected_runs) != 1 or not 0 < int(expected_runs[0]) <= 1_000_000:
            return False
        if not observed_runs or any(int(n) != int(expected_runs[0]) for n in observed_runs):
            return False
    elif observed_runs:
        return False
    identity = _normalise_text(" ".join(str(target.get(k) or "") for k in ("name", "variant")))
    for markers in (("signed", "signature", "autograph", "autographed", "auto"),
                    ("patch", "relic", "memorabilia"), ("rookie", "rc")):
        expected = any(_contains_term(identity, marker) for marker in markers)
        observed = any(_contains_term(text, marker) for marker in markers)
        if expected != observed:
            return False
    return True
