"""Fail-closed contract for a future explicitly approved YouTube Shorts pilot.

This module has no FastAPI route, no Buffer client and no publishing mutation.
It validates/binds the exact approved video and constructs the provider input
that a separately reviewed publishing adapter may later consume.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


SHOPIFY_FILES_HOST = "cdn.shopify.com"
SHOPIFY_FILES_PREFIX = "/s/files/1/1038/7482/2491/files/"
MAX_VIDEO_BYTES = 512 * 1024 * 1024
MAX_DURATION_MS = 180_000
YOUTUBE_CATEGORY_IDS = {
    "1", "2", "10", "15", "17", "19", "20", "22", "23", "24",
    "25", "26", "27", "28", "29",
}
YOUTUBE_DELIVERY_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}


class YouTubePilotContractError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class YouTubeChannelBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    service: Literal["youtube"]
    channel_id: str = Field(pattern=r"^[0-9a-f]{24}$")


class ApprovedYouTubeVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: str = Field(min_length=1, max_length=2048)
    mime_type: Literal["video/mp4"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0, le=MAX_VIDEO_BYTES)
    width: int = Field(ge=720, le=2160)
    height: int = Field(ge=1280, le=3840)
    duration_ms: int = Field(gt=0, le=MAX_DURATION_MS)
    has_audio: Literal[True]
    narration_approved: Literal[True]
    captions_approved: Literal[True]

    @model_validator(mode="after")
    def validate_asset(self) -> "ApprovedYouTubeVideo":
        parts = urlsplit(self.url)
        if (
            parts.scheme != "https"
            or parts.hostname != SHOPIFY_FILES_HOST
            or parts.username
            or parts.password
            or not parts.path.startswith(SHOPIFY_FILES_PREFIX)
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Video URL is not on the approved Shopify Files host")
        if self.width * 16 != self.height * 9:
            raise ValueError("Video must use an exact 9:16 aspect ratio")
        return self


class ApprovedYouTubeContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)
    category_id: str
    privacy: Literal["public"]
    made_for_kids: Literal[False]
    notify_subscribers: Literal[False]
    embeddable: Literal[True]
    license: Literal["youtube"]
    ai_assisted: Literal[True]
    is_ai_generated: bool

    @model_validator(mode="after")
    def validate_category(self) -> "ApprovedYouTubeContent":
        if self.category_id not in YOUTUBE_CATEGORY_IDS:
            raise ValueError("Unsupported YouTube category")
        return self


class FounderApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    approved: Literal[True]
    approved_by_user_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    approved_at: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_timestamp(self) -> "FounderApproval":
        try:
            parsed = datetime.fromisoformat(self.approved_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Approval timestamp must be ISO 8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("Approval timestamp must include a timezone")
        return self


class YouTubePilotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    pilot_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    actor_user_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    organization_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    expires_at: str = Field(min_length=1, max_length=64)
    channel: YouTubeChannelBinding
    asset: ApprovedYouTubeVideo
    content: ApprovedYouTubeContent
    approval: FounderApproval

    @model_validator(mode="after")
    def validate_manifest(self) -> "YouTubePilotManifest":
        if self.approval.approved_by_user_id != self.actor_user_id:
            raise ValueError("Approver must match the bound pilot actor")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Expiry must be ISO 8601") from exc
        if expiry.tzinfo is None:
            raise ValueError("Expiry must include a timezone")
        return self


def canonical(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def manifest_digest(manifest: YouTubePilotManifest) -> str:
    return hashlib.sha256(canonical(manifest)).hexdigest()


def buffer_create_input(manifest: YouTubePilotManifest) -> dict:
    """Build the exact future Buffer createPost input; this does not send it."""
    return {
        "channelId": manifest.channel.channel_id,
        "text": manifest.content.description,
        "mode": "shareNow",
        "schedulingType": "automatic",
        "saveToDraft": False,
        "needsApproval": False,
        "aiAssisted": manifest.content.ai_assisted,
        "assets": [{"video": {"url": manifest.asset.url}}],
        "metadata": {
            "youtube": {
                "title": manifest.content.title,
                "categoryId": manifest.content.category_id,
                "embeddable": manifest.content.embeddable,
                "isAiGenerated": manifest.content.is_ai_generated,
                "license": manifest.content.license,
                "madeForKids": manifest.content.made_for_kids,
                "notifySubscribers": manifest.content.notify_subscribers,
                "privacy": manifest.content.privacy,
            }
        },
    }


def verify_buffer_channel(channel: dict, manifest: YouTubePilotManifest) -> dict:
    if not isinstance(channel, dict):
        raise YouTubePilotContractError("BUFFER_YOUTUBE_CHANNEL_MISSING")
    if (
        channel.get("id") != manifest.channel.channel_id
        or channel.get("organizationId") != manifest.organization_id
        or channel.get("service") != "youtube"
    ):
        raise YouTubePilotContractError("BUFFER_YOUTUBE_CHANNEL_IDENTITY_MISMATCH")
    if any(
        channel.get(key) is not False
        for key in ("isDisconnected", "isLocked", "isQueuePaused")
    ):
        raise YouTubePilotContractError("BUFFER_YOUTUBE_CHANNEL_NOT_READY")
    allowed = channel.get("allowedActions")
    if not isinstance(allowed, list) or "scheduleUpdates" not in allowed:
        raise YouTubePilotContractError("BUFFER_YOUTUBE_CHANNEL_NOT_READY")
    return {
        "channel_id": manifest.channel.channel_id,
        "organization_id": manifest.organization_id,
        "service": "youtube",
        "ready": True,
    }


async def verify_approved_video(
    manifest: YouTubePilotManifest,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Read the approved file only and require exact bytes; never uploads it."""
    asset = manifest.asset
    digest = hashlib.sha256()
    byte_count = 0
    header = bytearray()

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            transport=transport,
        ) as client:
            async with client.stream(
                "GET",
                asset.url,
                headers={"Accept": "video/mp4"},
            ) as response:
                if response.status_code != 200:
                    raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_NOT_AVAILABLE")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type != asset.mime_type:
                    raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_MIME_CHANGED")
                declared_length = response.headers.get("content-length")
                if declared_length:
                    try:
                        declared = int(declared_length)
                    except ValueError:
                        raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_LENGTH_INVALID") from None
                    if declared != asset.byte_count or declared > MAX_VIDEO_BYTES:
                        raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_LENGTH_CHANGED")

                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    if len(header) < 16:
                        header.extend(chunk[: 16 - len(header)])
                    byte_count += len(chunk)
                    if byte_count > MAX_VIDEO_BYTES or byte_count > asset.byte_count:
                        raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_LENGTH_CHANGED")
                    digest.update(chunk)
    except YouTubePilotContractError:
        raise
    except httpx.HTTPError as exc:
        raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_UNVERIFIED") from exc

    if len(header) < 8 or bytes(header[4:8]) != b"ftyp":
        raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_CONTAINER_CHANGED")
    if byte_count != asset.byte_count:
        raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_LENGTH_CHANGED")
    actual = digest.hexdigest()
    if actual != asset.sha256:
        raise YouTubePilotContractError("YOUTUBE_PILOT_VIDEO_BYTES_CHANGED")
    return {"sha256": actual, "byte_count": byte_count, "mime_type": asset.mime_type}


