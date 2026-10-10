"""Deterministic, source-bound artwork for catalogue SET tiles only.

The checked-in registry mirrors the current title-art navigation lookup.
No network access, database writes, card-image fallback or media approvals.
An unknown or invalid source fails closed to the verified game mark.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

REGISTRY_PATH = Path(__file__).resolve().parent / "static" / "title-art" / "set-artwork-registry.json"
LOCAL_IMAGE = re.compile(r"^[a-z0-9][a-z0-9-]*\.(?:png|jpg|jpeg|webp|svg)$")
TCGDEX_LOGO = re.compile(r"^/en/[A-Za-z0-9_+./%-]+/logo\.webp$")
ART_TYPES = frozenset({"SET_LOGO", "GAME_LOGO", "BRANDED_FALLBACK"})


def _norm(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in decomposed
                   if unicodedata.category(character) != "Mn" and character.isalnum())


def _file(name: object) -> str | None:
    value = str(name or "")
    if not LOCAL_IMAGE.fullmatch(value):
        return None
    if not (REGISTRY_PATH.parent / value).is_file():
        return None
    return value


def _provider_logo(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "assets.tcgdex.net"
            or parsed.query or parsed.fragment or not TCGDEX_LOGO.fullmatch(parsed.path)):
        return None
    return url


@lru_cache(maxsize=1)
def _registry() -> dict:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("games"), dict):
        raise ValueError("Set artwork registry format is invalid")
    if not isinstance(data.get("bundled_sets"), list) or not isinstance(data.get("provider_sets"), dict):
        raise ValueError("Set artwork registry entries are invalid")
    return data


def _exact_logo(row: Mapping[str, Any], data: dict) -> dict[str, Any] | None:
    system = str(row.get("system_code") or "")
    language = str(row.get("language") or "")
    name = str(row.get("set_name") or row.get("name") or "")
    set_id = str(row.get("set_id") or "")
    provider = str(row.get("provider") or "")
    options = []
    for entry in data["bundled_sets"]:
        if entry.get("system") != system or entry.get("language") != language:
            continue
        same_name = any(_norm(n) == _norm(name) for n in entry.get("names", []) if name)
        same_code = set_id and set_id in entry.get("codes", [])
        same_provider_id = set_id and set_id in entry.get("provider_ids", {}).get(provider, [])
        if same_name or same_code or same_provider_id:
            options.append(entry)
    # An ambiguous source identity is never resolved by picking the first match.
    if len(options) == 1:
        file_name = _file(options[0].get("file"))
        if file_name is not None:
            return {
                "type": "SET_LOGO", "status": "SOURCE_INDEXED", "source": "BUNDLED_PUBLISHER",
                "file": file_name, "title": str(options[0].get("title") or name),
            }
    elif len(options) > 1:
        return None

    # Provider IDs are exact and only meaningful for their own game/language.
    if system == "POKEMON_TCG" and provider == "TCGdex":
        candidate = data["provider_sets"].get("TCGdex", {}).get(language, {}).get(set_id)
        if isinstance(candidate, dict):
            url = _provider_logo(candidate.get("url"))
            if url is not None:
                return {
                    "type": "SET_LOGO", "status": "SOURCE_INDEXED", "source": "TCGDEX",
                    "url": url, "title": str(candidate.get("title") or name),
                }
    return None


def resolve_set_artwork(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a typed navigation image, never a product, pack or individual card."""
    data = _registry()
    exact = _exact_logo(row, data)
    if exact is not None:
        return exact
    system = str(row.get("system_code") or "")
    game = data["games"].get(system)
    if isinstance(game, dict):
        game_file = _file(game.get("file"))
        if game_file is not None:
            return {
                "type": "GAME_LOGO", "status": "SET_LOGO_MISSING", "source": "OFFICIAL_GAME_MARK",
                "file": game_file, "title": str(row.get("set_name") or row.get("name") or ""),
            }
    return {
        "type": "BRANDED_FALLBACK", "status": "SET_LOGO_MISSING",
        "source": "DROP_RATE_FALLBACK", "title": str(row.get("set_name") or row.get("name") or ""),
    }


def artwork_coverage(rows: list[Mapping[str, Any]], *, missing_limit: int = 40) -> dict:
    """Audit whole read-only set population (provider records, not distinct sets)."""
    groups: dict[tuple[str, str, str], dict] = {}
    missing: list[dict] = []
    indexed = 0
    for row in rows:
        system, language, provider = (str(row.get(k) or "") for k in ("system_code", "language", "provider"))
        key = (system, language, provider)
        group = groups.setdefault(key, {
            "system_code": system, "language": language, "provider": provider,
            "total": 0, "set_logos": 0, "game_fallbacks": 0, "branded_fallbacks": 0,
        })
        group["total"] += 1
        art = resolve_set_artwork(row)
        if art["type"] == "SET_LOGO":
            indexed += 1
            group["set_logos"] += 1
        else:
            if art["type"] == "GAME_LOGO":
                group["game_fallbacks"] += 1
            else:
                group["branded_fallbacks"] += 1
            missing.append({
                "system_code": system, "language": language, "provider": provider,
                "set_id": str(row.get("set_id") or ""),
                "set_name": str(row.get("set_name") or row.get("name") or ""),
                "release_date": str(row.get("release_date") or "") or None,
                "status": art["status"], "fallback": art["type"],
            })
    return {
        "scope": "SET_REFERENCE_RECORDS_NOT_DISTINCT_RELEASES",
        "total": len(rows),
        "indexed_set_logos": indexed,
        "missing_set_logos": len(rows) - indexed,
        "coverage": round(indexed / len(rows), 4) if rows else 0,
        "groups": sorted(groups.values(), key=lambda r: (r["system_code"], r["language"], r["provider"])),
        "missing": missing[:missing_limit],
        "missing_returned": min(len(missing), missing_limit),
        "manual_review": _registry().get("pending_review", []),
    }
