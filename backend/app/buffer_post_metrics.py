"""Read-only Buffer metrics for specifically identified sent posts."""
from __future__ import annotations

import json
from typing import Any

import httpx


BUFFER_ENDPOINT = "https://api.buffer.com"
MAX_RESPONSE_BYTES = 1024 * 1024
POST_METRICS_QUERY = """query GetPostMetrics($input: PostInput!) {
  post(input: $input) {
    id
    channelId
    channelService
    status
    sentAt
    metrics {
      type
      name
      value
      unit
    }
    metricsUpdatedAt
  }
}"""


class BufferMetricsError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def get_post_metrics(
    api_key: str,
    *,
    post_id: str,
    expected_channel_id: str,
    expected_service: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not api_key or len(api_key.strip()) < 10:
        raise BufferMetricsError("BUFFER_RUNTIME_CREDENTIAL_MISSING")
    if not post_id or len(post_id) > 100:
        raise BufferMetricsError("BUFFER_POST_ID_INVALID")

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
                json={
                    "query": POST_METRICS_QUERY,
                    "variables": {"input": {"id": post_id}},
                },
            ) as response:
                if response.status_code != 200:
                    raise BufferMetricsError(
                        "BUFFER_METRICS_HTTP_" + str(response.status_code)
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise BufferMetricsError("BUFFER_METRICS_RESPONSE_TOO_LARGE")
    except BufferMetricsError:
        raise
    except httpx.HTTPError as exc:
        raise BufferMetricsError("BUFFER_METRICS_OUTCOME_UNVERIFIED") from exc

    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise BufferMetricsError("BUFFER_METRICS_RESPONSE_INVALID") from exc

    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise BufferMetricsError("BUFFER_METRICS_GRAPHQL_ERROR")

    post = payload["data"].get("post")
    if not isinstance(post, dict):
        raise BufferMetricsError("BUFFER_POST_NOT_FOUND")
    if (
        post.get("id") != post_id
        or post.get("channelId") != expected_channel_id
        or post.get("channelService") != expected_service
    ):
        raise BufferMetricsError("BUFFER_POST_IDENTITY_MISMATCH")
    if post.get("status") != "sent":
        raise BufferMetricsError("BUFFER_POST_NOT_SENT")

    raw_metrics = post.get("metrics")
    if raw_metrics is not None and not isinstance(raw_metrics, list):
        raise BufferMetricsError("BUFFER_METRICS_RESPONSE_INVALID")

    metrics = []
    for item in raw_metrics or []:
        if not isinstance(item, dict):
            raise BufferMetricsError("BUFFER_METRICS_RESPONSE_INVALID")
        metric_type = item.get("type")
        name = item.get("name")
        value = item.get("value")
        unit = item.get("unit")
        if not isinstance(metric_type, str) or not isinstance(name, str):
            raise BufferMetricsError("BUFFER_METRICS_RESPONSE_INVALID")
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            raise BufferMetricsError("BUFFER_METRICS_RESPONSE_INVALID")
        metrics.append(
            {
                "type": metric_type,
                "name": name,
                "value": value,
                "unit": unit if isinstance(unit, str) else None,
            }
        )

    return {
        "post_id": post_id,
        "channel_id": expected_channel_id,
        "service": expected_service,
        "status": "sent",
        "sent_at": post.get("sentAt"),
        "metrics_updated_at": post.get("metricsUpdatedAt"),
        "metrics": metrics,
        "metrics_available": raw_metrics is not None,
    }
