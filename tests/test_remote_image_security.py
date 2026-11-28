from __future__ import annotations

from pathlib import Path

import pytest

from app.api import (
    _fetch_inventory_image,
    _inventory_image_direct_browser_allowed,
    _inventory_image_direct_browser_url,
    _inventory_image_redirect_target,
    _inventory_image_source_allowed,
)
from app.recognition_images import (
    _trusted_reference_redirect,
    _trusted_reference_url,
)


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "api.py"
RECOGNITION_IMAGES = ROOT / "backend" / "app" / "recognition_images.py"


class _FakeResponse:
    def __init__(self, status_code: int, *, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]):
        self.responses = list(responses)
        self.calls: list[str] = []

    def stream(self, method: str, url: str):
        assert method == "GET"
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("unexpected outbound request")
        return self.responses.pop(0)


def test_inventory_image_allowlist_rejects_unsafe_url_components() -> None:
    assert _inventory_image_source_allowed("https://assets.tcgdex.net/card.png")
    assert _inventory_image_source_allowed("https://x.shopifycdn.com/card.webp")
    assert _inventory_image_source_allowed("https://cards.tcggraph.io/op/card.webp")
    assert not _inventory_image_source_allowed("http://assets.tcgdex.net/card.png")
    assert not _inventory_image_source_allowed("https://127.0.0.1/card.png")
    assert not _inventory_image_source_allowed("https://user:pass@assets.tcgdex.net/card.png")
    assert not _inventory_image_source_allowed("https://assets.tcgdex.net/card.png#fragment")


def test_inventory_direct_image_fast_path_is_strictly_allowlisted() -> None:
    assert _inventory_image_direct_browser_allowed("https://cdn.shopify.com/s/files/card.png")
    assert _inventory_image_direct_browser_allowed("https://x.shopifycdn.com/card.webp")
    assert _inventory_image_direct_browser_allowed("https://x.shopifycdn.net/card.webp")
    assert _inventory_image_direct_browser_allowed("https://assets.tcgdex.net/card.png")
    assert not _inventory_image_direct_browser_allowed(
        "https://en.onepiece-cardgame.com/images/card.png"
    )
    assert not _inventory_image_direct_browser_allowed(
        "https://www.onepiece-cardgame.com/images/card.png"
    )
    assert not _inventory_image_direct_browser_allowed("https://cardtrader.com/card.png")
    assert not _inventory_image_direct_browser_allowed("https://www.optcgapi.com/card.png")
    assert not _inventory_image_direct_browser_allowed("https://cards.tcggraph.io/op/card.webp")
    assert not _inventory_image_direct_browser_allowed("http://cdn.shopify.com/card.png")
    assert not _inventory_image_direct_browser_allowed("https://evil.example/card.png")
    assert not _inventory_image_direct_browser_allowed(
        "https://user:pass@cdn.shopify.com/card.png"
    )


def test_inventory_direct_tcgdex_grid_url_prefers_low_webp() -> None:
    assert (
        _inventory_image_direct_browser_url(
            "https://assets.tcgdex.net/en/me/me02/047/high.webp"
        )
        == "https://assets.tcgdex.net/en/me/me02/047/low.webp"
    )
    assert (
        _inventory_image_direct_browser_url(
            "https://cdn.shopify.com/s/files/card.png"
        )
        == "https://cdn.shopify.com/s/files/card.png"
    )
    assert (
        _inventory_image_direct_browser_url(
            "https://en.onepiece-cardgame.com/images/card.png"
        )
        is None
    )


def test_inventory_image_redirect_must_remain_on_allowlisted_https_host() -> None:
    current = "https://assets.tcgdex.net/card.png"
    assert _inventory_image_redirect_target(current, "/next.png") == "https://assets.tcgdex.net/next.png"
    assert _inventory_image_redirect_target(current, "https://cdn.shopify.com/card.png") == "https://cdn.shopify.com/card.png"
    assert _inventory_image_redirect_target(current, "http://169.254.169.254/latest/meta-data") is None
    assert _inventory_image_redirect_target(current, "https://evil.example/card.png") is None


@pytest.mark.asyncio
async def test_inventory_image_fetch_never_follows_redirect_to_untrusted_host() -> None:
    client = _FakeClient([
        _FakeResponse(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
        ),
    ])
    result = await _fetch_inventory_image(
        client,  # type: ignore[arg-type]
        "https://assets.tcgdex.net/card.png",
    )
    assert result is None
    assert client.calls == ["https://assets.tcgdex.net/card.png"]


@pytest.mark.asyncio
async def test_inventory_image_fetch_streams_valid_bounded_payload() -> None:
    client = _FakeClient([
        _FakeResponse(
            200,
            headers={"content-type": "image/webp", "content-length": "6"},
            chunks=[b"abc", b"def"],
        ),
    ])
    result = await _fetch_inventory_image(
        client,  # type: ignore[arg-type]
        "https://assets.tcgdex.net/card.webp",
    )
    assert result == (b"abcdef", "image/webp")


