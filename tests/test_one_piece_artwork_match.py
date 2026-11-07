"""Offline checks for artwork-confirmed catalogue pricing, never inventory."""
import pytest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
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


def test_coverage_first_refuses_refreshes_but_accepts_genuinely_missing_prices():
    now = datetime(2026, 10, 29, 16, tzinfo=timezone.utc)
    previously_priced = official(NUMBER, existing_catalogue_value=1000,
        existing_source=market.SOURCE, existing_pricing_updated_at=now - timedelta(days=4))
    missing = official(NUMBER, existing_catalogue_value=0)
    assert market.quote_eligible(previously_priced, now)
    assert not market.quote_eligible(previously_priced, now, coverage_first=True)
    assert market.quote_eligible(missing, now, coverage_first=True)
    assert market.collect_reference_groups([previously_priced], now, coverage_first=True) == {}
    # The source must not be queried just to refresh an already priced row.
    assert market.collect_reference_groups([missing], now, coverage_first=True)
    # A stale *detail* price counts towards global coverage as well.
    stale_detail = official(NUMBER, has_any_detail_value=True, has_detail_value=False)
    assert market.quote_eligible(stale_detail, now)
    assert not market.quote_eligible(stale_detail, now, coverage_first=True)


def test_missing_artwork_sets_are_prioritised_even_after_an_old_starter_cursor():
    targets = [("Japanese", "OP02", "11"), ("English", "OP15", "15"),
               ("English", "OP16", "16"), ("English", "ST02", "3191")]
    assert market.prioritize_missing_artwork_sets(
        targets, {"OP15", "OP16"}, "English:15") == [
            ("English", "OP16", "16"), ("English", "OP15", "15"),
            ("Japanese", "OP02", "11"), ("English", "ST02", "3191")]
    assert market.prioritize_missing_artwork_sets(
        targets, {"OP15"}, "English:3191")[0] == ("English", "OP15", "15")


@pytest.mark.asyncio
async def test_ambiguous_art_group_cursor_advances_instead_of_stalling(monkeypatch):
    called = []
    monkeypatch.setattr(market, "MAX_ARTWORK_GROUPS_PER_RUN", 1)
    def unlabeled(_, refs):
        called.append(refs[0]["card_number"])
        return []
    monkeypatch.setattr(market, "source_products_for_group", unlabeled)
    groups = {("OP15", f"OP15-{i:03d}"): [official(NUMBER, card_number=f"OP15-{i:03d}")]
              for i in (1, 2, 3)}
    class NeverCall:
        requests = 0
        limit = 10
        async def get_image(self, _):
            raise AssertionError("Unlabelled group must not fetch images")
    report = {"artwork_groups_tested": 0}
    assert await market.artwork_matches_for_complete_set(
        groups, "English", "OP15", [], NeverCall(), report,
        previous_artwork_cursor="OP15:OP15-001") == []
    assert called == ["OP15-002", "OP15-003", "OP15-001"]
    assert report["artwork_groups_tested"] == 0


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


def test_cardmarket_exact_bandai_release_code_slug_is_valid_for_artwork_matching():
    # Cardmarket's real OP16 singles have /Singles/OP16/ URLs, whereas the
    # Bandai checklist calls the same release "The Time of Battle [OP-16]".
    refs = [official(printing, card_number="OP16-001", name="Portgas.D.Ace",
                     set_name="BOOSTER PACK -The Time of Battle- [OP-16]", set_id="569116")
            for printing in ("OP16-001", "OP16-001_p1")]
    products = [product(version, card_number="OP16-001", name="Portgas.D.Ace",
                        cardmarket={
                            "product_name": f"Portgas.D.Ace (OP16-001) (V.{version})",
                            "product_url": ("https://www.cardmarket.com/en/OnePiece/Products/Singles/"
                                            f"OP16/PortgasDAce-OP16-001-V{version}"),
                            "prices": {"trend": 1.0 if version == 1 else 50.0},
                        })
                for version in (1, 2)]
    assert art.source_products_for_group(products, refs) == products
    unlabelled = [{**p, "sub_type_name": None} for p in products]
    assert art.image_proven_source_candidates(unlabelled, refs) == unlabelled

    # An adjacent release or region-specific slug is not sufficient identity.
    for wrong_slug in ("OP17", "OP16-Japanese", "OP16-Non-English", "OP160"):
        wrong = [{**products[0]}, {**products[1], "cardmarket": {
            **products[1]["cardmarket"],
            "product_url": products[1]["cardmarket"]["product_url"].replace(
                "/Singles/OP16/", f"/Singles/{wrong_slug}/"),
        }}]
        assert art.source_products_for_group(wrong, refs) == []
        assert art.image_proven_source_candidates(wrong, refs) == []


