from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, Mapping

import httpx
from pydantic import BaseModel, Field, model_validator
from .recognition_games import SYSTEM_BY_GAME


logger = logging.getLogger(__name__)

_SHARED_HTTP_CLIENT: httpx.AsyncClient | None = None
_SHARED_HTTP_CLIENT_LOCK = Lock()


def _shared_http_client() -> httpx.AsyncClient:
    """Reuse keep-alive connections across recognition scans in one API worker."""
    global _SHARED_HTTP_CLIENT
    with _SHARED_HTTP_CLIENT_LOCK:
        if _SHARED_HTTP_CLIENT is None or _SHARED_HTTP_CLIENT.is_closed:
            _SHARED_HTTP_CLIENT = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=60.0,
                )
            )
        return _SHARED_HTTP_CLIENT


async def close_shared_vision_http_client() -> None:
    """Close the worker-level transport during FastAPI shutdown."""
    global _SHARED_HTTP_CLIENT
    with _SHARED_HTTP_CLIENT_LOCK:
        client = _SHARED_HTTP_CLIENT
        _SHARED_HTTP_CLIENT = None
    if client is not None and not client.is_closed:
        await client.aclose()


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class RecognitionVisionTelemetry:
    request_ms: float
    response_id: str | None
    response_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_ms": self.request_ms,
            "response_id": self.response_id,
            "response_model": self.response_model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True, slots=True)
class RecognitionVisionResult:
    observation: "RecognitionObservation"
    telemetry: RecognitionVisionTelemetry


def _telemetry_from_response(
    payload: Mapping[str, Any],
    *,
    request_ms: float,
) -> RecognitionVisionTelemetry:
    usage = payload.get("usage")
    usage_map = usage if isinstance(usage, Mapping) else {}
    input_details = usage_map.get("input_tokens_details")
    input_details_map = input_details if isinstance(input_details, Mapping) else {}
    output_details = usage_map.get("output_tokens_details")
    output_details_map = output_details if isinstance(output_details, Mapping) else {}
    return RecognitionVisionTelemetry(
        request_ms=round(float(request_ms), 2),
        response_id=(
            str(payload.get("id")).strip()
            if payload.get("id") is not None
            else None
        ),
        response_model=(
            str(payload.get("model")).strip()
            if payload.get("model") is not None
            else None
        ),
        input_tokens=_optional_int(usage_map.get("input_tokens")),
        output_tokens=_optional_int(usage_map.get("output_tokens")),
        total_tokens=_optional_int(usage_map.get("total_tokens")),
        cached_input_tokens=_optional_int(input_details_map.get("cached_tokens")),
        reasoning_tokens=_optional_int(output_details_map.get("reasoning_tokens")),
    )


class RecognitionVisionError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable


