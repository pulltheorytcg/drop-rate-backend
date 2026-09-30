from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ops" / "railway" / "psa-fetch-batch" / "index.tsx"


def test_psa_lookup_uses_current_public_api_contract() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "https://api.psacard.com/publicapi/cert/GetByCertNumber/" in source
    assert 'Authorization: `bearer ${token}`' in source
    assert "X-PSA-API-KEY" not in source
    assert "https://api.psacard.com/cert/" not in source


def test_psa_lookup_is_parameterised_and_read_only() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'c.req.query("cert")' in source
    assert "cert must be 7-10 digits" in source
    assert "Bun.env.PSA_PUBLIC_API_TOKEN" in source
    assert "TCG_PARSE_API_KEY" not in source
    assert "inventory_items" not in source
    assert "shopify" not in source.lower()
    assert "update " not in source.lower()
    assert "insert " not in source.lower()


def test_psa_lookup_does_not_equate_cert_with_canonical_identity() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "identity_matched" not in source
    assert "verified" in source
    assert "image_fields" in source
