from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError


TRUSTED_REFERENCE_HOSTS = {
    "assets.tcgdex.net",
    "onepiece-cardgame.com",
    "www.onepiece-cardgame.com",
}


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


def _trusted_reference_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    return host in TRUSTED_REFERENCE_HOSTS or any(
        host.endswith(f".{trusted}") for trusted in TRUSTED_REFERENCE_HOSTS
    )


async def reference_image_hashes(
    url: str,
    *,
    max_bytes: int = 10_000_000,
    timeout_seconds: float = 12.0,
) -> tuple[int, ...] | None:
    if not _trusted_reference_url(url):
        return None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
        ) as client:
            async with client.stream(
                "GET",
                url,
                headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5"},
            ) as response:
                response.raise_for_status()
                final_url = str(response.url)
                if not _trusted_reference_url(final_url):
                    return None
                content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
                if content_type and content_type not in {
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                    "image/avif",
                }:
                    return None
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        return None
                    chunks.append(chunk)
    except (httpx.HTTPError, RecognitionImageError):
        return None

    data = b"".join(chunks)
    try:
        image, _, _ = _open_image(data)
    except RecognitionImageError:
        return None
    return _fingerprints(image)
