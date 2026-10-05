import hashlib
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.youtube_pilot_contract import (
    YouTubePilotContractError,
    YouTubePilotManifest,
    buffer_create_input,
    manifest_digest,
    normalise_youtube_post,
    verify_approved_video,
    verify_buffer_channel,
)


ORG = "6ac1a59ca59739d7c3e08601"
CHANNEL = "6ac1a694ea19ca0bde6c8ba3"
ACTOR = "11111111-1111-4111-8111-111111111111"
PILOT = "22222222-2222-4222-8222-222222222222"


def mp4_bytes():
    # Minimal byte shape for contract tests: size + ftyp box marker + deterministic payload.
    return b"\x00\x00\x00\x18ftypisom" + (b"drop-rate-youtube-pilot" * 8)


def manifest_dict(body=None):
    body = mp4_bytes() if body is None else body
    return {
        "schema_version": 1,
        "pilot_id": PILOT,
        "actor_user_id": ACTOR,
        "organization_id": ORG,
        "expires_at": "2026-10-06T20:00:00+00:00",
        "channel": {"service": "youtube", "channel_id": CHANNEL},
        "asset": {
            "url": "https://cdn.shopify.com/s/files/1/1038/7482/2491/files/drop-rate-youtube-pilot.mp4",
            "mime_type": "video/mp4",
            "sha256": hashlib.sha256(body).hexdigest(),
            "byte_count": len(body),
            "width": 1080,
            "height": 1920,
            "duration_ms": 30_000,
            "has_audio": True,
            "narration_approved": True,
            "captions_approved": True,
        },
        "content": {
            "title": "Drop Rate Market Watch",
            "description": "Real card. Real market data. Drop Rate.",
            "category_id": "20",
            "privacy": "public",
            "made_for_kids": False,
            "notify_subscribers": False,
            "embeddable": True,
            "license": "youtube",
            "ai_assisted": True,
            "is_ai_generated": True,
        },
        "approval": {
            "approved": True,
            "approved_by_user_id": ACTOR,
            "approved_at": "2026-10-05T08:00:00+01:00",
            "reference": "explicit founder approval for this exact video revision",
        },
    }


def manifest(body=None):
    return YouTubePilotManifest.model_validate(manifest_dict(body))


def test_manifest_is_strict_and_revision_digest_is_stable():
    value = manifest()
    assert len(manifest_digest(value)) == 64

    extra = manifest_dict()
    extra["surprise"] = True
    with pytest.raises(ValidationError):
        YouTubePilotManifest.model_validate(extra)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda v: v["asset"].update({"url": "https://example.com/pilot.mp4"}),
        lambda v: v["asset"].update({"url": "http://cdn.shopify.com/s/files/1/1038/7482/2491/files/x.mp4"}),
        lambda v: v["asset"].update({"width": 1000, "height": 1920}),
        lambda v: v["asset"].update({"duration_ms": 180_001}),
        lambda v: v["asset"].update({"has_audio": False}),
        lambda v: v["asset"].update({"narration_approved": False}),
        lambda v: v["asset"].update({"captions_approved": False}),
        lambda v: v["content"].update({"category_id": "999"}),
        lambda v: v["content"].update({"privacy": "unlisted"}),
        lambda v: v["content"].update({"notify_subscribers": True}),
        lambda v: v["approval"].update({"approved_by_user_id": "33333333-3333-4333-8333-333333333333"}),
    ],
)
def test_manifest_fails_closed_on_unapproved_media_or_metadata(mutator):
    value = manifest_dict()
    mutator(value)
    with pytest.raises(ValidationError):
        YouTubePilotManifest.model_validate(value)


def test_buffer_payload_is_exact_and_immediate_but_not_sent_here():
    value = manifest()
    payload = buffer_create_input(value)
    assert payload == {
        "channelId": CHANNEL,
        "text": "Real card. Real market data. Drop Rate.",
        "mode": "shareNow",
        "schedulingType": "automatic",
        "saveToDraft": False,
        "needsApproval": False,
        "aiAssisted": True,
        "assets": [{"video": {"url": value.asset.url}}],
        "metadata": {
            "youtube": {
                "title": "Drop Rate Market Watch",
                "categoryId": "20",
                "embeddable": True,
                "isAiGenerated": True,
                "license": "youtube",
                "madeForKids": False,
                "notifySubscribers": False,
                "privacy": "public",
            }
        },
    }


