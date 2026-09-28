from __future__ import annotations

from pathlib import Path

import pytest

from app.api import (
    _fetch_inventory_image,
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
    assert not _inventory_image_source_allowed("http://assets.tcgdex.net/card.png")
    assert not _inventory_image_source_allowed("https://127.0.0.1/card.png")
    assert not _inventory_image_source_allowed("https://user:pass@assets.tcgdex.net/card.png")
    assert not _inventory_image_source_allowed("https://assets.tcgdex.net/card.png#fragment")


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


def test_recognition_reference_redirect_must_stay_on_trusted_host() -> None:
    current = "https://assets.tcgdex.net/card.png"
    assert _trusted_reference_url(current)
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
