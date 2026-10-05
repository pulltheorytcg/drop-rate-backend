"""Deterministic platform-native media dimensions for Drop Rate social content.

These are rendering contracts, not engagement guarantees. Creative generation may
vary in composition, but publishable media must match one exact target rather than
being stretched, padded, or approximately resized after generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MediaKind = Literal["image", "video"]


@dataclass(frozen=True)
class SocialFormat:
    key: str
    channel: str
    surface: str
    media_kind: MediaKind
    width: int
    height: int
    aspect_ratio: str

    @property
    def ratio_value(self) -> float:
        left, right = self.aspect_ratio.split(":", 1)
        return int(left) / int(right)


FORMATS: dict[str, SocialFormat] = {
    "instagram_feed_image": SocialFormat(
        key="instagram_feed_image",
        channel="instagram",
        surface="feed",
        media_kind="image",
        width=1080,
        height=1350,
        aspect_ratio="4:5",
    ),
    "instagram_reel": SocialFormat(
        key="instagram_reel",
        channel="instagram",
        surface="reel",
        media_kind="video",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
    ),
    "instagram_story": SocialFormat(
        key="instagram_story",
        channel="instagram",
        surface="story",
        media_kind="video",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
    ),
    "tiktok_photo": SocialFormat(
        key="tiktok_photo",
        channel="tiktok",
        surface="photo",
        media_kind="image",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
    ),
    "tiktok_video": SocialFormat(
        key="tiktok_video",
        channel="tiktok",
        surface="video",
        media_kind="video",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
    ),
    "youtube_short": SocialFormat(
        key="youtube_short",
        channel="youtube",
        surface="short",
        media_kind="video",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
    ),
}


def get_format(key: str) -> SocialFormat:
    try:
        return FORMATS[key]
    except KeyError as exc:
        raise ValueError("SOCIAL_FORMAT_UNKNOWN") from exc


def validate_exact_dimensions(key: str, *, width: int, height: int) -> None:
    spec = get_format(key)
    if width != spec.width or height != spec.height:
        raise ValueError(
            f"SOCIAL_FORMAT_DIMENSIONS_INVALID:{key}:{width}x{height}"
        )


def prompt_contract() -> str:
    ordered = [
        FORMATS["instagram_feed_image"],
        FORMATS["instagram_reel"],
        FORMATS["instagram_story"],
        FORMATS["tiktok_photo"],
        FORMATS["tiktok_video"],
        FORMATS["youtube_short"],
    ]
    lines = [
        "PLATFORM-NATIVE MEDIA CONTRACT:",
        "Never resize one finished composition across channels. Recompose from the same brief for each destination.",
    ]
    lines.extend(
        f"- {item.key}: {item.width}x{item.height} px ({item.aspect_ratio}), {item.media_kind}."
        for item in ordered
    )
    lines.append(
        "Do not introduce approximate dimensions, letterboxing, decorative padding, or silent cropping as a substitute for the required canvas."
    )
    return "\n".join(lines)
