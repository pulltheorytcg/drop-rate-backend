"""Read-only D1/SQLite catalogue query feasibility probe.

This uses *synthetic* reference data and local SQLite, the SQL engine used by
Cloudflare D1. It does not contact Cloudflare or PostgreSQL, estimate D1 network
latency, price an account, move real data or change production configuration.

Run: python tools/d1_catalogue_feasibility.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from time import perf_counter


# Production counts independently verified on 3 November 2026. Synthetic data
# distribution and market coverage are *not* production measurements.
SYSTEM_COUNTS = {
    "POKEMON_TCG": 36927,
    "ONE_PIECE_CARD_GAME": 9007,
    "DRAGON_BALL_SUPER_MASTERS": 9002,
    "DRAGON_BALL_SUPER_FUSION_WORLD": 7595,
    "NARUTO_BANDAI_LEGACY": 4487,
    "NARUTO_KAYOU": 2679,
}

PROVIDERS = {
    "POKEMON_TCG": "TCGdex",
    "ONE_PIECE_CARD_GAME": "Punk Records",
    "DRAGON_BALL_SUPER_MASTERS": "Bandai Official",
    "DRAGON_BALL_SUPER_FUSION_WORLD": "Bandai Official",
    "NARUTO_BANDAI_LEGACY": "Synthetic Naruto Reference",
    "NARUTO_KAYOU": "Synthetic Kayou Reference",
}

SCHEMA = """
pragma foreign_keys=on;
create table reference_cards (
 provider text not null, system_code text not null,
 language text not null, provider_id text not null,
 set_id text not null, name text not null, name_fold text not null,
 card_number text not null, rarity text not null, image_key text,
 primary key(provider,system_code,language,provider_id)
);
create index reference_cards_set_idx
 on reference_cards(provider,system_code,language,set_id,provider_id);
create index reference_cards_name_idx
 on reference_cards(system_code,language,name_fold,provider_id);
create table reference_market_prices (
 provider text not null, system_code text not null,
 language text not null, provider_id text not null,
 market_value_minor integer not null,
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,provider_id)
 references reference_cards(provider,system_code,language,provider_id)
);
create table reference_catalogue_prices (
 provider text not null, system_code text not null,
 language text not null, provider_id text not null,
 market_value_minor integer not null,
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,provider_id)
 references reference_cards(provider,system_code,language,provider_id)
);
"""

EXACT_QUERY = """
select r.provider_id,r.name,r.language,m.market_value_minor as detailed_minor,
       b.market_value_minor as catalogue_minor
from reference_cards r
left join reference_market_prices m
 using(provider,system_code,language,provider_id)
left join reference_catalogue_prices b
 using(provider,system_code,language,provider_id)
where r.provider=? and r.system_code=? and r.language=? and r.provider_id=?
"""

SET_PAGE_QUERY = """
select r.provider_id,r.name,r.card_number,r.rarity,
       m.market_value_minor as detailed_minor,
       b.market_value_minor as catalogue_minor
from reference_cards r
left join reference_market_prices m
 using(provider,system_code,language,provider_id)
left join reference_catalogue_prices b
 using(provider,system_code,language,provider_id)
