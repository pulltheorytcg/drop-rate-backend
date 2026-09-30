from __future__ import annotations

import json
from typing import Any, Literal, Mapping

import httpx
from pydantic import BaseModel, Field, model_validator
from .recognition_games import SYSTEM_BY_GAME


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


OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "game": {"type": "string", "enum": [*SYSTEM_BY_GAME, "Unknown"]},
        "game_confidence": {"type": "number"},
        "language": {"type": "string", "enum": ["English", "Japanese", "Chinese", "Korean", "French", "German", "Italian", "Spanish", "Portuguese", "Unknown"]},
        "language_confidence": {"type": "number"},
        "name_guess": {"type": "string"},
        "name_confidence": {"type": "number"},
        "set_name_guess": {"type": "string"},
        "set_name_confidence": {"type": "number"},
        "card_number": {"type": "string"},
        "card_number_confidence": {"type": "number"},
        "cost": {"type": ["integer", "null"]},
        "cost_confidence": {"type": "number"},
        "power": {"type": ["integer", "null"]},
        "power_confidence": {"type": "number"},
        "colors": {"type": "array", "items": {"type": "string"}},
        "colors_confidence": {"type": "number"},
        "attributes": {"type": "array", "items": {"type": "string"}},
        "attributes_confidence": {"type": "number"},
        "traits": {"type": "array", "items": {"type": "string"}},
        "traits_confidence": {"type": "number"},
        "effect_text": {"type": "string"},
        "effect_confidence": {"type": "number"},
        "rarity_text": {"type": "string"},
        "rarity_confidence": {"type": "number"},
        "card_type_text": {"type": "string"},
        "card_type_confidence": {"type": "number"},
        "art_treatment_text": {"type": "string"},
        "art_treatment_confidence": {"type": "number"},
        "finish_text": {"type": "string"},
        "finish_confidence": {"type": "number"},
        "visible_markers": {"type": "array", "items": {"type": "string"}},
        "ocr_lines": {"type": "array", "items": {"type": "string"}},
        "image_quality": {"type": "string", "enum": ["GOOD", "FAIR", "POOR"]},
        "counterfeit_concerns": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
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
You are the evidence-extraction stage of Drop Rate's trading-card recognition system.

Analyse only what is visible in the supplied card photograph. Do not decide whether
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
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        if not model.strip():
            raise ValueError("Recognition model is required")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)

    @property
    def model(self) -> str:
        return self._model

    async def observe(self, image_data_url: str) -> RecognitionObservation:
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
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/responses",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
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

        try:
            payload = response.json()
        except ValueError as exc:
            raise RecognitionVisionError("Recognition vision returned invalid JSON") from exc

        text = _output_text(payload)
        if not text:
            raise RecognitionVisionError("Recognition vision returned no structured observation")

        try:
            parsed = json.loads(text)
            return RecognitionObservation.model_validate(parsed)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RecognitionVisionError(
                "Recognition vision response failed schema validation"
            ) from exc
