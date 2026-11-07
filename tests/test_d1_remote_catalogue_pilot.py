"""Offline safety tests. These never call Cloudflare or any production service."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from d1_remote_catalogue_pilot import (  # noqa: E402
    D1Client,
    PilotError,
    checked_query_results,
    insert_batches,
    insert_statement,
    run,
    validate_account_id,
)


ACCOUNT = "e4d4b363540e991048d2e1812d5ef53e"
UUID = "12345678-1234-1234-1234-1234567890ab"


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class D1RemotePilotTests(unittest.TestCase):
    def test_account_validation_and_missing_token(self):
        self.assertEqual(validate_account_id(ACCOUNT), ACCOUNT)
        for value in ("", "not an account", "a" * 32 + "/d1/database"):
            with self.assertRaises(PilotError):
                validate_account_id(value)
        with self.assertRaises(PilotError):
            D1Client(ACCOUNT, "")

    def test_inspect_is_read_only_even_when_run_ids_are_present(self):
        calls = []

        def fake_open(req, timeout):
            calls.append((req.get_method(), req.full_url))
            return Response(json.dumps({"success": True, "result": []}).encode())

        with patch("d1_remote_catalogue_pilot.request.urlopen", side_effect=fake_open):
            result = run("inspect", 200, ACCOUNT, "dummy-token", "123", "1")
        self.assertEqual(result["production_writes"], 0)
        self.assertEqual(calls, [("GET", f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database")])

    def test_pilot_requires_github_run_identity_before_remote_write(self):
        with patch.object(D1Client, "list_databases", return_value=[]), patch.object(
            D1Client, "create_synthetic_database", side_effect=AssertionError("must not create")
        ):
            with self.assertRaises(PilotError):
                run("pilot", 200, ACCOUNT, "dummy-token", "", "1")

    def test_existing_pilot_name_is_never_modified(self):
        existing = [{"name": "drop-rate-d1-synthetic-456-1", "uuid": UUID}]
        with patch.object(D1Client, "list_databases", return_value=existing), patch.object(
            D1Client, "create_synthetic_database", side_effect=AssertionError("must not create")
        ):
            with self.assertRaises(PilotError):
                run("pilot", 200, ACCOUNT, "dummy-token", "456", "1")

    def test_batches_use_only_synthetic_data_and_at_most_100_parameters(self):
        statements, counts = insert_batches(200)
        self.assertEqual(counts["cards"], 1200)
        self.assertEqual(counts["detailed_prices"], 720)
        self.assertEqual(counts["catalogue_prices"], 120)
        self.assertTrue(statements)
        self.assertTrue(all(len(item["params"]) <= 100 for item in statements))
        self.assertTrue(all(item["sql"].lower().startswith("insert into reference_") for item in statements))
        self.assertTrue(any("TEST-SET-" in str(param) for item in statements for param in item["params"]))
        with self.assertRaises(PilotError):
            insert_batches(1001)
        with self.assertRaises(PilotError):
            insert_statement("reference_cards", [("bad",)])

    def test_remote_create_requires_synthetic_database_name(self):
        client = D1Client(ACCOUNT, "dummy-token")
        with self.assertRaises(PilotError):
            client.create_synthetic_database("drop-rate-production")
        with self.assertRaises(PilotError):
            client.batch(UUID, [{"sql": "select 1", "params": [0] * 101}])
        with self.assertRaises(PilotError):
            client.call("POST", "/accounts/not-ours/d1/database", {"name": "bad"})

    def test_query_envelope_and_http_errors_do_not_leak_token(self):
        client = D1Client(ACCOUNT, "hidden-secret")
        self.assertEqual(checked_query_results({"success": True, "results": []})[0]["results"], [])
        with self.assertRaises(PilotError):
            checked_query_results([{"success": False, "error": "failure"}])

        def denial(req, timeout):
            raise HTTPError(req.full_url, 403, "Auth failed hidden-secret", {}, None)

        with patch("d1_remote_catalogue_pilot.request.urlopen", side_effect=denial):
            with self.assertRaises(PilotError) as ctx:
                client.list_databases()
        self.assertNotIn("hidden-secret", str(ctx.exception))

    def test_full_synthetic_remote_sequence_against_sqlite_transport_double(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys=on")
        calls = []

        def fake_batch(_client, database_id, queries):
            self.assertEqual(database_id, UUID)
            calls.extend(item["sql"].lower().strip() for item in queries)
            with conn:
                for item in queries:
                    conn.execute(item["sql"], item.get("params", []))
            return [{"success": True, "results": []} for _ in queries]

        def fake_query(_client, database_id, sql, params=()):
            self.assertEqual(database_id, UUID)
            rows = [dict(item) for item in conn.execute(sql, params).fetchall()]
            return ({"success": True, "results": rows, "meta": {
                "rows_read": len(rows), "timings": {"sql_duration_ms": 0.1}}}, 0.5)

        with patch.object(D1Client, "list_databases", return_value=[]), patch.object(
            D1Client, "create_synthetic_database", return_value=UUID
        ), patch.object(D1Client, "batch", new=fake_batch), patch.object(
            D1Client, "query", new=fake_query
        ):
            result = run("pilot", 200, ACCOUNT, "dummy-token", "789", "1")
        self.assertTrue(result["checks"]["exact_price_ok"])
        self.assertEqual(result["synthetic_rows"]["cards"], 1200)
        self.assertEqual(len(result["benchmarks"]), 3)
        self.assertTrue(all(x.startswith(("create ", "insert ")) for x in calls))
        self.assertFalse(any("drop" in x or "delete" in x or "truncate" in x for x in calls))
        conn.close()


if __name__ == "__main__":
    unittest.main()
