import io
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

from app.book_artwork import book_cover_reference
from app.book_bulk_import import (ImportPaused, apply_batch, capacity_plan, open_stage,
                                  source_attributes, stage_file, stage_report, import_capacity)
from app.book_catalogue_sources import ReviewRequired, normalise, validate_entry, barcode_aliases
from app.book_research import catalogue_candidates
from scripts.fetch_book_catalogue import (PRH_URL, export_download, fetch_gcd, fetch_prh,
    get, open_download, provider_json)
from scripts.import_book_catalogue import check_covers
from book_bulk_samples import entry, gcd, isbn, prh, publisher


@pytest.mark.parametrize("provider,sample", [("PUBLISHER", publisher), ("GCD", gcd), ("PRH", prh)])
@pytest.mark.parametrize("manga", [True, False])
def test_both_catalogues_roundtrip_with_no_printing_price_or_rights_approval(provider, sample, manga):
    row = normalise(provider, sample(manga=manga))
    validate_entry(row)
    assert (row["book"]["system_code"] == "MANGA") == manga
    assert row["book"]["printing_number"] is None
    assert "price" not in row and row["reference"] is None
    attrs = source_attributes(row, "fixture")
    assert attrs["cover_rights_status"] == "PENDING"
    if provider == "GCD":
        assert row["image_url"] is None and "by-sa/4.0" in row["metadata_license"]


def test_omnibus_language_binding_and_variant_are_distinct_editions():
    source = prh(); first = normalise("PRH", source)
    assert first["book"]["issue_number"] == "1-3" and "Omnibus" in first["book"]["series_title"]
    source["title"]["format"] = {"code": "HC"}; source["title"]["formatFamily"] = "Hardcover"
    hardback = normalise("PRH", source)
    source["title"]["language"] = "J"; japanese = normalise("PRH", source)
    assert len({r["identity_key"] for r in (first, hardback, japanese)}) == 3
    source = gcd(); source["issue"].update(variant_of="https://www.comics.org/api/issue/2/", variant_name="Cover B")
    variant = normalise("GCD", source)
    assert variant["book"]["cover_code"] == "Cover B"
    assert variant["book"]["printing_number"] is None
    source["issue"]["variant_name"] = ""
    with pytest.raises(ReviewRequired, match="VARIANT_NAME"):
        normalise("GCD", source)


def test_isbn10_is_canonicalised_and_unknown_dates_relations_not_invented():
    source = publisher(); source["book"]["barcode_gtin"] = "1-56931-901-4"
    assert normalise("PUBLISHER", source)["book"]["barcode_gtin"] == "9781569319017"
    source = gcd(); source["issue"]["series"] = "https://www.comics.org/api/series/6/"
    with pytest.raises(ReviewRequired, match="RELATION"):
        normalise("GCD", source)
    source = prh(); source["title"]["title"] = "86"; source["title"]["seriesNumber"] = None
    with pytest.raises(ReviewRequired, match="VOLUME_NUMBER_REQUIRED"):
        normalise("PRH", source)


def test_barcode_aliases_protect_legacy_rows_without_merging_comic_addons():
    assert barcode_aliases("1-56931-901-4") == ["1569319014", "9781569319017"]
    assert barcode_aliases("75960621349800112") == ["75960621349800112"]
    assert barcode_aliases("759606213498") == ["0759606213498", "759606213498"]


@pytest.mark.parametrize("change", [
    {"source_url": "https://www.viz.com.evil.test/manga-books/manga/1"},
    {"image_url": "https://images.penguinrandomhouse.com/cover/9781569319017"},
    {"language": "unknown"}, {"release_date": "2099-01-01"},
])
def test_source_edition_language_and_dates_fail_closed(change):
    with pytest.raises(ValueError):
        normalise("PUBLISHER", {**publisher(), **change})


