"""D1 feasibility probe guarantees; only synthetic local SQLite is touched."""

import sqlite3
import unittest

from tools.d1_catalogue_feasibility import (
    EXACT_QUERY, NAME_QUERY, PROVIDERS, SET_PAGE_QUERY, SYSTEM_COUNTS,
    benchmark, build_connection, verify,
)


class D1CatalogueFeasibilityTests(unittest.TestCase):
    def test_public_reference_fixture_preserves_all_games_and_uses_indexes(self):
        counts = {system: 60 for system in SYSTEM_COUNTS}
        with build_connection(counts) as conn:
            result = verify(conn, counts)
            self.assertEqual(sum(result["counts"].values()), 360)
            self.assertTrue(all(any("INDEX" in op for op in plan)
                                for plan in result["index_plans"].values()))
            self.assertTrue(all(v["local_sqlite_p95_ms"] >= 0
                                for v in benchmark(conn, 8).values()))

    def test_identity_is_composite_and_language_specific(self):
        with build_connection({"POKEMON_TCG": 22}) as conn:
            provider = PROVIDERS["POKEMON_TCG"]
            english = conn.execute(EXACT_QUERY, (provider, "POKEMON_TCG", "English", "SYN-POK-000000")).fetchone()
            japanese = conn.execute(EXACT_QUERY, (provider, "POKEMON_TCG", "Japanese", "SYN-POK-000000")).fetchone()
            self.assertEqual(english["language"], "English")
            self.assertEqual(japanese["language"], "Japanese")
            self.assertEqual(english["name"], japanese["name"])
            self.assertIsNone(conn.execute(EXACT_QUERY, (provider, "ONE_PIECE_CARD_GAME", "English", "SYN-POK-000000")).fetchone())

    def test_prices_are_not_invented_when_quote_is_missing(self):
        with build_connection({"POKEMON_TCG": 30}) as conn:
            provider = PROVIDERS["POKEMON_TCG"]
            # 0 has detailed quote, 6 has catalogue quote, 8 has neither.
            for i, expected in ((0, (100, None)), (6, (None, 106)), (8, (None, None))):
                key = (provider, "POKEMON_TCG", "English", f"SYN-POK-{i // 2:06d}")
                value = conn.execute(EXACT_QUERY, key).fetchone()
                self.assertEqual((value["detailed_minor"], value["catalogue_minor"]), expected)

    def test_set_browse_has_stable_order_and_bounded_page(self):
        with build_connection({"POKEMON_TCG": 90}) as conn:
            args = (PROVIDERS["POKEMON_TCG"], "POKEMON_TCG", "English", "TEST-SET-0000")
            first = conn.execute(SET_PAGE_QUERY, (*args, 15, 0)).fetchall()
            second = conn.execute(SET_PAGE_QUERY, (*args, 15, 15)).fetchall()
            self.assertEqual((len(first), len(second)), (15, 15))
            self.assertEqual(len({r["provider_id"] for r in first + second}), 30)
            self.assertLess(first[-1]["provider_id"], second[0]["provider_id"])

    def test_search_uses_normalized_name_not_database_locale(self):
        with build_connection({"POKEMON_TCG": 25}) as conn:
            rows = conn.execute(NAME_QUERY, ("POKEMON_TCG", "Japanese", "char", "chas", 5)).fetchall()
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row["name"].startswith("Charizard") for row in rows))

    def test_foreign_key_rejects_orphan_quote_and_rolls_back(self):
        with build_connection({"POKEMON_TCG": 20}) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                with conn:
                    conn.execute("insert into reference_market_prices values (?,?,?,?,?)",
                                 ("bad", "POKEMON_TCG", "English", "unmatched", 999))
            self.assertEqual(conn.execute("select count(*) from reference_market_prices where provider='bad'").fetchone()[0], 0)

    def test_full_synthetic_scale_excludes_financial_tables(self):
        with build_connection(SYSTEM_COUNTS) as conn:
            self.assertEqual(verify(conn, SYSTEM_COUNTS)["counts"], SYSTEM_COUNTS)
            tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
            self.assertEqual(tables, {"reference_cards", "reference_market_prices", "reference_catalogue_prices"})


if __name__ == "__main__":
    unittest.main()
