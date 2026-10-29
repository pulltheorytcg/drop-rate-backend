"""Offline checks for artwork-confirmed catalogue pricing, never inventory."""
import pytest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app import one_piece_artwork_match as art
from app import pokewallet_one_piece_market as market
from app.fx import FxQuote


NUMBER = "OP15-001"
TITLE = "Krieg"
SET = "BOOSTER PACK -Adventure on Kami's Island- [OP-15]"


def official(printing, **overrides):
    ref = {
        "provider": "Bandai Official", "system_code": "ONE_PIECE_CARD_GAME",
        "language": "English", "provider_id": printing, "card_number": NUMBER,
        "name": TITLE, "set_name": SET, "set_id": "569115",
        "rarity": "L", "finish": None,
        "image_url": f"https://en.onepiece-cardgame.com/images/cardlist/card/{printing}.png?261016",
        "evidence": {"detail_level": "OFFICIAL_CHECKLIST", "printing_id": printing},
        "has_detail_value": False, "existing_catalogue_value": 0,
        "existing_source": None, "existing_pricing_updated_at": None,
    }
    ref.update(overrides)
    return ref


def product(version, **overrides):
    suffix = f"-V{version}" if version > 1 else "-V1"
    row = {
        "id": f"op_abcdef{version:06d}", "card_number": NUMBER,
        "name": TITLE, "rarity": "L", "sub_type_name": "Normal" if version == 1 else "Alternate Art",
        "product_type": "card",
        "cardmarket": {
            "product_name": f"Krieg ({NUMBER}) (V.{version})",
            "product_url": ("https://www.cardmarket.com/en/OnePiece/Products/Singles/"
                            f"Adventure-on-Kamis-Island/Krieg-{NUMBER}{suffix}"),
            "prices": {"trend": 1.0 if version == 1 else 50.0},
        },
    }
    row.update(overrides)
    return row


def two_official():
    return [official(NUMBER), official(NUMBER + "_p1")]


def two_products():
    return [product(1), product(2)]


def test_official_printings_are_distinct_and_publisher_evidenced():
    refs = two_official()
    assert art.official_groups(refs, market.code_from_reference) == {("OP15", NUMBER): refs}
    assert art.official_groups([refs[0], official(NUMBER + "_p1", evidence={})],
                               market.code_from_reference) == {}
    assert art.official_groups([refs[0], official(NUMBER + "_p1", image_url=refs[0]["image_url"])],
                               market.code_from_reference) == {}
    assert art.official_groups([refs[0], official(NUMBER + "_p1", set_id="unrelated")],
                               market.code_from_reference) == {}
    assert art.official_groups([*refs, official(NUMBER + "_p2", evidence={})],
                               market.code_from_reference) == {}
    assert art.official_groups([*refs, official(NUMBER + "_foil")],
                               market.code_from_reference) == {}


@pytest.mark.parametrize("bad", [
    {"card_number": "OP14-001"},
    {"cardmarket": {"product_name": f"Krieg ({NUMBER}) (V.2)",
                    "product_url": "https://www.cardmarket.com/en/OnePiece/Products/Singles/Other/Krieg-OP15-001-V2"}},
    {"sub_type_name": "Unknown"},
    {"name": "Different", "cardmarket": {"product_name": "Different (OP15-001) (V.2)",
                        "product_url": "https://www.cardmarket.com/en/OnePiece/Products/Singles/Adventure-on-Kamis-Island/Different-OP15-001-V2"}},
])
def test_source_requires_complete_known_edition_and_cardmarket_identity(bad):
    candidates = two_products()
    candidates[1] = product(2, **bad)
    assert art.source_products_for_group(candidates, two_official()) == []


def test_source_accepts_only_complete_versions_not_order_or_price():
    assert art.source_products_for_group(two_products()[::-1], two_official()) == two_products()[::-1]
    assert art.source_products_for_group([product(2)], two_official()) == []
    assert art.source_products_for_group([product(1), product(1)], two_official()) == []
    assert art.source_products_for_group([product(1), product(3)], two_official()) == []


def test_perceptual_match_is_reciprocal_not_by_price_or_source_order():
    refs = two_official()
    products = two_products()[::-1]
    base_hash = (0,)
    alternate_hash = ((1 << 256) - 1,)
    matched = art.match_image_fingerprints(
        refs, products,
        {NUMBER: base_hash, NUMBER + "_p1": alternate_hash},
        {products[0]["id"]: alternate_hash, products[1]["id"]: base_hash},
    )
    assert {(link.reference_id, link.source_id) for link in matched} == {
        (NUMBER, product(1)["id"]), (NUMBER + "_p1", product(2)["id"]),
    }
    assert all(link.similarity == 1.0 and link.margin == 1.0 for link in matched)


def test_ambiguous_artwork_or_incomplete_fingerprints_never_price():
    refs = two_official()
    products = two_products()
    same = (0,)
    opposite = ((1 << 256) - 1,)
    assert art.match_image_fingerprints(refs, products,
        {NUMBER: same, NUMBER + "_p1": same},
        {products[0]["id"]: same, products[1]["id"]: opposite}) == []
    assert art.match_image_fingerprints(refs, products,
        {NUMBER: same, NUMBER + "_p1": opposite},
        {products[0]["id"]: same}) == []
    assert art.match_image_fingerprints(refs, products,
        {NUMBER: same, NUMBER + "_p1": opposite},
        {products[0]["id"]: (0b1010,), products[1]["id"]: (0b0101,)}) == []