def test_unlabelled_source_candidates_need_exact_title_release_number_and_rarity():
    missing_labels = [product(1, sub_type_name=None), product(2, sub_type_name=None)]
    assert art.source_products_for_group(missing_labels, two_official()) == []
    assert art.image_proven_source_candidates(missing_labels, two_official()) == missing_labels
    # A third distinct source printing may be compared but cannot silently
    # disappear from the source collision test.
    extras = missing_labels + [product(3, sub_type_name=None)]
    assert art.image_proven_source_candidates(extras, two_official()) == extras
    assert art.image_proven_source_candidates([missing_labels[0]], two_official()) == []
    assert art.image_proven_source_candidates(
        [missing_labels[0], product(2, rarity="C")], two_official()) == []
    assert art.image_proven_source_candidates(
        [missing_labels[0], product(2, cardmarket={**product(2)["cardmarket"],
            "product_name": "Other (OP15-001) (V.2)"})], two_official()) == []
    assert art.image_proven_source_candidates(
        [missing_labels[0], product(2, cardmarket={**product(2)["cardmarket"],
            "product_url": "https://www.cardmarket.com/en/OnePiece/Products/Singles/Wrong-Set/Krieg-OP15-001-V2"})],
        two_official()) == []


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


def test_image_match_checks_every_extra_source_competitor():
    refs = two_official()
    products = [product(1), product(2), product(3)]
    official = {NUMBER: (0,), NUMBER + "_p1": ((1 << 256) - 1,)}
    source = {products[0]["id"]: (0,), products[1]["id"]: ((1 << 256) - 1,),
              products[2]["id"]: ((1 << 128) - 1,)}
    matches = art.match_image_fingerprints(refs, products, official, source)
    assert {link.source_id for link in matches} == {products[0]["id"], products[1]["id"]}
    # A second source variant with the same base artwork destroys uniqueness.
    source[products[2]["id"]] = (0,)
    assert art.match_image_fingerprints(refs, products, official, source) == []


@pytest.mark.asyncio
async def test_artwork_can_prove_unlabelled_printings_without_guessing_versions(monkeypatch):
    refs = two_official()
    products = [product(1, sub_type_name=None), product(2, sub_type_name=None)]
    async def official_hash(url):
        return (0,) if url.endswith("OP15-001.png?261016") else ((1 << 256) - 1,)
    class FakeClient:
        requests = 0
        limit = 10
        async def get_image(self, source_id):
            self.requests += 1
            return source_id.encode()
    monkeypatch.setattr(market, "reference_image_hashes", official_hash)
    monkeypatch.setattr(market, "_open_image", lambda value: (value, 200, 280))
    monkeypatch.setattr(market, "_fingerprints", lambda value: (0,)
                        if value == products[0]["id"].encode() else ((1 << 256) - 1,))
    stats = {"artwork_groups_tested": 0}
    matches = await market.artwork_matches_for_complete_set(
        {("OP15", NUMBER): refs}, "English", "OP15", products, FakeClient(), stats)
    assert len(matches) == 2
    assert stats["artwork_groups_image_only_candidates"] == 1
    assert all(evidence["printing_label_confirmed"] is False
               for _, _, evidence in matches)

    # If a supplier explicitly calls the alternate 'Normal' while its art
    # matches the publisher's alternate, that contradiction still fails shut.
    products[1]["sub_type_name"] = "Normal"
    stats = {"artwork_groups_tested": 0}
    assert await market.artwork_matches_for_complete_set(
        {("OP15", NUMBER): refs}, "English", "OP15", products, FakeClient(), stats) == []
    assert stats["artwork_groups_metadata_conflict"] == 1


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
    assert report["artwork_cursors"] == {"OP15": "OP15:OP15-001"}
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


@pytest.mark.asyncio
async def test_coverage_first_writes_only_the_unpriced_alternate(monkeypatch):
    refs = two_official()
    now = datetime(2026, 10, 29, 16, tzinfo=timezone.utc)
    refs[0]["existing_catalogue_value"] = 500
    refs[0]["existing_source"] = market.SOURCE
    refs[0]["existing_pricing_updated_at"] = now - timedelta(days=4)
    products = two_products()
    writes = []

    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self, query):
                return refs
            async def executemany(self, query, rows):
                writes.extend(rows)
        yield Conn()

    class Response:
        def __init__(self, body=None, image=None):
            self.status_code = 200
            self.body = body
            self.headers = {"content-type": "image/png"} if image else {}
            self.content = image or b"fixture"
        def json(self):
            return self.body

    class Http:
        async def get(self, url, params=None, headers=None):
            if url.endswith("/op/sets"):
                return Response({"success": True, "data": [
                    {"set_code": "OP15", "group_id": "15", "language": "en"}]
                    if params["language"] == "en" else []})
            if url.endswith("/op/sets/15"):
                return Response({"success": True,
                    "set": {"set_code": "OP15", "group_id": "15", "language": "en"},
                    "page": 1, "total": 2, "data": products})
            if "/images/" in url:
                return Response(image=url.rsplit("/", 1)[-1].encode())
            raise AssertionError("Unexpected endpoint")

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
    result = await market.refresh_pokewallet_one_piece(
        object(), uuid4(), FX(), "pk_live_secret_fixture",
        dry_run=False, coverage_first=True, artwork_matching_enabled=True,
        request_limit=10, http_client=Http())
    assert result["coverage_first"] is True and result["artwork_groups_verified"] == 1
    assert result["artwork_priority_releases"] == ["OP15"]
    assert result["artwork_cursors"] == {"OP15": "OP15:OP15-001"}
    assert result["eligible_quotes"] == result["writes_attempted"] == 1
    assert len(writes) == 1 and writes[0][3] == NUMBER + "_p1"
