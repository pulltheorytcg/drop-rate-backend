"""Run a manual, synthetic-only Cloudflare D1 read-model pilot.

No production Postgres, Supabase, R2, Shopify or user records are accessed.
The only remote write is creating and populating a new D1 database whose name
explicitly identifies it as synthetic test data. No database is ever deleted.

GitHub Actions supplies the token via CLOUDFARE_D1_PILOT_TOKEN (historical
secret spelling) and an account ID already present in the project's R2 docs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path
from time import perf_counter
from urllib import error, request

from d1_catalogue_feasibility import (
    EXACT_QUERY,
    NAME_QUERY,
    SCHEMA,
    SET_PAGE_QUERY,
    SYSTEM_COUNTS,
    synthetic_rows,
)


API_ORIGIN = "https://api.cloudflare.com/client/v4"
MAX_BOUND_PARAMETERS = 100  # Cloudflare D1 documented platform limit.
MAX_ROWS_PER_GAME = 1000
INSERT_COLUMNS = {
    "reference_cards": 10,
    "reference_market_prices": 5,
    "reference_catalogue_prices": 5,
}


class PilotError(RuntimeError):
    """A configuration, safety, Cloudflare API or validation failure."""


def validate_account_id(value: str) -> str:
    if not re.fullmatch(r"[a-fA-F0-9]{32}", value):
        raise PilotError("CLOUDFLARE_ACCOUNT_ID must be a 32-character hex account ID")
    return value.lower()


class D1Client:
    def __init__(self, account_id: str, token: str):
        self.account_id = validate_account_id(account_id)
        if not token or not token.strip():
            raise PilotError("CLOUDFARE_D1_PILOT_TOKEN GitHub Actions secret is missing")
        self._token = token.strip()
        self.path = f"/accounts/{self.account_id}/d1/database"

    def call(self, method: str, path: str, data: dict | None = None):
        if not path.startswith(self.path) or not re.fullmatch(r"[a-zA-Z0-9/_-]+", path):
            raise PilotError("Blocked API path outside the configured D1 account")
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        req = request.Request(
            f"{API_ORIGIN}{path}", data=payload, method=method,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        started = perf_counter()
        try:
            with request.urlopen(req, timeout=25) as response:
                result = json.load(response)
        except error.HTTPError as exc:
            # Do not include response bodies or credentials in CI logs.
            raise PilotError(f"Cloudflare D1 HTTP {exc.code}; check token scope/account ID") from None
        except (error.URLError, TimeoutError, ValueError) as exc:
            raise PilotError(f"Cloudflare D1 request/response failed: {type(exc).__name__}") from None
        if not isinstance(result, dict) or not result.get("success"):
            error_codes = [item.get("code") for item in result.get("errors", [])]
            raise PilotError(f"Cloudflare D1 API rejected request (error codes: {error_codes})")
        return result.get("result"), round((perf_counter() - started) * 1000, 3)

    def list_databases(self):
        result, _ = self.call("GET", self.path)
        if not isinstance(result, list):
            raise PilotError("Unexpected Cloudflare D1 database list shape")
        return result

    def create_synthetic_database(self, name: str):
        if not re.fullmatch(r"drop-rate-d1-synthetic-[0-9]+-[0-9]+", name):
            raise PilotError("Refusing to create a database without the synthetic-run marker")
        if any(db.get("name") == name for db in self.list_databases()):
            raise PilotError("Synthetic pilot database already exists; refusing to reuse or alter it")
        result, _ = self.call("POST", self.path, {"name": name})
        if not isinstance(result, dict) or result.get("name") != name:
            raise PilotError("Cloudflare did not return the expected synthetic database name")
        database_id = result.get("uuid", "")
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", database_id):
            raise PilotError("Cloudflare did not return a valid D1 database UUID")
        return database_id

    def query(self, database_id: str, sql: str, params: tuple | list = ()):  # noqa: PLR0913
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", database_id):
            raise PilotError("Invalid synthetic D1 database UUID")
        result, duration_ms = self.call(
            "POST", f"{self.path}/{database_id}/query", {"sql": sql, "params": list(params)}
        )
        return checked_query_results(result)[0], duration_ms

    def batch(self, database_id: str, queries: list[dict]):
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", database_id):
            raise PilotError("Invalid synthetic D1 database UUID")
        if not queries or len(queries) > 12:
            raise PilotError("Unexpected D1 SQL batch size")
        for statement in queries:
            if len(statement.get("params", [])) > MAX_BOUND_PARAMETERS:
                raise PilotError("D1 statement exceeds 100 bound parameters")
        result, _ = self.call("POST", f"{self.path}/{database_id}/query", {"batch": queries})
        return checked_query_results(result)


def checked_query_results(result):
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list) or not result:
        raise PilotError("D1 query returned no result envelopes")
    if any(not row.get("success", False) for row in result):
        raise PilotError("D1 query statement failed; synthetic database retained for inspection")
    return result


def insert_statement(table: str, rows: list[tuple]) -> dict:
    width = INSERT_COLUMNS[table]
    if not rows or any(len(row) != width for row in rows):
        raise PilotError("Invalid synthetic row shape")
    if width * len(rows) > MAX_BOUND_PARAMETERS:
        raise PilotError("Too many parameter bindings in synthetic insert")
    sql = f"insert into {table} values " + ",".join(
        "(" + ",".join("?" for _ in range(width)) + ")" for _ in rows
    )
    return {"sql": sql, "params": [item for row in rows for item in row]}


def insert_batches(rows_per_game: int):
    if not 1 <= rows_per_game <= MAX_ROWS_PER_GAME:
        raise PilotError(f"rows_per_game must be between 1 and {MAX_ROWS_PER_GAME}")
    cards, details, catalogue = [], [], []
    for system in SYSTEM_COUNTS:
        for identity, card, index in synthetic_rows(system, rows_per_game):
            cards.append(card)
            if index % 10 < 6:
                details.append((*identity, 100 + index % 10000))
            elif index % 10 == 6:
                catalogue.append((*identity, 100 + index % 10000))
    statements = []
    for table, rows, width in (
        ("reference_cards", cards, 10),
        ("reference_market_prices", details, 5),
        ("reference_catalogue_prices", catalogue, 5),
    ):
        chunk = MAX_BOUND_PARAMETERS // width
        for start in range(0, len(rows), chunk):
            statements.append(insert_statement(table, rows[start:start + chunk]))
    return statements, {"cards": len(cards), "detailed_prices": len(details), "catalogue_prices": len(catalogue)}


def populate(client: D1Client, database_id: str, rows_per_game: int):
    # Schema only contains CREATE statements and FK enforcement; no existing tables.
    # Cloudflare controls FK enforcement; avoid relying on a connection-scoped
    # PRAGMA carrying across independent REST API calls.
    schema_queries = [{"sql": sql.strip()} for sql in SCHEMA.split(";")
                      if sql.strip() and not sql.strip().lower().startswith("pragma foreign_keys")]
    client.batch(database_id, schema_queries)
    statements, counts = insert_batches(rows_per_game)
    for start in range(0, len(statements), 12):
        client.batch(database_id, statements[start:start + 12])
    return counts


def validate_remote(client: D1Client, database_id: str, rows_per_game: int):
    count_result, _ = client.query(database_id, "select count(*) as n from reference_cards")
    actual = count_result["results"][0]["n"]
    if actual != 6 * rows_per_game:
        raise PilotError(f"Synthetic catalogue count mismatch: {actual}")
    fks, _ = client.query(database_id, "pragma foreign_key_check")
    if fks.get("results"):
        raise PilotError("Synthetic D1 foreign key verification failed")
    sample = next(synthetic_rows("POKEMON_TCG", 1))[0]
    exact, _ = client.query(database_id, EXACT_QUERY, sample)
    if (len(exact["results"]) != 1 or exact["results"][0]["detailed_minor"] != 100
            or exact["results"][0]["catalogue_minor"] is not None):
        raise PilotError("Exact card lookup/price validation failed")
    page, _ = client.query(database_id, SET_PAGE_QUERY, (*sample[:3], "TEST-SET-0000", 25, 0))
    if len(page["results"]) != min(25, (rows_per_game + 1) // 2):
        raise PilotError("Indexed set pagination failed")
    prefix, _ = client.query(database_id, NAME_QUERY, ("POKEMON_TCG", "English", "char", "chas", 20))
    if not prefix["results"] or not all(row["name"].startswith("Charizard") for row in prefix["results"]):
        raise PilotError("Indexed name-prefix search failed")
    return {"synthetic_cards": actual, "foreign_keys_ok": True,
            "exact_price_ok": True, "set_browse_ok": True, "prefix_search_ok": True}


def percentile_95(values):
    return sorted(values)[int((len(values) - 1) * 0.95)]


def benchmark_remote(client: D1Client, database_id: str, repetitions: int = 20):
    sample = next(synthetic_rows("POKEMON_TCG", 1))[0]
    workloads = {
        "exact_printing": (EXACT_QUERY, sample),
        "set_browse_25": (SET_PAGE_QUERY, (*sample[:3], "TEST-SET-0000", 25, 0)),
        "prefix_search_20": (NAME_QUERY, ("POKEMON_TCG", "English", "char", "chas", 20)),
    }
    metrics = {}
    for name, (sql, params) in workloads.items():
        roundtrip, execution, rows_read = [], [], []
        for _ in range(repetitions):
            result, elapsed = client.query(database_id, sql, params)
            meta = result.get("meta") or {}
            roundtrip.append(elapsed)
            # Cloudflare returns SQL duration; request time includes remote network.
            if "timings" in meta and "sql_duration_ms" in meta["timings"]:
                execution.append(float(meta["timings"]["sql_duration_ms"]))
            if "rows_read" in meta:
                rows_read.append(meta["rows_read"])
        metrics[name] = {
            "github_runner_to_api_median_ms": round(statistics.median(roundtrip), 2),
            "github_runner_to_api_p95_ms": round(percentile_95(roundtrip), 2),
            "d1_sql_median_ms": round(statistics.median(execution), 2) if execution else None,
            "d1_sql_p95_ms": round(percentile_95(execution), 2) if execution else None,
            "max_rows_read": max(rows_read) if rows_read else None,
            "repetitions": repetitions,
        }
    return metrics


def run(mode: str, rows_per_game: int, account_id: str, token: str, run_id: str, attempt: str):
    client = D1Client(account_id, token)
    databases = client.list_databases()  # Authenticate and validate account before writes.
    if mode == "inspect":
        return {"mode": "READ_ONLY_ACCOUNT_CHECK", "d1_api_access": True,
                "visible_database_count": len(databases), "production_writes": 0}
    if mode != "pilot":
        raise PilotError("Unsupported mode")
    if not (re.fullmatch(r"[0-9]+", run_id) and re.fullmatch(r"[0-9]+", attempt)):
        raise PilotError("A GitHub Actions run ID and attempt are required before creating D1")
    # Unique per Actions attempt; never repurpose an existing / live database.
    name = f"drop-rate-d1-synthetic-{run_id}-{attempt}"
    if any(db.get("name") == name for db in databases):
        raise PilotError("Synthetic database exists; refusing to modify it")
    database_id = client.create_synthetic_database(name)
    print(json.dumps({"created_synthetic_test_database": name, "uuid": database_id}), flush=True)
    counts = populate(client, database_id, rows_per_game)
    verified = validate_remote(client, database_id, rows_per_game)
    return {"mode": "SYNTHETIC_D1_REMOTE_PILOT", "database_name": name,
            "database_uuid": database_id, "synthetic_rows": counts,
            "checks": verified, "benchmarks": benchmark_remote(client, database_id),
            "production_writes": 0, "deletions": 0,
            "note": "D1 test DB retained for review. No production traffic/cutover. API RTT is not app latency."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "pilot"), required=True)
    parser.add_argument("--rows-per-game", type=int, default=200)
    parser.add_argument("--report", type=Path, default=Path("d1-pilot-report.json"))
    args = parser.parse_args()
    if not 1 <= args.rows_per_game <= MAX_ROWS_PER_GAME:
        parser.error(f"rows-per-game must be 1..{MAX_ROWS_PER_GAME}")
    try:
        report = run(
            args.mode, args.rows_per_game,
            os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            os.environ.get("CLOUDFARE_D1_PILOT_TOKEN", ""),
            os.environ.get("GITHUB_RUN_ID", ""),
            os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        )
    except PilotError as exc:
        print(f"D1 pilot failed safely: {exc}", file=sys.stderr)
        return 1
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