@pytest.mark.asyncio
async def test_inventory_image_bytes_are_reused_for_the_same_source(monkeypatch) -> None:
    import app.api as api
    monkeypatch.setattr(api, "_INVENTORY_IMAGE_CACHE", api.OrderedDict())
    client = _FakeClient([
        _FakeResponse(200, headers={"content-type": "image/webp", "content-length": "3"}, chunks=[b"abc"]),
    ])
    url = "https://cdn.shopify.com/s/files/1/card.webp"
    assert await _fetch_inventory_image(client, url) == (b"abc", "image/webp")  # type: ignore[arg-type]
    assert await _fetch_inventory_image(client, url) == (b"abc", "image/webp")  # type: ignore[arg-type]
    assert client.calls == [url]


@pytest.mark.asyncio
async def test_inventory_image_cache_expires_skips_failures_and_is_bounded(monkeypatch) -> None:
    import app.api as api
    monkeypatch.setattr(api, "_INVENTORY_IMAGE_CACHE", api.OrderedDict())
    url = "https://cdn.shopify.com/s/files/1/card.webp"
    failing = _FakeClient([_FakeResponse(404)])
    assert await _fetch_inventory_image(failing, url) is None  # type: ignore[arg-type]
    assert url not in api._INVENTORY_IMAGE_CACHE
    api._remember_inventory_image(url, b"old", "image/webp")
    now = api.time.monotonic()
    monkeypatch.setattr(api.time, "monotonic", lambda: now + api.INVENTORY_IMAGE_CACHE_TTL + 1)
    assert api._cached_inventory_image(url) is None
    monkeypatch.setattr(api, "INVENTORY_IMAGE_CACHE_MAX_BYTES", 5)
    api._remember_inventory_image("https://cdn.shopify.com/a.webp", b"aaa", "image/webp")
    api._remember_inventory_image("https://cdn.shopify.com/b.webp", b"bbb", "image/webp")
    assert list(api._INVENTORY_IMAGE_CACHE) == ["https://cdn.shopify.com/b.webp"]


@pytest.mark.asyncio
async def test_a_cached_image_is_never_served_for_an_untrusted_host(monkeypatch) -> None:
    import app.api as api
    monkeypatch.setattr(api, "_INVENTORY_IMAGE_CACHE", api.OrderedDict())
    api._INVENTORY_IMAGE_CACHE["https://evil.example/card.png"] = (api.time.monotonic() + 60, b"x", "image/png")
    client = _FakeClient([])
    assert await _fetch_inventory_image(client, "https://evil.example/card.png") is None  # type: ignore[arg-type]
    assert client.calls == []


def test_recognition_reference_redirect_must_stay_on_trusted_host() -> None:
    current = "https://assets.tcgdex.net/card.png"
    assert _trusted_reference_url(current)
    assert _trusted_reference_url("https://cards.tcggraph.io/op/card.webp")
    assert _trusted_reference_redirect(current, "/next.png") == "https://assets.tcgdex.net/next.png"
    assert _trusted_reference_redirect(current, "http://127.0.0.1/private") is None
    assert _trusted_reference_redirect(current, "https://evil.example/card.png") is None
    assert not _trusted_reference_url("https://user:pass@assets.tcgdex.net/card.png")


def test_remote_image_clients_disable_automatic_redirect_following() -> None:
    api_source = API.read_text()
    recognition_source = RECOGNITION_IMAGES.read_text()
    assert "follow_redirects=True" not in api_source[
        api_source.index("async def inventory_card_image("):
        api_source.index('@router.patch("/inventory/{inventory_id}"')
    ]
    fetch_block = recognition_source[
        recognition_source.index("async def _fetch_reference_image_uncached("):
        recognition_source.index("async def reference_image_bytes(")
    ]
    assert "follow_redirects=True" not in fetch_block
    assert "follow_redirects=False" in fetch_block
    assert "_trusted_reference_redirect(" in fetch_block


@pytest.mark.asyncio
@pytest.mark.parametrize('publisher,body_kind,declared_mime,accepted', [
    (True,'JPEG',None,True),(True,'HTML',None,False),(True,'SVG',None,False),
    (True,'GIF',None,False),(True,'JPEG','text/html',False),(False,'JPEG',None,False)])
async def test_missing_publisher_mime_requires_valid_bounded_raster(monkeypatch,publisher,body_kind,declared_mime,accepted):
    import io
    import httpx
    from PIL import Image
    from app import recognition_images as images
    output = io.BytesIO()
    if body_kind in {'JPEG','GIF'}:
        Image.new('RGB',(220,300),'navy').save(output,format=body_kind)
        data=output.getvalue()
    else:
        data=b'<html>not an image</html>' if body_kind=='HTML' else b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    headers={'content-type':declared_mime} if declared_mime else {}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=data,headers=headers))) as client:
        monkeypatch.setattr(images,'_reference_http_client',lambda:client)
        url='https://dw9to29mmj727.cloudfront.net/products/1974710025.jpg' if publisher else 'https://assets.tcgdex.net/card.jpg'
        result=await images._fetch_reference_image_uncached(url,max_bytes=200_000,timeout_seconds=2)
    assert (result is not None)==accepted
    if accepted:assert result.content_type=='image/jpeg' and result.data==data