where r.provider=? and r.system_code=? and r.language=? and r.set_id=?
order by r.provider_id limit ? offset ?
"""

NAME_QUERY = """
select provider_id,name from reference_cards
where system_code=? and language=? and name_fold>=? and name_fold<?
order by name_fold,provider_id limit ?
"""


def synthetic_rows(system: str, count: int):
    """Generate unique printings; same ID can exist in both languages."""
    provider = PROVIDERS[system]
    stem = {"POKEMON_TCG": "Charizard", "ONE_PIECE_CARD_GAME": "Luffy",
            "DRAGON_BALL_SUPER_MASTERS": "Son Goku",
            "DRAGON_BALL_SUPER_FUSION_WORLD": "Vegeta",
            "NARUTO_BANDAI_LEGACY": "Naruto", "NARUTO_KAYOU": "Sasuke"}[system]
    for i in range(count):
        language = "English" if i % 2 == 0 else "Japanese"
        provider_id = f"SYN-{system[:3]}-{i // 2:06d}"
        name = f"{stem} SAMPLE {i // 2:05d}"
        identity = (provider, system, language, provider_id)
        card = (*identity, f"TEST-SET-{i // 200:04d}", name,
                name.casefold(), f"{i % 400:03d}", "TEST_ONLY", None)
        yield identity, card, i


def build_connection(counts: dict[str, int] | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    counts = counts or SYSTEM_COUNTS
    with conn:
        for system, count in counts.items():
            for identity, card, index in synthetic_rows(system, count):
                conn.execute("insert into reference_cards values (?,?,?,?,?,?,?,?,?,?)", card)
                if index % 10 < 6:
                    conn.execute("insert into reference_market_prices values (?,?,?,?,?)",
                                 (*identity, 100 + index % 10000))
                elif index % 10 == 6:
                    conn.execute("insert into reference_catalogue_prices values (?,?,?,?,?)",
                                 (*identity, 100 + index % 10000))
    return conn


def verify(conn: sqlite3.Connection, counts: dict[str, int]) -> dict:
    assert conn.execute("select count(*) from reference_cards").fetchone()[0] == sum(counts.values())
    assert conn.execute("pragma foreign_key_check").fetchall() == []
    by_system = dict(conn.execute(
        "select system_code,count(*) from reference_cards group by system_code"
    ).fetchall())
    assert by_system == counts

    sample = next(synthetic_rows("POKEMON_TCG", 1))[0]
    exact = conn.execute(EXACT_QUERY, sample).fetchone()
    assert exact is not None and exact["language"] == "English"
    assert exact["detailed_minor"] == 100 and exact["catalogue_minor"] is None

    page = conn.execute(SET_PAGE_QUERY, (*sample[:3], "TEST-SET-0000", 25, 0)).fetchall()
    assert len(page) == min(25, (counts["POKEMON_TCG"] + 1) // 2, 100)
    assert [r["provider_id"] for r in page] == sorted(r["provider_id"] for r in page)

    prefix = conn.execute(NAME_QUERY, ("POKEMON_TCG", "English", "char", "chas", 20)).fetchall()
    assert prefix and all(row["name"].startswith("Charizard") for row in prefix)

    plans = {
        "exact": [row[3] for row in conn.execute("explain query plan " + EXACT_QUERY, sample)],
        "set_page": [row[3] for row in conn.execute(
            "explain query plan " + SET_PAGE_QUERY,
            (*sample[:3], "TEST-SET-0000", 25, 0))],
        "prefix": [row[3] for row in conn.execute(
            "explain query plan " + NAME_QUERY,
            ("POKEMON_TCG", "English", "char", "chas", 20))],
    }
    assert all(any("USING" in op and "INDEX" in op for op in ops)
               for ops in plans.values()), plans

    return {"counts": by_system, "index_plans": plans}


def benchmark(conn: sqlite3.Connection, repetitions: int = 150) -> dict:
    sample = next(synthetic_rows("POKEMON_TCG", 1))[0]
    work = {
        "exact_printing": (EXACT_QUERY, sample),
        "set_browse_25": (SET_PAGE_QUERY, (*sample[:3], "TEST-SET-0000", 25, 0)),
        "prefix_search_20": (NAME_QUERY, ("POKEMON_TCG", "English", "char", "chas", 20)),
    }
    result = {}
    for label, (sql, params) in work.items():
        elapsed = []
        for _ in range(repetitions):
            started = perf_counter()
            conn.execute(sql, params).fetchall()
            elapsed.append((perf_counter() - started) * 1000)
        result[label] = {"local_sqlite_median_ms": round(statistics.median(elapsed), 3),
                         "local_sqlite_p95_ms": round(sorted(elapsed)[int(0.95 * (len(elapsed) - 1))], 3)}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small", action="store_true", help="Use 60 synthetic cards per game")
    args = parser.parse_args()
    counts = {s: min(n, 60) for s, n in SYSTEM_COUNTS.items()} if args.small else SYSTEM_COUNTS
    started = perf_counter()
    with build_connection(counts) as conn:
        verified = verify(conn, counts)
        measurements = benchmark(conn)
        bytes_used = conn.execute("pragma page_count").fetchone()[0] * conn.execute(
            "pragma page_size").fetchone()[0]
    print(json.dumps({"status": "LOCAL_SQLITE_ONLY_NOT_CLOUDFLARE_D1",
                      "synthetic_rows": sum(counts.values()),
                      "build_seconds": round(perf_counter() - started, 2),
                      "sqlite_allocated_bytes": bytes_used,
                      "verification": verified, "benchmarks": measurements}, indent=2))


if __name__ == "__main__":
    main()