def test_thousands_stage_restart_conflicts_and_changed_input(tmp_path):
    path = tmp_path / "books.jsonl"
    rows = [publisher(n, n % 2 == 0) for n in range(1, 2501)]
    rows += [deepcopy(rows[0]), {**deepcopy(rows[1]), "language": "Japanese"}, {"bad": "schema"}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    state = open_stage(tmp_path / "stage.sqlite")
    real = normalise
    calls = 0
    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 205:
            raise KeyboardInterrupt
        return real(*args)
    with patch("app.book_bulk_import.normalise", interrupted), pytest.raises(KeyboardInterrupt):
        stage_file(state, path, "PUBLISHER")
    state.close()
    state = open_stage(tmp_path / "stage.sqlite")
    report = stage_file(state, path, "PUBLISHER")
    assert report["statuses"] == {"DUPLICATE": 1, "READY": 2499, "REVIEW": 3}
    assert report["ready_by_system"] == {"OTHER_COMICS": 1250, "MANGA": 1249}
    assert stage_file(state, path, "PUBLISHER") == report
    path.write_text(path.read_text() + "{}\n")
    with pytest.raises(ImportPaused, match="INPUT_CHANGED"):
        stage_file(state, path, "PUBLISHER")
    state.close()


@pytest.mark.asyncio
async def test_covers_are_checked_resumable_and_pending_bytes_never_render(tmp_path):
    path = tmp_path / "books.jsonl"; path.write_text("\n".join(json.dumps(publisher(n)) for n in (1, 2)))
    state = open_stage(tmp_path / "stage.sqlite"); stage_file(state, path, "PUBLISHER")
    data = io.BytesIO(); Image.new("RGB", (300, 450), "red").save(data, format="PNG")
    fetch = AsyncMock(side_effect=[None, SimpleNamespace(data=data.getvalue())])
    assert (await check_covers(state, 1, fetch))["cover_checks"] == {"checked": 0, "pending": 1}
    report = await check_covers(state, 1, fetch)
    assert report["artwork"] == {"pending": 1, "checked": 1}
    assert fetch.await_count == 2
    row = json.loads(state.execute("select entry from records where line=2").fetchone()[0])
    validate_entry(row)
    assert len(row["reference"]["observed_sha256"]) == 64
    state.close()


def catalogue_book(row):
    return {**row["book"], "catalogue_id": row["id"], "language": row["catalogue"]["language"],
        "name": row["catalogue"]["name"], "profile_status": "STRUCTURED", "identity_status": "STRUCTURED",
        "profile_release_date": row["release_date"], "attributes": source_attributes(row, "fixture")}


@pytest.mark.parametrize("change", [None, "language", "id", "printing", "revoked", "seller", "gcd", "hash", "pending"])
def test_dynamic_cover_stays_bound_to_trusted_exact_edition(change):
    row = entry(); book = catalogue_book(row); language = "English"
    if change == "language": language = "Japanese"
    if change == "id": book["catalogue_id"] = "different"
    if change == "printing": book["printing_number"] = 2
    if change == "revoked": book["attributes"]["cover_rights_status"] = "REVOKED"
    if change == "seller": book["attributes"]["identity_source"] = "SELLER_ENTERED"
    if change == "gcd": book["attributes"]["catalogue_import"]["provider"] = "GCD"
    if change == "hash": book["attributes"]["publisher_reference"]["observed_sha256"] = "x" * 64
    if change == "pending": book["attributes"]["publisher_reference"] = None
    assert bool(book_cover_reference(book, language)) == (change is None)


@pytest.mark.asyncio
async def test_imported_cover_can_be_found_by_scan_and_conflicts_are_rejected():
    row = entry(); db = AsyncMock(); db.fetch.return_value = [catalogue_book(row)]
    observed = {**row["book"], "language": "English"}
    candidates = await catalogue_candidates(db, observed)
    assert len(candidates) == 1 and candidates[0]["image_url"] == row["image_url"]
    assert not candidates[0]["cover_matches_photo"]
    legacy_isbn = next(value for value in barcode_aliases(row["book"]["barcode_gtin"]) if len(value) == 10)
    equivalent = await catalogue_candidates(db, {**observed, "barcode_gtin": legacy_isbn})
    assert len(equivalent) == 1 and equivalent[0]["fields"]["barcode_gtin"] == row["book"]["barcode_gtin"]
    assert await catalogue_candidates(db, {**observed, "printing_number": 2}) == []
    assert await catalogue_candidates(db, {**observed, "language": "Japanese"}) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("size,readonly,reason", [(402304147, "off", "CAPACITY"), (1000, "on", "READ_ONLY"), (399999999, "off", "RESERVE")])
async def test_capacity_and_readonly_pause_before_any_inserts(size, readonly, reason):
    @asynccontextmanager
    async def transaction(): yield
    db = AsyncMock(); db.transaction = MagicMock(side_effect=transaction)
    db.fetchrow.return_value = {"database_bytes": size, "default_read_only": readonly}
    with pytest.raises(ImportPaused, match=reason):
        await apply_batch(db, [entry()], "fixture")
    assert all("insert" not in call.args[0].lower() for call in db.execute.await_args_list)


@pytest.mark.asyncio
async def test_verified_upgrade_quota_has_headroom_and_never_overrides_readonly():
    db = AsyncMock(); db.fetchrow.return_value = {"database_bytes": 402304147, "default_read_only": "off"}
    assert not (await import_capacity(db))["refresh_allowed"]
    upgraded = await import_capacity(db, 1_000_000_000)
    assert upgraded["refresh_allowed"] and upgraded["pause_threshold_bytes"] == 800_000_000
    db.fetchrow.return_value["default_read_only"] = "on"
    assert not (await import_capacity(db, 1_000_000_000))["refresh_allowed"]


@pytest.mark.asyncio
async def test_prh_pages_resume_on_rate_limit_and_never_save_key(tmp_path):
    state = open_download(tmp_path / "download.sqlite"); calls = []
    def handler(request):
        calls.append(request)
        start = int(request.url.params["start"])
        assert request.url.params["api_key"] == "secret-fixture-key"
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": "60"})
        return httpx.Response(200, json={"status": "ok", "data": {"titles": [prh()["title"]] if start == 0 else []}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImportPaused, match="429_RETRY_AFTER_60"):
            await fetch_prh(state, client, api_key="secret-fixture-key", category_id="fixture", interval=0)
        assert get(state, "cursor") == 1
        await fetch_prh(state, client, api_key="secret-fixture-key", category_id="fixture", interval=0)
    output = tmp_path / "export.jsonl"; export_download(state, output)
    assert len(output.read_text().splitlines()) == 1
    assert "secret-fixture-key" not in str(state.execute("select * from download_metadata").fetchall())
    assert "secret-fixture-key" not in output.read_text()
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 503])
async def test_provider_denial_never_follows_redirect_or_retries(status):
    handler = MagicMock(return_value=httpx.Response(status, headers={"Location": "https://evil.example/"}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImportPaused, match=f"HTTP_{status}"):
            await provider_json(client, PRH_URL, params={"api_key": "secret"})
        with pytest.raises(ImportPaused, match="UNTRUSTED"):
            await provider_json(client, "https://www.comics.org.evil.test/api/issue/1/")
    assert handler.call_count == 1


@pytest.mark.asyncio
async def test_provider_cannot_echo_credentials_into_download_checkpoint():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"echo": "secret-fixture-key"}))) as client:
        with pytest.raises(ImportPaused, match="CONTAINS_CREDENTIALS"):
            await provider_json(client, PRH_URL, params={"api_key": "secret-fixture-key"})


@pytest.mark.asyncio
async def test_gcd_issue_download_resume_both_classifications(tmp_path):
    sample = gcd(manga=True); sample["series"]["active_issues"] = [sample["issue"]["api_url"]]
    calls = []
    def handler(request):
        calls.append(str(request.url))
        result = next((sample[k] for k in ("issue", "series", "publisher") if sample[k]["api_url"] == str(request.url)), None)
        return httpx.Response(200, json=result)
    state = open_download(tmp_path / "gcd.sqlite")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        args = dict(username="fixture", password="secret", rules=[sample["classification"]], interval=0)
        first = await fetch_gcd(state, client, max_requests=2, **args)
        assert first["records"] == 0
        second = await fetch_gcd(state, client, max_requests=3, **args)
        assert second["complete"] and second["records"] == 1 and len(calls) == 3
    output = tmp_path / "gcd.jsonl"; export_download(state, output)
    assert normalise("GCD", json.loads(output.read_text()))["book"]["system_code"] == "MANGA"
    state.close()
