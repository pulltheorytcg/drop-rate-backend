"""Explicit, bounded model smoke check; never run automatically on every scan.

Run in the existing service: PYTHONPATH=backend python
backend/scripts/recognition_model_smoketest.py --expected-model gpt-6.1-sol

Two real image requests through the unmodified production adapters, using only
a generated blank image. No database, inventory, certificate lookup or storage
writes. This checks API access/schema/no-object handling, NOT card accuracy.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import time
from typing import Any

import httpx
from PIL import Image

from app.grading_certificates import observe_graded_slab
from app.recognition_vision import OpenAIRecognitionVisionClient
from app.settings import get_settings


class SmokeCheckError(RuntimeError):
    pass


def blank_image() -> str:
    output = io.BytesIO()
    Image.new("RGB", (512, 512), (128, 128, 128)).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


class CheckedClient:
    """Record only safe response metadata; credentials/observations never logged."""

    def __init__(self, client: httpx.AsyncClient, expected_model: str) -> None:
        self.client = client
        self.expected_model = expected_model
        self.receipts: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        body = kwargs.get("json", {})
        if url != "https://api.openai.com/v1/responses":
            raise SmokeCheckError("Unexpected provider endpoint")
        if body.get("model") != self.expected_model or body.get("store") is not False:
            raise SmokeCheckError("Model/storage request contract mismatch")
        started = time.perf_counter()
        response = await self.client.post(url, **kwargs)
        if response.is_success:
            data = response.json()
            model = str(data.get("model", ""))
            if model != self.expected_model and not model.startswith(self.expected_model + "-"):
                raise SmokeCheckError("Provider returned a different model")
            if data.get("status") != "completed":
                raise SmokeCheckError("Provider response did not complete")
            usage = data.get("usage") or {}
            self.receipts.append({
                "schema": body["text"]["format"]["name"],
                "response_model": model,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
            })
        return response


async def run_smoke(settings: Any, client: httpx.AsyncClient, expected_model: str) -> dict[str, Any]:
    if settings.recognition_model != expected_model or not settings.openai_api_key:
        raise SmokeCheckError("Runtime model/key is not configured as requested")
    checked = CheckedClient(client, expected_model)
    image = blank_image()
    vision = OpenAIRecognitionVisionClient(
        api_key=settings.openai_api_key,
        model=settings.recognition_model,
        http_client=checked,
    )
    result = await vision.observe_with_telemetry(image)
    observed = result.observation
    if observed.object_type not in {"NONE", "UNKNOWN"} or observed.card_number or observed.product_code:
        raise SmokeCheckError("Blank image incorrectly identified as stock")
    slab = await observe_graded_slab(image, settings=settings, client=checked)
    if slab.certificate_number.strip() or slab.grade.strip() or slab.card_number.strip():
        raise SmokeCheckError("Blank image generated slab identity")
    if len(checked.receipts) != 2:
        raise SmokeCheckError("Incomplete adapter verification")
    return {
        "recognition_model_smoketest": "PASS",
        "configured_model": settings.recognition_model,
        "requests": checked.receipts,
        "scope": "Real image API/schema/no-object checks only; not exact-card accuracy or a signed-in scanner journey.",
        "database_writes": False,
        "source_image": "generated_blank_fixture",
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-model", required=True)
    args = parser.parse_args()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
            report = await run_smoke(get_settings(), client, args.expected_model)
        print(json.dumps(report, sort_keys=True), flush=True)
        return 0
    except Exception as error:
        # Provider exceptions may contain sensitive request context. Log only
        # the class/status, not the message, traceback, headers or response body.
        print(json.dumps({
            "recognition_model_smoketest": "FAIL",
            "error_type": type(error).__name__,
            "http_status": getattr(error, "status_code", None),
        }), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
