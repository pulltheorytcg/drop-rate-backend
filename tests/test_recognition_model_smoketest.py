"""Mocked provider tests. Real API results belong in release verification."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.recognition_vision import OBSERVATION_SCHEMA, RecognitionVisionError

PATH = Path(__file__).resolve().parents[1] / "backend/scripts/recognition_model_smoketest.py"
SPEC = importlib.util.spec_from_file_location("recognition_model_smoketest", PATH)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)
MODEL = "gpt-6.1-sol"
SETTINGS = SimpleNamespace(recognition_model=MODEL, openai_api_key="synthetic-key-not-real", recognition_max_image_bytes=8_000_000)


def observation():
    result = {}
    for key, schema in OBSERVATION_SCHEMA["properties"].items():
        if key == "book":
            result[key] = None
            continue
        kind = schema["type"]
        if isinstance(kind, list): value = None
        elif kind == "array": value = []
        elif kind in {"number", "integer"}: value = 0
        else: value = schema.get("enum", [""])[0]
        result[key] = value
    result.update(object_type="NONE", game="Unknown", language="Unknown", image_quality="POOR")
    return result


def slab_observation():
    return dict(grader="Unknown", certificate_number="", grade="", card_name="", card_number="", set_name="", year="", language="Unknown", label_lines=[], confidence=0)


def run(mode="success"):
    calls = []
    async def execute():
        def handle(request):
            body = json.loads(request.content)
            calls.append(body)
            if mode == "rejected": return httpx.Response(401, json={"error": "synthetic rejection"})
            if mode == "timeout": raise httpx.ReadTimeout("synthetic", request=request)
            is_slab = body["text"]["format"]["name"] == "drop_rate_graded_slab_observation"
            result = slab_observation() if is_slab else observation()
            if mode == "invented_card" and not is_slab: result["object_type"] = "CARD"
            if mode == "invented_certificate" and is_slab: result["certificate_number"] = "12345678"
            return httpx.Response(200, json={
                "status": "incomplete" if mode == "incomplete" else "completed",
                "model": "gpt-5.6-sol" if mode == "wrong_model" else MODEL,
                "output_text": json.dumps(result),
                "usage": {"input_tokens": 100, "output_tokens": 100},
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await SMOKE.run_smoke(SETTINGS, client, MODEL)
    return asyncio.run(execute()), calls


def test_new_model_uses_existing_image_and_slab_adapters_without_storage_or_tools():
    report, calls = run()
    assert report["recognition_model_smoketest"] == "PASS"
    assert len(calls) == len(report["requests"]) == 2
    assert report["database_writes"] is False
    for body in calls:
        assert body["model"] == MODEL and body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert body["input"][0]["content"][1]["type"] == "input_image"
        assert body["input"][0]["content"][1]["detail"] == "high"
        assert "tools" not in body and "service_tier" not in body
    assert calls[0]["max_output_tokens"] == 3000
    assert calls[1]["max_output_tokens"] == 900
    assert "synthetic-key-not-real" not in json.dumps(report)


@pytest.mark.parametrize("mode", ["wrong_model", "incomplete", "invented_card", "invented_certificate"])
def test_cannot_claim_upgrade_success_for_wrong_or_incomplete_response(mode):
    with pytest.raises(SMOKE.SmokeCheckError): run(mode)


@pytest.mark.parametrize("mode", ["rejected", "timeout"])
def test_provider_errors_fail_without_switching_models(mode):
    with pytest.raises(RecognitionVisionError): run(mode)


def test_missing_key_and_wrong_runtime_model_send_no_requests():
    async def execute():
        def handle(request): raise AssertionError("No request is authorised")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            for settings in (SimpleNamespace(recognition_model="gpt-5.6-sol", openai_api_key="x"), SimpleNamespace(recognition_model=MODEL, openai_api_key=None)):
                with pytest.raises(SMOKE.SmokeCheckError):
                    await SMOKE.run_smoke(settings, client, MODEL)
    asyncio.run(execute())
