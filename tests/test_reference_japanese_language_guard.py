"""Database and importer must both reject English-product fallback into Japanese prices."""
from pathlib import Path

from app.one_piece_japanese_market import japanese_nonenglish_quote

ROOT=Path(__file__).resolve().parents[1]


def test_importer_has_explicit_language_exclusive_market_product_selector():
    source=(ROOT/'backend/app/one_piece_market.py').read_text()
    block=source[source.index("for ref in references:\n            # Provider ids are reused"):source.index("            price = prices.get(",source.index("for ref in references:\n            # Provider ids are reused"))]
    assert "if ref['language']=='Japanese':" in block
    assert "product = jp_match['product'] if jp_match else None" in block
    assert "elif ref['language']=='English':" in block
    assert "product = matches.get(ref['provider_id'])" in block
    assert "product = jp_match['product'] if jp_match else matches.get(" not in source
    assert "jp_match = None\n                product = None" in block


def test_database_constraint_fails_closed_for_missing_japanese_source_evidence():
    source=(ROOT/'database/migrations/20261013105000_reference_japanese_source_guard.sql').read_text()
    assert "ALTER TABLE tcg.reference_market_prices" in source
    assert "ADD CONSTRAINT reference_market_one_piece_japanese_source_language" in source
    assert "VALIDATE CONSTRAINT reference_market_one_piece_japanese_source_language" in source
    assert "language = 'Japanese'" in source
    assert "COALESCE(quotes->0->>'reference_language','') <> 'Japanese'" in source
    assert "COALESCE(quotes->0->>'source','') = 'CARDMARKET_BULK_SINGLES'" in source
    assert "DROP TABLE" not in source
    assert "DELETE FROM" not in source
    assert "DISABLE TRIGGER" not in source
    assert "ROW LEVEL SECURITY" not in source
