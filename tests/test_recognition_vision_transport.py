from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from app.recognition_vision import (
    OpenAIRecognitionVisionClient,
    _shared_http_client,
    close_shared_vision_http_client,
)


ROOT = Path(__file__).resolve().parents[1]
VISION = ROOT / "backend" / "app" / "recognition_vision.py"
RECOGNITION = ROOT / "backend" / "app" / "recognition.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def observation_payload() -> dict:
    return {
        "game": "One Piece",
        "game_confidence": 0.99,
        "language": "English",
        "language_confidence": 0.99,
        "name_guess": "Nami",
        "name_confidence": 0.98,
        "set_name_guess": "Example Set",
        "set_name_confidence": 0.90,
        "card_number": "OP01-016",
        "card_number_confidence": 0.97,
        "cost": 1,
        "cost_confidence": 0.95,
        "power": 2000,
        "power_confidence": 0.95,
        "colors": ["Red"],
        "colors_confidence": 0.95,
        "attributes": ["Special"],
        "attributes_confidence": 0.85,
        "traits": ["Straw Hat Crew"],
        "traits_confidence": 0.90,
        "effect_text": "Example visible effect.",
        "effect_confidence": 0.80,
        "rarity_text": "R",
        "rarity_confidence": 0.95,
        "card_type_text": "Character",
        "card_type_confidence": 0.99,
        "art_treatment_text": "Base",
        "art_treatment_confidence": 0.80,
        "finish_text": "Holofoil",
        "finish_confidence": 0.88,
        "visible_markers": [],
        "ocr_lines": ["OP01-016"],
        "image_quality": "GOOD",
        "counterfeit_concerns": [],
        "notes": [],
    }


def test_vision_request_contract_remains_high_detail_and_semantically_unchanged() -> None:
    captured: list[dict] = []

    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured.append(body)
            return httpx.Response(
                200,
                json={
                    "id": "resp_recognition_test",
                    "model": "gpt-5.6-sol",
                    "usage": {
                        "input_tokens": 1234,
                        "output_tokens": 321,
                        "total_tokens": 1555,
                        "input_tokens_details": {"cached_tokens": 256},
                        "output_tokens_details": {"reasoning_tokens": 11},
                    },
                    "output_text": json.dumps(observation_payload()),
                },
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = OpenAIRecognitionVisionClient(
                api_key="test-key",
                model="gpt-5.6-sol",
                http_client=http_client,
            )
            result = await client.observe_with_telemetry(
                "data:image/jpeg;base64,ZmFrZQ=="
            )

        assert result.observation.card_number == "OP01-016"
        assert result.telemetry.response_id == "resp_recognition_test"
        assert result.telemetry.response_model == "gpt-5.6-sol"
        assert result.telemetry.input_tokens == 1234
        assert result.telemetry.output_tokens == 321
        assert result.telemetry.total_tokens == 1555
        assert result.telemetry.cached_input_tokens == 256
        assert result.telemetry.reasoning_tokens == 11
        assert result.telemetry.request_ms >= 0

    asyncio.run(run())

    assert len(captured) == 1
    body = captured[0]
    assert body["model"] == "gpt-5.6-sol"
    assert body["store"] is False
    assert body["max_output_tokens"] == 1800
    assert "reasoning" not in body
    image_part = body["input"][0]["content"][1]
    assert image_part["type"] == "input_image"
    assert image_part["detail"] == "high"
    assert body["text"]["format"]["strict"] is True


def test_default_vision_transport_reuses_one_keepalive_client() -> None:
    async def run() -> None:
        await close_shared_vision_http_client()
        first = _shared_http_client()
        second = _shared_http_client()
        assert first is second
        assert not first.is_closed
        await close_shared_vision_http_client()
        assert first.is_closed
        replacement = _shared_http_client()
        assert replacement is not first
        await close_shared_vision_http_client()

    asyncio.run(run())


def test_recognition_pipeline_persists_transport_and_usage_telemetry() -> None:
    source = RECOGNITION.read_text()
    assert "vision.observe_with_telemetry(payload.image_data_url)" in source
    assert 'timings_ms["vision_provider_http"]' in source
    assert '"vision_telemetry": vision_telemetry' in source


def test_api_shutdown_closes_shared_vision_transport() -> None:
    source = MAIN.read_text()
    assert "close_shared_vision_http_client" in source
    assert "await close_shared_vision_http_client()" in source


def test_transport_change_does_not_change_recognition_engine_version_or_gates() -> None:
    recognition = RECOGNITION.read_text()
    vision = VISION.read_text()

    assert 'ENGINE_VERSION = "v1.6.1"' in recognition
    assert '"detail": "high"' in vision
    assert '"max_output_tokens": 1800' in vision
    assert '"reasoning"' not in vision


def test_vision_repairs_provider_values_that_exceed_local_bounds() -> None:
    async def run() -> None:
        payload = observation_payload()
        payload["game_confidence"] = 1.00001
        payload["name_guess"] = "N" * 450
        payload["effect_text"] = "E" * 2200
        payload["visible_markers"] = [f"marker-{index}" for index in range(45)]
        payload["cost"] = 123
        payload["power"] = 1234567

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "resp_overflow_repair",
                    "model": "gpt-5.6-sol",
                    "usage": {},
                    "output_text": json.dumps(payload),
                },
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = OpenAIRecognitionVisionClient(
                api_key="test-key",
                model="gpt-5.6-sol",
                http_client=http_client,
            )
            result = await client.observe_with_telemetry(
                "data:image/jpeg;base64,ZmFrZQ=="
            )

        assert result.observation.game_confidence == 1.0
        assert len(result.observation.name_guess) == 300
        assert len(result.observation.effect_text) == 1600
        assert len(result.observation.visible_markers) == 30
        assert result.observation.cost == 99
        assert result.observation.power == 999999

    asyncio.run(run())


def test_provider_json_schema_matches_local_validation_bounds() -> None:
    source = VISION.read_text()
    assert '"minimum": 0, "maximum": 1' in source
    assert '"maxLength": 1600' in source
    assert '"maxItems": 40' in source
    assert "_repair_observation_payload(parsed)" in source
