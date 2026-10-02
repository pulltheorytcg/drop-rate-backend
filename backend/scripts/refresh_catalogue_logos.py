"""Refresh navigation logos from the existing TCGdex set indexes.

Only reads two public indexes and updates the checked-in title lookup/provenance.
It does not import cards, change inventory, or approve product media.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
START = "  // BEGIN TCGDEX SET LOGOS\n"
END = "  // END TCGDEX SET LOGOS\n"


def refresh():
    index = {}
    sources = []
    for code, language in (("en", "English"), ("ja", "Japanese")):
        url = f"https://api.tcgdex.net/v2/{code}/sets"
        with urlopen(url, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Set index exceeds expected size")
        rows = json.loads(raw)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise ValueError("Invalid set index")
        index[language] = {}
        for row in rows:
            logo = row.get("logo")
            if not logo:
                continue
            if not re.fullmatch(r"https://assets\.tcgdex\.net/[A-Za-z0-9_+./%-]+/logo", logo):
                raise ValueError("Unexpected set-logo origin or path")
            index[language][row["id"]] = {"title": row["name"], "url": logo + ".webp"}
        sources.append({"url": url, "language": language, "sets": len(rows),
                        "logos": len(index[language]), "sha256": hashlib.sha256(raw).hexdigest()})
    path = STATIC / "catalogue-title-art.js"
    text = path.read_text()
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    block = "  const providerSets = " + json.dumps(index, ensure_ascii=False, indent=2) + ";\n"
    path.write_text(before + START + block + END + after)
    path = STATIC / "title-art" / "sources.json"
    manifest = json.loads(path.read_text())
    manifest["provider_set_logos"] = {
        "provider": "TCGdex", "retrieved": datetime.now(timezone.utc).date().isoformat(),
        "indexes": sources, "documentation": "https://tcgdex.dev/assets",
        "delivery": "Original logos from assets.tcgdex.net; exact provider, language and set ID required.",
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({source["language"]: source["logos"] for source in sources}))


if __name__ == "__main__":
    refresh()
