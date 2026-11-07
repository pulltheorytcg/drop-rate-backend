import json

import httpx
import pytest

from app import buffer_post_metrics as m


POST = "buffer-post-123"
CHANNEL = "buffer-channel-123"


@pytest.mark.asyncio
async def test_reads_metrics_with_identity_and_freshness():
    def respond(request):
        assert request.method == "POST"
        assert str(request.url) == m.BUFFER_ENDPOINT
        assert request.headers["authorization"] == "Bearer fixture-buffer-key"
        body = json.loads(request.content)
        assert body["variables"] == {"input": {"id": POST}}
        return httpx.Response(
            200,
            json={
                "data": {
                    "post": {
                        "id": POST,
                        "channelId": CHANNEL,
                        "channelService": "tiktok",
                        "status": "sent",
                        "sentAt": "2026-10-04T18:40:08.542Z",
                        "metrics": [
                            {"type": "views", "name": "Views", "value": 12, "unit": "count"},
                            {"type": "reactions", "name": "Reactions", "value": 1, "unit": "count"},
                        ],
                        "metricsUpdatedAt": "2026-10-05T03:00:00Z",
                    }
                }
            },
        )

    result = await m.get_post_metrics(
        "fixture-buffer-key",
        post_id=POST,
        expected_channel_id=CHANNEL,
        expected_service="tiktok",
        transport=httpx.MockTransport(respond),
    )
    assert result["metrics_available"] is True
    assert result["metrics_updated_at"] == "2026-10-05T03:00:00Z"
    assert result["metrics"][0]["type"] == "views"
    assert "fixture-buffer-key" not in str(result)


@pytest.mark.asyncio
async def test_null_metrics_are_unknown_not_zero():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "post": {
                        "id": POST,
                        "channelId": CHANNEL,
                        "channelService": "instagram",
                        "status": "sent",
                        "sentAt": "2026-10-04T18:38:32.980Z",
                        "metrics": None,
                        "metricsUpdatedAt": None,
                    }
                }
            },
        )

    result = await m.get_post_metrics(
        "fixture-buffer-key",
        post_id=POST,
        expected_channel_id=CHANNEL,
        expected_service="instagram",
        transport=httpx.MockTransport(respond),
    )
    assert result["metrics_available"] is False
    assert result["metrics"] == []
    assert result["metrics_updated_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"id": "other"},
        {"channelId": "other"},
        {"channelService": "youtube"},
        {"status": "scheduled"},
    ],
)
async def test_wrong_post_identity_or_state_fails_closed(change):
    value = {
        "id": POST,
        "channelId": CHANNEL,
        "channelService": "tiktok",
        "status": "sent",
        "sentAt": "2026-10-04T18:40:08.542Z",
        "metrics": [],
        "metricsUpdatedAt": "2026-10-05T03:00:00Z",
    }
    value.update(change)

    def respond(request):
        return httpx.Response(200, json={"data": {"post": value}})

    with pytest.raises(m.BufferMetricsError):
        await m.get_post_metrics(
            "fixture-buffer-key",
            post_id=POST,
            expected_channel_id=CHANNEL,
            expected_service="tiktok",
            transport=httpx.MockTransport(respond),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["http", "graphql", "invalid", "oversized"])
async def test_provider_failures_do_not_leak_provider_bodies(kind):
    def respond(request):
        if kind == "http":
            return httpx.Response(401, text="secret-provider-body")
        if kind == "graphql":
            return httpx.Response(200, json={"errors": [{"message": "secret-provider-body"}]})
        if kind == "oversized":
            return httpx.Response(200, content=b"x" * (m.MAX_RESPONSE_BYTES + 1))
        return httpx.Response(200, text="not-json secret-provider-body")

    with pytest.raises(m.BufferMetricsError) as exc:
        await m.get_post_metrics(
            "fixture-buffer-key",
            post_id=POST,
            expected_channel_id=CHANNEL,
            expected_service="tiktok",
            transport=httpx.MockTransport(respond),
        )
    assert "secret" not in str(exc.value).lower()
    assert "fixture-buffer-key" not in str(exc.value)
