from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError


TRUSTED_REFERENCE_HOSTS = {
    "assets.tcgdex.net",
    "onepiece-cardgame.com",
    "www.onepiece-cardgame.com",
    "cards.tcggraph.io",
}

REFERENCE_HASH_CACHE_TTL_SECONDS = 6 * 60 * 60
REFERENCE_HASH_CACHE_MAX_ENTRIES = 2048
REFERENCE_IMAGE_BYTES_CACHE_TTL_SECONDS = 60 * 60
REFERENCE_IMAGE_BYTES_CACHE_MAX_ENTRIES = 48
REFERENCE_IMAGE_BYTES_CACHE_MAX_ITEM_BYTES = 2_000_000
_REFERENCE_HASH_CACHE: OrderedDict[str, tuple[float, tuple[int, ...]]] = OrderedDict()
_REFERENCE_HASH_INFLIGHT: dict[str, asyncio.Task[tuple[int, ...] | None]] = {}
_REFERENCE_IMAGE_BYTES_CACHE: OrderedDict[str, tuple[float, "ReferenceImagePayload"]] = OrderedDict()


def _clear_reference_image_hash_cache() -> None:
    """Test/maintenance hook; production callers should rely on TTL eviction."""
    _REFERENCE_HASH_CACHE.clear()
    _REFERENCE_HASH_INFLIGHT.clear()
    _REFERENCE_IMAGE_BYTES_CACHE.clear()


class RecognitionImageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DecodedRecognitionImage:
    mime_type: str
    data: bytes
    sha256: str
    size_bytes: int
    width: int
    height: int
    hashes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReferenceImagePayload:
    content_type: str
    data: bytes


def _dhash(image: Image.Image, *, size: int = 16) -> int:
    grey = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(grey.getdata())
    value = 0
    for row in range(size):
        start = row * (size + 1)
        for col in range(size):
            value <<= 1
            value |= int(pixels[start + col] > pixels[start + col + 1])
    return value


