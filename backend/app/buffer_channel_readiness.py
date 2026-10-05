"""Read-only Buffer channel readiness checks used by bounded operator diagnostics."""
from __future__ import annotations

import json
from typing import Any

import httpx


BUFFER_ENDPOINT = "https://api.buffer.com"
MAX_RESPONSE_BYTES = 1024 * 1024
CHANNELS_QUERY = """query($input: ChannelsInput!) {
  channels(input: $input) {
    id
    organizationId
    name
    displayName
    service
    allowedActions
    isDisconnected
    isLocked
    isQueuePaused
    timezone
  }
}"""


class BufferReadinessError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def _graphql(
    api_key: str,
    query: str,
    variables: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not isinstance(api_key, str) or len(api_key.strip()) < 10:
        raise BufferReadinessError("BUFFER_RUNTIME_CREDENTIAL_MISSING")

    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
            transport=transport,
        ) as client:
            async with client.stream(
                "POST",
                BUFFER_ENDPOINT,
                headers={"Authorization": "Bearer " + api_key.strip()},
                json={"query": query, "variables": variables},
            ) as response:
                if response.status_code != 200:
                    raise BufferReadinessError(
                        "BUFFER_CHANNELS_HTTP_" + str(response.status_code)
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise BufferReadinessError("BUFFER_CHANNELS_RESPONSE_TOO_LARGE")
    except BufferReadinessError:
        raise
    except httpx.HTTPError as exc:
        raise BufferReadinessError("BUFFER_CHANNELS_OUTCOME_UNVERIFIED") from exc

    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise BufferReadinessError("BUFFER_CHANNELS_RESPONSE_INVALID") from exc

    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise BufferReadinessError("BUFFER_CHANNELS_GRAPHQL_ERROR")
    return payload["data"]


def _sanitise_channel(channel: dict[str, Any]) -> dict[str, Any]:
    allowed_actions = channel.get("allowedActions")
    if not isinstance(allowed_actions, list) or not all(
        isinstance(item, str) for item in allowed_actions
    ):
        allowed_actions = []

    return {
        "id": channel.get("id"),
        "organization_id": channel.get("organizationId"),
        "name": channel.get("name"),
        "display_name": channel.get("displayName"),
        "service": channel.get("service"),
        "allowed_actions": sorted(set(allowed_actions)),
        "is_disconnected": channel.get("isDisconnected"),
        "is_locked": channel.get("isLocked"),
        "is_queue_paused": channel.get("isQueuePaused"),
        "timezone": channel.get("timezone"),
    }


def select_youtube_channel(
    channels: list[dict[str, Any]],
    *,
    organization_id: str,
) -> dict[str, Any]:
    if not isinstance(channels, list):
        raise BufferReadinessError("BUFFER_CHANNELS_RESPONSE_INVALID")

    matches = [
        item
        for item in channels
        if isinstance(item, dict)
        and item.get("service") == "youtube"
        and item.get("organizationId") == organization_id
    ]
    if not matches:
        raise BufferReadinessError("BUFFER_YOUTUBE_CHANNEL_MISSING")
    if len(matches) != 1:
        raise BufferReadinessError("BUFFER_YOUTUBE_CHANNEL_AMBIGUOUS")

    channel = _sanitise_channel(matches[0])
    if not isinstance(channel["id"], str) or not channel["id"] or len(channel["id"]) > 100:
        raise BufferReadinessError("BUFFER_YOUTUBE_CHANNEL_ID_INVALID")

    blockers: list[str] = []
    if channel["is_disconnected"] is not False:
        blockers.append("DISCONNECTED")
    if channel["is_locked"] is not False:
        blockers.append("LOCKED")
    if channel["is_queue_paused"] is not False:
        blockers.append("QUEUE_PAUSED")
    if "scheduleUpdates" not in channel["allowed_actions"]:
        blockers.append("SCHEDULE_PERMISSION_MISSING")

    return {
        "ready": not blockers,
        "reason": None if not blockers else "BUFFER_YOUTUBE_CHANNEL_NOT_READY",
        "blockers": blockers,
        "channel": channel,
    }


async def get_youtube_readiness(
    api_key: str,
    *,
    organization_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    data = await _graphql(
        api_key,
        CHANNELS_QUERY,
        {"input": {"organizationId": organization_id}},
        transport=transport,
    )
    channels = data.get("channels")
    if not isinstance(channels, list):
        raise BufferReadinessError("BUFFER_CHANNELS_RESPONSE_INVALID")
    return select_youtube_channel(channels, organization_id=organization_id)