class RecognitionObservation(BaseModel):
    object_type: Literal["CARD", "GRADED_CARD", "SEALED_PRODUCT", "NONE", "UNKNOWN"] = "CARD"
    object_type_confidence: float = Field(default=1.0, ge=0, le=1)
    sealed_product_type: Literal["BOOSTER_PACK", "BOOSTER_BOX", "STARTER_DECK", "COLLECTION", "TIN", "CASE", "OTHER", "UNKNOWN"] = "UNKNOWN"
    sealed_product_type_confidence: float = Field(default=0.0, ge=0, le=1)
    product_code: str = Field(default="", max_length=100)
    product_code_confidence: float = Field(default=0.0, ge=0, le=1)
    game: Literal["Pokemon", "One Piece", "Dragon Ball Super Masters", "Dragon Ball Super Fusion World", "Naruto Kayou", "Naruto Bandai Legacy", "Naruto Bandai", "Yu-Gi-Oh!", "Riftbound", "Disney Lorcana", "Unknown"]
    game_confidence: float = Field(ge=0, le=1)
    language: Literal["English", "Japanese", "Chinese", "Korean", "French", "German", "Italian", "Spanish", "Portuguese", "Unknown"]
    language_confidence: float = Field(ge=0, le=1)
    name_guess: str = Field(max_length=300)
    name_confidence: float = Field(ge=0, le=1)
    set_name_guess: str = Field(max_length=300)
    set_name_confidence: float = Field(ge=0, le=1)
    card_number: str = Field(max_length=100)
    card_number_confidence: float = Field(ge=0, le=1)
    cost: int | None = Field(default=None, ge=0, le=99)
    cost_confidence: float = Field(ge=0, le=1)
    power: int | None = Field(default=None, ge=0, le=999999)
    power_confidence: float = Field(ge=0, le=1)
    colors: list[str] = Field(max_length=8)
    colors_confidence: float = Field(ge=0, le=1)
    attributes: list[str] = Field(max_length=12)
    attributes_confidence: float = Field(ge=0, le=1)
    traits: list[str] = Field(max_length=20)
    traits_confidence: float = Field(ge=0, le=1)
    effect_text: str = Field(max_length=1600)
    effect_confidence: float = Field(ge=0, le=1)
    rarity_text: str = Field(max_length=120)
    rarity_confidence: float = Field(ge=0, le=1)
    card_type_text: str = Field(max_length=120)
    card_type_confidence: float = Field(ge=0, le=1)
    art_treatment_text: str = Field(max_length=160)
    art_treatment_confidence: float = Field(ge=0, le=1)
    finish_text: str = Field(max_length=160)
    finish_confidence: float = Field(ge=0, le=1)
    visible_markers: list[str] = Field(max_length=30)
    ocr_lines: list[str] = Field(max_length=40)
    image_quality: Literal["GOOD", "FAIR", "POOR"]
    counterfeit_concerns: list[str] = Field(max_length=20)
    notes: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def normalize(self) -> "RecognitionObservation":
        for field_name in (
            "name_guess",
            "set_name_guess",
            "card_number",
            "effect_text",
            "rarity_text",
            "card_type_text",
            "art_treatment_text",
            "finish_text",
        ):
            setattr(self, field_name, " ".join(getattr(self, field_name).strip().split()))
        self.colors = [
            " ".join(str(value).strip().split())[:80]
            for value in self.colors
            if str(value).strip()
        ]
        self.attributes = [
            " ".join(str(value).strip().split())[:80]
            for value in self.attributes
            if str(value).strip()
        ]
        self.traits = [
            " ".join(str(value).strip().split())[:120]
            for value in self.traits
            if str(value).strip()
        ]
        self.visible_markers = [
            " ".join(str(value).strip().split())[:200]
            for value in self.visible_markers
            if str(value).strip()
        ]
        self.ocr_lines = [
            " ".join(str(value).strip().split())[:300]
            for value in self.ocr_lines
            if str(value).strip()
        ]
        self.counterfeit_concerns = [
            " ".join(str(value).strip().split())[:300]
            for value in self.counterfeit_concerns
            if str(value).strip()
        ]
        self.notes = [
            " ".join(str(value).strip().split())[:300]
            for value in self.notes
            if str(value).strip()
        ]
        return self



_CONFIDENCE_FIELDS = (
    "object_type_confidence",
    "sealed_product_type_confidence",
    "product_code_confidence",
    "game_confidence",
    "language_confidence",
    "name_confidence",
    "set_name_confidence",
    "card_number_confidence",
    "cost_confidence",
    "power_confidence",
    "colors_confidence",
    "attributes_confidence",
    "traits_confidence",
    "effect_confidence",
    "rarity_confidence",
    "card_type_confidence",
    "art_treatment_confidence",
    "finish_confidence",
)

_STRING_LIMITS = {
    "product_code": 100,
    "name_guess": 300,
    "set_name_guess": 300,
    "card_number": 100,
    "effect_text": 1600,
    "rarity_text": 120,
    "card_type_text": 120,
    "art_treatment_text": 160,
    "finish_text": 160,
}

_LIST_LIMITS = {
    "colors": 8,
    "attributes": 12,
    "traits": 20,
    "visible_markers": 30,
    "ocr_lines": 40,
    "counterfeit_concerns": 20,
    "notes": 20,
}


def _repair_observation_payload(parsed: Mapping[str, Any]) -> dict[str, Any]:
    """Bound provider output to the same limits already enforced by our model.

    The OpenAI structured-output schema historically omitted several Pydantic
    max/min constraints. A response could therefore satisfy the provider schema
    but still fail local validation because of a 1.00001 confidence, oversized
    OCR list, or long free-text field. This helper only clamps/truncates those
    representational overflows; it never invents identity fields.
    """

    repaired = dict(parsed)
    for field_name in _CONFIDENCE_FIELDS:
        value = repaired.get(field_name)
        if isinstance(value, (int, float)):
            repaired[field_name] = max(0.0, min(1.0, float(value)))

    for field_name, max_length in _STRING_LIMITS.items():
        value = repaired.get(field_name)
        if isinstance(value, str):
            repaired[field_name] = value[:max_length]

    for field_name, max_items in _LIST_LIMITS.items():
        value = repaired.get(field_name)
        if isinstance(value, list):
            repaired[field_name] = value[:max_items]

    cost = repaired.get("cost")
    if isinstance(cost, int):
        repaired["cost"] = max(0, min(99, cost))
    power = repaired.get("power")
    if isinstance(power, int):
        repaired["power"] = max(0, min(999999, power))
    return repaired


OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "object_type": {"type": "string", "enum": ["CARD", "GRADED_CARD", "SEALED_PRODUCT", "NONE", "UNKNOWN"]},
        "object_type_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "sealed_product_type": {"type": "string", "enum": ["BOOSTER_PACK", "BOOSTER_BOX", "STARTER_DECK", "COLLECTION", "TIN", "CASE", "OTHER", "UNKNOWN"]},
        "sealed_product_type_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "product_code": {"type": "string", "maxLength": 100},
        "product_code_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "game": {"type": "string", "enum": [*SYSTEM_BY_GAME, "Unknown"]},
        "game_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "language": {"type": "string", "enum": ["English", "Japanese", "Chinese", "Korean", "French", "German", "Italian", "Spanish", "Portuguese", "Unknown"]},
        "language_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "name_guess": {"type": "string", "maxLength": 300},
        "name_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "set_name_guess": {"type": "string", "maxLength": 300},
        "set_name_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "card_number": {"type": "string", "maxLength": 100},
        "card_number_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "cost": {"type": ["integer", "null"], "minimum": 0, "maximum": 99},
        "cost_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "power": {"type": ["integer", "null"], "minimum": 0, "maximum": 999999},
        "power_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "colors": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "colors_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "attributes": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "attributes_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "traits": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "traits_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "effect_text": {"type": "string", "maxLength": 1600},
        "effect_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rarity_text": {"type": "string", "maxLength": 120},
        "rarity_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "card_type_text": {"type": "string", "maxLength": 120},
        "card_type_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "art_treatment_text": {"type": "string", "maxLength": 160},
        "art_treatment_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "finish_text": {"type": "string", "maxLength": 160},
        "finish_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "visible_markers": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
        "ocr_lines": {"type": "array", "items": {"type": "string"}, "maxItems": 40},
        "image_quality": {"type": "string", "enum": ["GOOD", "FAIR", "POOR"]},
        "counterfeit_concerns": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "notes": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
    },
    "required": [
        "object_type",
        "object_type_confidence",
        "sealed_product_type",
        "sealed_product_type_confidence",
        "product_code",
        "product_code_confidence",
        "game",
        "game_confidence",
        "language",
        "language_confidence",
        "name_guess",
        "name_confidence",
        "set_name_guess",
        "set_name_confidence",
        "card_number",
        "card_number_confidence",
        "cost",
        "cost_confidence",
        "power",
        "power_confidence",
        "colors",
        "colors_confidence",
        "attributes",
        "attributes_confidence",
        "traits",
        "traits_confidence",
        "effect_text",
        "effect_confidence",
        "rarity_text",
        "rarity_confidence",
        "card_type_text",
        "card_type_confidence",
        "art_treatment_text",
        "art_treatment_confidence",
        "finish_text",
        "finish_confidence",
        "visible_markers",
        "ocr_lines",
        "image_quality",
        "counterfeit_concerns",
        "notes",
    ],
}


VISION_INSTRUCTIONS = """
You are the evidence-extraction stage of Drop Rate's collectible recognition system.

First classify the photographed object itself. object_type must be CARD, GRADED_CARD,
SEALED_PRODUCT, NONE or UNKNOWN. A booster wrapper, booster box, starter deck,
collection box, tin or case is SEALED_PRODUCT and must never be interpreted as an
individual card merely because card artwork or characters are printed on its packaging.
Use NONE when no collectible is actually present in the scan guide.

For SEALED_PRODUCT, identify the visible sealed_product_type and transcribe any
manufacturer/set product code such as OP-17 into product_code. Keep card-only fields
empty or low-confidence unless they are genuinely printed as packaging metadata.
For CARD or GRADED_CARD, use product_code as an empty string and
sealed_product_type=UNKNOWN.

Analyse only what is visible in the supplied photograph. Do not decide whether
the card is safe to publish, price, buy, sell, grade, or certify as authentic.
Do not invent unreadable text. When a field cannot be established from the image,
return an empty string or Unknown and lower the corresponding confidence.

CRITICAL: extract every field independently from pixels. A guessed card number must
never be used to fill or "correct" the set, colour, rarity, traits, effect, power,
cost, card type, art treatment or any other field from prior knowledge. Likewise,
do not choose a card number because other visible fields remind you of a known card.
If the tiny printed ID is blurred, return the best literal OCR guess with appropriately
low confidence while preserving independently visible collaboration/event marks such
as ROUND1, tournament stamps, promo logos or anniversary marks. Do not infer metadata
from that OCR guess.

Supported game lines: Pokemon, One Piece, Dragon Ball Super Masters, Dragon Ball
Super Fusion World, Naruto Kayou, Naruto Bandai Legacy, Naruto Bandai (new game),
Yu-Gi-Oh!, Riftbound and Disney Lorcana. Distinguish game lines from visible logos
and layout; never treat a franchise name as proof of a specific game. Use Unknown
when the game line cannot be established. Do not invent unreleased cards or sets.
For Yu-Gi-Oh!, transcribe the printed set code (e.g. LOB-EN001) as card_number,
not the eight-digit gameplay passcode; preserve edition, region and rarity clues.
For Riftbound preserve the complete printed set/card identifier and art markers.
For Lorcana preserve collector number, set code, subtitle and language clues.
For Naruto preserve Kayou wave/tier/rarity codes and distinguish legacy Bandai
from the upcoming game. For Dragon Ball distinguish Masters from Fusion World.
For Pokemon, distinguish English vs Japanese, collector number, set clues, rarity
wording/symbols, card category, holo/reverse-holo/normal clues and visible special
art treatment when possible.
For One Piece, distinguish English vs Japanese, printed card ID, Leader/Character/
Event/Stage/DON!! category, printed rarity, and visible signs of base, parallel,
alternate-art, manga/super-parallel, SP/promo/reprint treatment when visible.
Also extract visible cost, power, card colour(s), attribute(s), trait/type line and
rules/effect text. These fields are important identity fingerprints when glare or
a sleeve makes the tiny printed card ID unreadable. Transcribe only what is visible.

A character/name match is not an exact-printing match. Two cards with the same
name and number can be different printings. Preserve uncertainty rather than
guessing. Confidence is probability-like evidence quality from 0 to 1, not a
permission to auto-approve.

Counterfeit concerns are observations only (for example visibly inconsistent print
layout or suspicious typography). Never state that a card is counterfeit from a
photo alone.

Return only the requested structured object.
""".strip()