def _centre_crop(image: Image.Image, fraction: float) -> Image.Image:
    if fraction >= 1.0:
        return image
    width, height = image.size
    crop_width = max(1, round(width * fraction))
    crop_height = max(1, round(height * fraction))
    left = max(0, (width - crop_width) // 2)
    top = max(0, (height - crop_height) // 2)
    return image.crop((left, top, left + crop_width, top + crop_height))


def _fingerprints(image: Image.Image) -> tuple[int, ...]:
    normalized = ImageOps.exif_transpose(image).convert("RGB")
    values: list[int] = []
    for fraction in (1.0, 0.92, 0.84, 0.76):
        crop = _centre_crop(normalized, fraction)
        for angle in (0, 180):
            rotated = crop.rotate(angle, expand=True) if angle else crop
            values.append(_dhash(rotated))
    return tuple(dict.fromkeys(values))


def _open_image(data: bytes) -> tuple[Image.Image, int, int]:
    if not data:
        raise RecognitionImageError("Recognition image is empty")
    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise RecognitionImageError("Recognition image is invalid or unsafe") from exc

    if getattr(image, "is_animated", False):
        raise RecognitionImageError("Animated images are not supported")
    width, height = image.size
    if width < 200 or height < 200:
        raise RecognitionImageError("Recognition image resolution is too low")
    if width * height > 40_000_000:
        raise RecognitionImageError("Recognition image dimensions are too large")
    return image, width, height


def decode_image_data_url(value: str, *, max_bytes: int) -> DecodedRecognitionImage:
    if not isinstance(value, str) or not value.startswith("data:image/"):
        raise RecognitionImageError("Recognition requires an image data URL")
    try:
        header, encoded = value.split(",", 1)
    except ValueError as exc:
        raise RecognitionImageError("Recognition image data URL is malformed") from exc
    if ";base64" not in header:
        raise RecognitionImageError("Recognition image must be base64 encoded")

    mime_type = header[5:].split(";", 1)[0].strip().casefold()
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise RecognitionImageError("Recognition image must be JPEG, PNG or WebP")

    estimated = (len(encoded) * 3) // 4
    if estimated > max_bytes + 3:
        raise RecognitionImageError("Recognition image exceeds the configured size limit")

    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise RecognitionImageError("Recognition image base64 payload is invalid") from exc
    if len(data) > max_bytes:
        raise RecognitionImageError("Recognition image exceeds the configured size limit")

    image, width, height = _open_image(data)
    return DecodedRecognitionImage(
        mime_type=mime_type,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        width=width,
        height=height,
        hashes=_fingerprints(image),
    )


def hash_similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float | None:
    if not left or not right:
        return None
    bits = 16 * 16
    best = 0.0
    for a in left:
        for b in right:
            distance = (a ^ b).bit_count()
            similarity = 1.0 - (distance / bits)
            if similarity > best:
                best = similarity
    return round(max(0.0, min(1.0, best)), 5)


REFERENCE_IMAGE_MAX_REDIRECTS = 3


def _trusted_reference_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return False
    host = parsed.hostname.casefold().rstrip(".")
    return host in TRUSTED_REFERENCE_HOSTS or any(
        host.endswith(f".{trusted}") for trusted in TRUSTED_REFERENCE_HOSTS
    )


def _trusted_reference_redirect(current_url: str, location: str) -> str | None:
    clean = str(location or "").strip()
    if not clean:
        return None
    try:
        target = urljoin(current_url, clean)
    except ValueError:
        return None
    return target if _trusted_reference_url(target) else None


def _cache_reference_image_bytes(url: str, payload: ReferenceImagePayload) -> None:
    if len(payload.data) > REFERENCE_IMAGE_BYTES_CACHE_MAX_ITEM_BYTES:
        return
    _REFERENCE_IMAGE_BYTES_CACHE[url] = (
        time.monotonic() + REFERENCE_IMAGE_BYTES_CACHE_TTL_SECONDS,
        payload,
    )
    _REFERENCE_IMAGE_BYTES_CACHE.move_to_end(url)
    while len(_REFERENCE_IMAGE_BYTES_CACHE) > REFERENCE_IMAGE_BYTES_CACHE_MAX_ENTRIES:
        _REFERENCE_IMAGE_BYTES_CACHE.popitem(last=False)


async def _fetch_reference_image_uncached(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
) -> ReferenceImagePayload | None:
    current = url
    data = b""
    content_type = ""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        ) as client:
            for redirect_count in range(REFERENCE_IMAGE_MAX_REDIRECTS + 1):
                if not _trusted_reference_url(current):
                    return None
                async with client.stream(
                    "GET",
                    current,
                    headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5"},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if redirect_count >= REFERENCE_IMAGE_MAX_REDIRECTS:
                            return None
                        target = _trusted_reference_redirect(
                            current,
                            response.headers.get("location", ""),
                        )
                        if target is None:
                            return None
                        current = target
                        continue

                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
                    if content_type not in {
                        "image/jpeg",
                        "image/png",
                        "image/webp",
                        "image/avif",
                    }:
                        return None
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > max_bytes:
                                return None
                        except ValueError:
                            return None
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            return None
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    break
            else:
                return None
    except httpx.HTTPError:
        return None

    try:
        _open_image(data)
    except RecognitionImageError:
        return None
    return ReferenceImagePayload(content_type=content_type, data=data)


async def reference_image_bytes(
    url: str,
    *,
    max_bytes: int = REFERENCE_IMAGE_BYTES_CACHE_MAX_ITEM_BYTES,
    timeout_seconds: float = 12.0,
) -> ReferenceImagePayload | None:
    """Fetch a trusted card image for authenticated same-origin rendering."""
    if not _trusted_reference_url(url):
        return None

    now = time.monotonic()
    cached = _REFERENCE_IMAGE_BYTES_CACHE.get(url)
    if cached is not None:
        expires_at, payload = cached
        if expires_at > now:
            _REFERENCE_IMAGE_BYTES_CACHE.move_to_end(url)
            return payload
        _REFERENCE_IMAGE_BYTES_CACHE.pop(url, None)

    payload = await _fetch_reference_image_uncached(
        url,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
    )
    if payload is not None:
        _cache_reference_image_bytes(url, payload)
    return payload


async def _reference_image_hashes_uncached(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
) -> tuple[int, ...] | None:
    payload = await _fetch_reference_image_uncached(
        url,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
    )
    if payload is None:
        return None

    _cache_reference_image_bytes(url, payload)
    try:
        image, _, _ = _open_image(payload.data)
    except RecognitionImageError:
        return None
    return _fingerprints(image)


async def reference_image_hashes(
    url: str,
    *,
    max_bytes: int = 10_000_000,
    timeout_seconds: float = 12.0,
) -> tuple[int, ...] | None:
    """Return trusted reference fingerprints with TTL/LRU and in-flight de-duplication."""
    if not _trusted_reference_url(url):
        return None

    now = time.monotonic()
    cached = _REFERENCE_HASH_CACHE.get(url)
    if cached is not None:
        expires_at, hashes = cached
        if expires_at > now:
            _REFERENCE_HASH_CACHE.move_to_end(url)
            return hashes
        _REFERENCE_HASH_CACHE.pop(url, None)

    task = _REFERENCE_HASH_INFLIGHT.get(url)
    if task is None:
        task = asyncio.create_task(
            _reference_image_hashes_uncached(
                url,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )
        )
        _REFERENCE_HASH_INFLIGHT[url] = task

    try:
        hashes = await task
    finally:
        if _REFERENCE_HASH_INFLIGHT.get(url) is task:
            _REFERENCE_HASH_INFLIGHT.pop(url, None)

    # Cache only successful fingerprints. Transient provider/network failures must
    # recover immediately on the next scan rather than becoming negative-cache hits.
    if hashes:
        _REFERENCE_HASH_CACHE[url] = (
            time.monotonic() + REFERENCE_HASH_CACHE_TTL_SECONDS,
            hashes,
        )
        _REFERENCE_HASH_CACHE.move_to_end(url)
        while len(_REFERENCE_HASH_CACHE) > REFERENCE_HASH_CACHE_MAX_ENTRIES:
            _REFERENCE_HASH_CACHE.popitem(last=False)
    return hashes