def normalise_youtube_post(post: dict, manifest: YouTubePilotManifest) -> dict:
    if (
        not isinstance(post, dict)
        or post.get("channelId") != manifest.channel.channel_id
        or post.get("channelService") != "youtube"
        or post.get("text") != manifest.content.description
        or not isinstance(post.get("id"), str)
        or not post.get("id")
        or len(post["id"]) > 100
    ):
        raise YouTubePilotContractError("BUFFER_YOUTUBE_POST_IDENTITY_MISMATCH")
    if post.get("schedulingType") != "automatic" or post.get("shareMode") != "shareNow":
        raise YouTubePilotContractError("BUFFER_YOUTUBE_WRONG_PUBLISHING_MODE")

    status = post.get("status")
    state = {
        "sent": "DELIVERED",
        "error": "FAILED",
        "sending": "SENDING",
        "scheduled": "ACCEPTED",
        "buffer": "ACCEPTED",
        "draft": "BLOCKED",
        "needs_approval": "BLOCKED",
    }.get(status)
    if state is None:
        raise YouTubePilotContractError("BUFFER_YOUTUBE_UNKNOWN_POST_STATUS")

    link = post.get("externalLink")
    if link:
        if not isinstance(link, str):
            raise YouTubePilotContractError("BUFFER_YOUTUBE_INVALID_DELIVERY_URL")
        parts = urlsplit(link)
        if (
            parts.scheme != "https"
            or parts.hostname not in YOUTUBE_DELIVERY_HOSTS
            or parts.username
            or parts.password
        ):
            raise YouTubePilotContractError("BUFFER_YOUTUBE_INVALID_DELIVERY_URL")

    sent_at = post.get("sentAt")
    if state == "DELIVERED":
        try:
            when = datetime.fromisoformat(str(sent_at).replace("Z", "+00:00"))
            if when.tzinfo is None:
                raise ValueError
        except (TypeError, ValueError):
            raise YouTubePilotContractError("BUFFER_YOUTUBE_SENT_WITHOUT_TIMESTAMP") from None

    return {
        "state": state,
        "post_id": post["id"],
        "provider_status": status,
        "sent_at": sent_at,
        "external_url": link,
        "delivery_reported": state == "DELIVERED",
        "public_visibility_verified": False,
    }