@pytest.mark.asyncio
async def test_artwork_import_checks_actual_images_and_metadata(monkeypatch):
    refs = two_official()
    products = two_products()
    from app import pokewallet_one_piece_market as one_piece

    async def official_hash(url):
        return (0,) if url.endswith("OP15-001.png?261016") else ((1 << 256) - 1,)

    class FakeClient:
        requests = 0
        limit = 10

        async def get_image(self, source_id):
            self.requests += 1
            return source_id.encode()

    monkeypatch.setattr(one_piece, "reference_image_hashes", official_hash)
    monkeypatch.setattr(one_piece, "_open_image", lambda value: (value, 200, 280))
    monkeypatch.setattr(one_piece, "_fingerprints", lambda value: (0,) if value == products[0]["id"].encode() else ((1 << 256) - 1,))
    client = FakeClient()
    diag = {}
    linked = await one_piece.artwork_matches_for_complete_set(
        {("OP15", NUMBER): refs}, "English", "OP15", products, client, diag)
    assert len(linked) == 2
    assert {ref["provider_id"]: source["id"] for ref, source, _ in linked} == {
        NUMBER: products[0]["id"], NUMBER + "_p1": products[1]["id"],
    }
    assert all(evidence["match_basis"] == "OFFICIAL_PUBLISHER_ARTWORK_RECIPROCAL_IMAGE_MATCH"
               and evidence["image_similarity"] == 1.0
               for _, _, evidence in linked)
    assert diag["artwork_groups_verified"] == 1 and client.requests == 2

    # Swapping upstream images while leaving 'Normal'/'Alternate Art' labels
    # contradicting the official art must quarantine the entire group.
    monkeypatch.setattr(one_piece, "_fingerprints", lambda value: ((1 << 256) - 1,)
                        if value == products[0]["id"].encode() else (0,))
    assert await one_piece.artwork_matches_for_complete_set(
        {("OP15", NUMBER): refs}, "English", "OP15", products, client, {}) == []


@pytest.mark.asyncio
async def test_source_image_endpoint_is_quota_counted_and_requires_binary():
    class Response:
        status_code = 200
        headers = {"content-type": "image/png", "X-RateLimit-Remaining-Hour": "10"}
        content = b"png-fixture"

    class Http:
        async def get(self, url, headers):
            assert url == "https://api.pokewallet.io/images/op_abcdef0123"
            assert headers["X-API-Key"] == "pk_live_fixture"
            return Response()

    client = market.FreePokewalletOnePieceClient("pk_live_fixture", request_limit=1, client=Http())
    assert await client.get_image("op_abcdef0123") == b"png-fixture"
    assert client.requests == 1
    with pytest.raises(market.ProviderResponseError, match="REQUEST_BUDGET_EXHAUSTED"):
        await client.get_image("op_abcdef0123")


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_live_job_path_uses_artwork_evidence_for_reference_quotes_only(monkeypatch, dry_run):
    refs, products = two_official(), two_products()
    writes = []

    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self, query):
                assert query == market.READ_SQL
                return refs

            async def executemany(self, query, rows):
                assert query == market.WRITE_SQL
                writes.extend(rows)
        yield Conn()

    class Response:
        def __init__(self, body=None, image=None):
            self.status_code = 200
            self.headers = {"content-type": "image/png"} if image else {}
            self.content = image or b"ok"
            self.body = body

        def json(self):
            return self.body

    class Http:
        async def get(self, url, params=None, headers=None):
            if url.endswith("/op/sets"):
                return Response({"success": True, "data": (
                    [{"set_code": "OP15", "group_id": "15", "language": "en"}]
                    if params["language"] == "en" else [])})
            if url.endswith("/op/sets/15"):
                return Response({"success": True, "set": {
                    "set_code": "OP15", "group_id": "15", "language": "en"},
                    "page": 1, "total": 2, "data": products})
            if "/images/" in url:
                return Response(image=url.rsplit("/", 1)[-1].encode())
            raise AssertionError(f"Unexpected source endpoint: {url}")

    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)

    async def official_hash(url):
        return (0,) if url.endswith("OP15-001.png?261016") else ((1 << 256) - 1,)

    class FX:
        async def quote(self, **kwargs):
            return FxQuote("EUR", "GBP", Decimal(".86"), now, now, "ECB_EURO_REFERENCE_RATES")

    monkeypatch.setattr(market, "user_connection", connection)
    monkeypatch.setattr(market, "reference_image_hashes", official_hash)
    monkeypatch.setattr(market, "_open_image", lambda value: (value, 200, 280))
    monkeypatch.setattr(market, "_fingerprints", lambda value: (0,)
                        if value == products[0]["id"].encode() else ((1 << 256) - 1,))
    report = await market.refresh_pokewallet_one_piece(
        object(), uuid4(), FX(), "pk_live_secret_fixture",
        dry_run=dry_run, artwork_matching_enabled=True, request_limit=10,
        http_client=Http(),
    )
    assert report["provider_failures"] == 0
    assert report["requests"] == 5
    assert report["artwork_groups_verified"] == 1
    assert report["artwork_printings_quoted"] == 2
    assert report["eligible_quotes"] == 2
    assert report["writes_attempted"] == (0 if dry_run else 2)
    assert len(writes) == (0 if dry_run else 2)
    if writes:
        assert {row[3] for row in writes} == {NUMBER, NUMBER + "_p1"}
        assert {row[3]: row[4][0]["source_card_id"] for row in writes} == {
            NUMBER: products[0]["id"], NUMBER + "_p1": products[1]["id"]}
        assert all(row[4][0]["physical_valuation_eligible"] is False for row in writes)
        assert all(row[16] == next(ref["image_url"] for ref in refs if ref["provider_id"] == row[3])
                   and row[17] == row[3] for row in writes)
