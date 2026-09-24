from __future__ import annotations

import re


_LANGUAGE_ALIASES = {
    "en": "English",
    "eng": "English",
    "english": "English",
    "jp": "Japanese",
    "jpn": "Japanese",
    "japanese": "Japanese",
}

_LANGUAGE_CODES = {
    "English": "EN",
    "Japanese": "JP",
}

_TITLE_LANGUAGE_RE = re.compile(
    r"""(?ix)
    ^(?P<base>.*?)
    (?:
        \s*\((?P<p1>EN|ENG|ENGLISH|JP|JPN|JAPANESE)\)
      | \s*\[(?P<p2>EN|ENG|ENGLISH|JP|JPN|JAPANESE)\]
      | \s*[-·|/]\s*(?P<p3>EN|ENG|ENGLISH|JP|JPN|JAPANESE)
      | \s+(?P<p4>EN|ENG|ENGLISH|JP|JPN|JAPANESE)
    )
    \s*$
    """
)


def clean_language(value: object) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    return _LANGUAGE_ALIASES.get(text.casefold(), text)


def language_code(value: object) -> str | None:
    canonical = clean_language(value)
    if not canonical:
        return None
    return _LANGUAGE_CODES.get(canonical, canonical.upper() if len(canonical) <= 4 else canonical)


def parse_title_language(title: object) -> tuple[str, str | None]:
    text = " ".join(str(title or "").strip().split())
    if not text:
        return "", None
    match = _TITLE_LANGUAGE_RE.match(text)
    if not match:
        return text, None
    raw = next((match.group(key) for key in ("p1", "p2", "p3", "p4") if match.group(key)), None)
    return match.group("base").strip(), clean_language(raw)


def display_title(name: object, language: object) -> str:
    base, title_language = parse_title_language(name)
    canonical_language = clean_language(language) or title_language
    code = language_code(canonical_language)
    if not base:
        return code or ""
    return f"{base} · {code}" if code else base