def _output_text(payload: Mapping[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, Mapping)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
            ):
                return part["text"]
    return ""


class OpenAIRecognitionVisionClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 45.0,
        base_url: str = "https://api.openai.com/v1",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        if not model.strip():
            raise ValueError("Recognition model is required")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http_client = http_client

    @property
    def model(self) -> str:
        return self._model

    async def observe(self, image_data_url: str) -> RecognitionObservation:
        result = await self.observe_with_telemetry(image_data_url)
        return result.observation

    async def observe_with_telemetry(
        self,
        image_data_url: str,
    ) -> RecognitionVisionResult:
        body = {
            "model": self._model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": VISION_INSTRUCTIONS},
                        {
                            "type": "input_image",
                            "image_url": image_data_url,
                            "detail": "high",
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "tcg_recognition_observation",
                    "strict": True,
                    "schema": OBSERVATION_SCHEMA,
                }
            },
            "max_output_tokens": 1800,
        }
        request_started = time.perf_counter()
        try:
            client = self._http_client or _shared_http_client()
            response = await client.post(
                f"{self._base_url}/responses",
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise RecognitionVisionError(
                "Recognition vision request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise RecognitionVisionError(
                "Recognition vision request failed",
                retryable=True,
            ) from exc

        if response.status_code == 429:
            raise RecognitionVisionError(
                "Recognition vision rate limit reached",
                status_code=429,
                retryable=True,
            )
        if 400 <= response.status_code < 500:
            raise RecognitionVisionError(
                "Recognition vision request was rejected",
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise RecognitionVisionError(
                "Recognition vision provider is unavailable",
                status_code=response.status_code,
                retryable=True,
            )

        request_ms = (time.perf_counter() - request_started) * 1000
        try:
            payload = response.json()
        except ValueError as exc:
            raise RecognitionVisionError("Recognition vision returned invalid JSON") from exc

        telemetry = _telemetry_from_response(payload, request_ms=request_ms)
        logger.info(
            "Recognition vision provider request_ms=%s response_id=%s model=%s "
            "input_tokens=%s output_tokens=%s cached_input_tokens=%s reasoning_tokens=%s",
            telemetry.request_ms,
            telemetry.response_id,
            telemetry.response_model,
            telemetry.input_tokens,
            telemetry.output_tokens,
            telemetry.cached_input_tokens,
            telemetry.reasoning_tokens,
        )

        text = _output_text(payload)
        if not text:
            raise RecognitionVisionError("Recognition vision returned no structured observation")

        try:
            parsed = json.loads(text)
            if not isinstance(parsed, Mapping):
                raise ValueError("structured observation must be an object")
            repaired = _repair_observation_payload(parsed)
            return RecognitionVisionResult(
                observation=RecognitionObservation.model_validate(repaired),
                telemetry=telemetry,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Recognition vision schema validation failed response_id=%s error_type=%s",
                telemetry.response_id,
                exc.__class__.__name__,
            )
            raise RecognitionVisionError(
                "Recognition vision response failed schema validation"
            ) from exc
