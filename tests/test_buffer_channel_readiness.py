import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app import buffer_channel_readiness as r


ORG = "6ac1a59ca59739d7c3e08601"


def channel(**changes):
    value = {
        "id": "youtube-channel-123",
        "organizationId": ORG,
        "name": "Drop Rate",
        "displayName": "Drop Rate",
        "service": "youtube",
        "allowedActions": ["scheduleUpdates"],
        "isDisconnected": False,
        "isLocked": False,
        "isQueuePaused": False,
        "timezone": "Europe/London",
    }
    value.update(changes)
    return value


@pytest.mark.asyncio
async def test_readiness_fetches_exact_org_and_returns_sanitised_channel():
    seen = {}

    def respond(request):
        assert request.method == "POST"
        assert str(request.url) == r.BUFFER_ENDPOINT
        assert request.headers["authorization"] == "Bearer fixture-buffer-key"
        body = json.loads(request.content)
        seen.update(body["variables"])
        return httpx.Response(
            200,
            json={"data": {"channels": [channel()]}},
        )

    result = await r.get_youtube_readiness(
        "fixture-buffer-key",
        organization_id=ORG,
        transport=httpx.MockTransport(respond),
    )
    assert seen == {"input": {"organizationId": ORG}}
    assert result["ready"] is True
    assert result["reason"] is None
    assert result["channel"]["id"] == "youtube-channel-123"
    assert result["channel"]["service"] == "youtube"
    assert "authorization" not in str(result).lower()


@pytest.mark.parametrize(
    ("change", "blocker"),
    [
        ({"isDisconnected": True}, "DISCONNECTED"),
        ({"isLocked": True}, "LOCKED"),
        ({"isQueuePaused": True}, "QUEUE_PAUSED"),
        ({"allowedActions": []}, "SCHEDULE_PERMISSION_MISSING"),
    ],
)
def test_not_ready_states_are_explicit(change, blocker):
    result = r.select_youtube_channel([channel(**change)], organization_id=ORG)
    assert result["ready"] is False
    assert result["reason"] == "BUFFER_YOUTUBE_CHANNEL_NOT_READY"
    assert blocker in result["blockers"]


def test_missing_and_ambiguous_channels_fail_closed():
    with pytest.raises(r.BufferReadinessError, match="BUFFER_YOUTUBE_CHANNEL_MISSING"):
        r.select_youtube_channel([channel(service="instagram")], organization_id=ORG)

    with pytest.raises(r.BufferReadinessError, match="BUFFER_YOUTUBE_CHANNEL_AMBIGUOUS"):
        r.select_youtube_channel([channel(id="a"), channel(id="b")], organization_id=ORG)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["http", "graphql", "invalid", "oversized"])
async def test_provider_failures_are_sanitised(kind):
    def respond(request):
        if kind == "http":
            return httpx.Response(401, text="super-secret-provider-message")
        if kind == "graphql":
            return httpx.Response(
                200,
                json={"errors": [{"message": "super-secret-provider-message"}]},
            )
        if kind == "oversized":
            return httpx.Response(
                200,
                content=b"x" * (r.MAX_RESPONSE_BYTES + 1),
            )
        return httpx.Response(200, text="not-json super-secret-provider-message")

    with pytest.raises(r.BufferReadinessError) as exc:
        await r.get_youtube_readiness(
            "fixture-buffer-key",
            organization_id=ORG,
            transport=httpx.MockTransport(respond),
        )
    assert "secret" not in str(exc.value).lower()
    assert "fixture-buffer-key" not in str(exc.value)


def test_operator_script_never_prints_runtime_key(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "backend")
    env["TCG_BUFFER_API_KEY"] = ""

    result = subprocess.run(
        [sys.executable, str(root / "backend/scripts/buffer_youtube_readiness.py")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("DROP_RATE_BUFFER_YOUTUBE_READINESS ")
    payload = json.loads(result.stdout.split(" ", 1)[1])
    assert payload["probe_version"] == "buffer-youtube-readiness-v1"
    assert payload["ready"] is False
    assert payload["reason"] == "BUFFER_RUNTIME_CREDENTIAL_MISSING"
    assert "TCG_BUFFER_API_KEY" not in result.stdout