def buffer_channel(**changes):
    value = {
        "id": CHANNEL,
        "organizationId": ORG,
        "service": "youtube",
        "name": "Drop Rate ",
        "allowedActions": ["scheduleUpdates", "viewChannel"],
        "isDisconnected": False,
        "isLocked": False,
        "isQueuePaused": False,
    }
    value.update(changes)
    return value


def test_channel_identity_binds_ids_not_mutable_display_name():
    result = verify_buffer_channel(buffer_channel(name="anything can change"), manifest())
    assert result["ready"] is True
    assert result["channel_id"] == CHANNEL


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "aaaaaaaaaaaaaaaaaaaaaaaa"},
        {"organizationId": "bbbbbbbbbbbbbbbbbbbbbbbb"},
        {"service": "tiktok"},
        {"isDisconnected": True},
        {"isLocked": True},
        {"isQueuePaused": True},
        {"allowedActions": ["viewChannel"]},
    ],
)
def test_channel_mismatch_or_not_ready_fails_closed(changes):
    with pytest.raises(YouTubePilotContractError):
        verify_buffer_channel(buffer_channel(**changes), manifest())


@pytest.mark.asyncio
async def test_video_readback_requires_exact_approved_bytes():
    body = mp4_bytes()
    value = manifest(body)
    seen = {}

    def respond(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "video/mp4", "content-length": str(len(body))},
            content=body,
        )

    result = await verify_approved_video(value, transport=httpx.MockTransport(respond))
    assert seen == {"method": "GET", "url": value.asset.url}
    assert result == {
        "sha256": hashlib.sha256(body).hexdigest(),
        "byte_count": len(body),
        "mime_type": "video/mp4",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bytes", "length", "mime", "redirect", "container"])
async def test_video_readback_rejects_changed_or_ambiguous_media(mode):
    approved = mp4_bytes()
    value = manifest(approved)

    def respond(request):
        body = approved
        status = 200
        headers = {"content-type": "video/mp4", "content-length": str(len(body))}
        if mode == "bytes":
            body = body[:-1] + b"X"
            headers["content-length"] = str(len(body))
        elif mode == "length":
            body = body + b"extra"
            headers["content-length"] = str(len(body))
        elif mode == "mime":
            headers["content-type"] = "application/octet-stream"
        elif mode == "redirect":
            status = 302
        elif mode == "container":
            body = b"not-an-mp4" + approved
            headers["content-length"] = str(len(body))
        return httpx.Response(status, headers=headers, content=body)

    with pytest.raises(YouTubePilotContractError):
        await verify_approved_video(value, transport=httpx.MockTransport(respond))


def delivered_post(**changes):
    value = {
        "id": "buffer-youtube-post-1",
        "channelId": CHANNEL,
        "channelService": "youtube",
        "text": "Real card. Real market data. Drop Rate.",
        "status": "sent",
        "schedulingType": "automatic",
        "shareMode": "shareNow",
        "sentAt": "2026-10-05T08:30:00+01:00",
        "externalLink": "https://www.youtube.com/shorts/abc123",
    }
    value.update(changes)
    return value


def test_delivery_normalisation_accepts_only_youtube_identity_and_urls():
    result = normalise_youtube_post(delivered_post(), manifest())
    assert result["state"] == "DELIVERED"
    assert result["delivery_reported"] is True
    assert result["public_visibility_verified"] is False

    with pytest.raises(YouTubePilotContractError):
        normalise_youtube_post(
            delivered_post(externalLink="https://tiktok.com/@dropratetcg/video/123"),
            manifest(),
        )


def test_contract_module_has_no_live_route_or_buffer_mutation():
    import app.youtube_pilot_contract as module

    source = Path(module.__file__).read_text()
    assert not hasattr(module, "router")
    assert "createPost(" not in source
    assert "Authorization" not in source
