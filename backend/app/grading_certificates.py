from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner
from .recognition_images import RecognitionImageError, decode_image_data_url
from .settings import Settings, get_settings


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/grading-certificates",
    tags=["grading-certificates"],
)

PSA_API_BASE = "https://api.psacard.com/publicapi"
PSA_CERT_URL = "https://www.psacard.com/cert"
ACE_CERT_URL = "https://acegrading.com/cert"
CGC_CERT_URL = "https://www.cgccards.com/certlookup/"
BECKETT_CERT_URL = "https://marketplace.beckett.com/grading/withoutLogin_card_lookup"

PSA_CERT_PATTERN = re.compile(r"^\d{7,10}$")
GENERIC_CERT_PATTERN = re.compile(r"^\d{4,14}$")


class GradingProvider(str, Enum):
    PSA = "PSA"
    ACE = "ACE"
    CGC = "CGC"
    BGS = "BGS"
    BVG = "BVG"
    BCCG = "BCCG"


class CertificateLookupStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_CERTIFICATE = "INVALID_CERTIFICATE"
    MANUAL_VERIFICATION_REQUIRED = "MANUAL_VERIFICATION_REQUIRED"


class CertificateProviderConfigurationError(RuntimeError):
    pass


class CertificateProviderUpstreamError(RuntimeError):
    pass


_PROVIDER_ALIASES = {
    "PSA": GradingProvider.PSA,
    "ACE": GradingProvider.ACE,
    "ACE GRADING": GradingProvider.ACE,
    "CGC": GradingProvider.CGC,
    "CGC CARDS": GradingProvider.CGC,
    "BGS": GradingProvider.BGS,
    "BECKETT": GradingProvider.BGS,
    "BECKETT BGS": GradingProvider.BGS,
    "BVG": GradingProvider.BVG,
    "BCCG": GradingProvider.BCCG,
}


class GradingCertificateLookupRequest(BaseModel):
    grader: str = Field(min_length=2, max_length=40)
    certificate_number: str = Field(min_length=1, max_length=40)


class GradingSlabScanRequest(BaseModel):
    image_data_url: str = Field(min_length=100, max_length=12_000_000)


class GradingQrResolveRequest(BaseModel):
    qr_value: str = Field(min_length=1, max_length=2048)
    grader_hint: str | None = Field(default=None, max_length=40)


class GradingSlabObservation(BaseModel):
    grader: str
    certificate_number: str
    grade: str
    card_name: str
    card_number: str
    set_name: str
    year: str
    language: str
    label_lines: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class GradingCertificateResult(BaseModel):
    provider: GradingProvider
    certificate_number: str
    status: CertificateLookupStatus
    automated: bool
    verified: bool
    source: str
    verification_url: str
    fetched_at: datetime
    year: str | None = None
    set_brand: str | None = None
    subject: str | None = None
    card_number: str | None = None
    variety: str | None = None
    category: str | None = None
    grade: str | None = None
    grade_description: str | None = None
    language_printing: str | None = None
    subgrades: dict[str, str] = Field(default_factory=dict)
    front_image_url: str | None = None
    back_image_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


_OFFICIAL_QR_HOSTS: dict[str, GradingProvider] = {
    "psacard.com": GradingProvider.PSA,
    "www.psacard.com": GradingProvider.PSA,
    "acegrading.com": GradingProvider.ACE,
    "www.acegrading.com": GradingProvider.ACE,
    "cgccards.com": GradingProvider.CGC,
    "www.cgccards.com": GradingProvider.CGC,
    "beckett.com": GradingProvider.BGS,
    "www.beckett.com": GradingProvider.BGS,
    "marketplace.beckett.com": GradingProvider.BGS,
}


def parse_grading_qr_payload(
    raw_value: str,
    grader_hint: str | None = None,
) -> dict[str, Any]:
    from urllib.parse import parse_qsl, unquote, urlparse

    raw = str(raw_value or "").strip()
    if not raw:
        raise ValueError("QR code is empty")

    hint = normalize_grading_provider(grader_hint) if grader_hint else None

    if re.fullmatch(r"[0-9\s-]{4,20}", raw):
        if hint is None:
            raise ValueError("Numeric QR payload requires a grading-company hint")
        certificate = normalize_certificate_number(hint, raw)
        return {
            "provider": hint.value,
            "certificate_number": certificate,
            "trusted_domain": False,
            "source": "NUMERIC_QR_WITH_GRADER_HINT",
            "raw_value": raw,
        }

    parsed = urlparse(raw)
    host = (parsed.hostname or "").casefold()
    provider = _OFFICIAL_QR_HOSTS.get(host)
    if provider is None:
        raise ValueError("QR code does not point to a supported official grading domain")
    if hint is not None and provider is not hint:
        raise ValueError("QR grading domain conflicts with the selected grading company")

    decoded = unquote(raw)
    candidates: list[str] = []
    candidates.extend(re.findall(r"(?<!\d)\d{4,14}(?!\d)", decoded))
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if any(token in key.casefold() for token in ("cert", "serial", "item", "id")):
            candidates.insert(0, value)

    for candidate in candidates:
        try:
            certificate = normalize_certificate_number(provider, candidate)
            return {
                "provider": provider.value,
                "certificate_number": certificate,
                "trusted_domain": True,
                "source": "OFFICIAL_GRADER_QR",
                "raw_value": raw,
            }
        except ValueError:
            continue

    raise ValueError("QR code did not contain a readable grading certificate number")


def normalize_grading_provider(value: str) -> GradingProvider:
    normalized = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()
    provider = _PROVIDER_ALIASES.get(normalized)
    if provider is None:
        raise ValueError("Unsupported grading provider")
    return provider


def normalize_certificate_number(provider: GradingProvider, value: str) -> str:
    certificate = re.sub(r"[\s-]+", "", str(value or "")).strip()
    pattern = PSA_CERT_PATTERN if provider is GradingProvider.PSA else GENERIC_CERT_PATTERN
    if not pattern.fullmatch(certificate):
        if provider is GradingProvider.PSA:
            raise ValueError("PSA certificate number must contain 7-10 digits")
        raise ValueError("Certificate number must contain 4-14 digits")
    return certificate


def provider_verification_url(provider: GradingProvider, certificate: str) -> str:
    if provider is GradingProvider.PSA:
        return f"{PSA_CERT_URL}/{certificate}/psa"
    if provider is GradingProvider.ACE:
        return f"{ACE_CERT_URL}/{certificate}"
    if provider is GradingProvider.CGC:
        # CGC exposes a public cert verification tool but does not document a
        # stable cert-specific deep-link/API contract for server automation.
        return CGC_CERT_URL
    if provider in {GradingProvider.BGS, GradingProvider.BVG, GradingProvider.BCCG}:
        # Beckett explicitly exposes a public graded-card lookup page. Keep the
        # certificate as data in our result, but do not invent undocumented
        # deep-link/query semantics for that page.
        return BECKETT_CERT_URL
    raise ValueError("Unsupported grading provider")


def _pick(source: Any, *names: str) -> Any:
    if not isinstance(source, dict):
        return None
    for name in names:
        value = source.get(name)
        if value not in (None, ""):
            return value
    return None


def _psa_payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    nested = _pick(data, "PSACert", "psaCert", "cert", "Cert")
    return nested if isinstance(nested, dict) else data


def _collect_image_urls(
    value: Any,
    path: str = "",
    found: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    if found is None:
        found = []
    if isinstance(value, list):
        for index, entry in enumerate(value):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            _collect_image_urls(entry, next_path, found)
        return found
    if not isinstance(value, dict):
        return found
    for key, entry in value.items():
        next_path = f"{path}.{key}" if path else str(key)
        if (
            isinstance(entry, str)
            and entry.startswith("https://")
            and re.search(r"image|scan|photo|front|back|reverse", next_path, re.IGNORECASE)
        ):
            found.append((next_path, entry))
        elif isinstance(entry, (dict, list)):
            _collect_image_urls(entry, next_path, found)
    return found


def _string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def normalize_psa_response(certificate: str, data: Any) -> GradingCertificateResult:
    root = data if isinstance(data, dict) else {}
    payload = _psa_payload(data)
    valid_request = _pick(root, "IsValidRequest", "isValidRequest")
    message = str(_pick(root, "ServerMessage", "serverMessage") or "").strip()
    lowered = message.casefold()

    if valid_request is True and "request successful" in lowered:
        status = CertificateLookupStatus.VERIFIED
    elif valid_request is True and "no data found" in lowered:
        status = CertificateLookupStatus.NOT_FOUND
    else:
        status = CertificateLookupStatus.INVALID_CERTIFICATE

    image_fields = _collect_image_urls(data)
    front = next((url for key, url in image_fields if "front" in key.casefold()), None)
    back = next(
        (
            url
            for key, url in image_fields
            if "back" in key.casefold() or "reverse" in key.casefold()
        ),
        None,
    )
    unique_urls = list(dict.fromkeys(url for _, url in image_fields))
    if front is None and unique_urls:
        front = unique_urls[0]
    if back is None:
        back = next((url for url in unique_urls if url != front), None)

    warnings: list[str] = []
    if status is CertificateLookupStatus.VERIFIED and not (front and back):
        warnings.append("GRADED_SLAB_MEDIA_INCOMPLETE")

    return GradingCertificateResult(
        provider=GradingProvider.PSA,
        certificate_number=_string(
            _pick(payload, "CertNumber", "cert_number", "cert_id", "CertNo")
        )
        or certificate,
        status=status,
        automated=True,
        verified=status is CertificateLookupStatus.VERIFIED,
        source="PSA_PUBLIC_API",
        verification_url=provider_verification_url(GradingProvider.PSA, certificate),
        fetched_at=datetime.now(timezone.utc),
        year=_string(_pick(payload, "Year", "year")),
        set_brand=_string(_pick(payload, "Brand", "BrandTitle", "set_name", "brand")),
        subject=_string(_pick(payload, "Subject", "subject", "card_title", "title")),
        card_number=_string(_pick(payload, "CardNumber", "card_number")),
        variety=_string(_pick(payload, "Variety", "VarietyPedigree", "variety")),
        category=_string(_pick(payload, "Category", "category")),
        grade=_string(_pick(payload, "CardGrade", "Grade", "grade", "grade_value")),
        grade_description=_string(
            _pick(payload, "GradeDescription", "grade_description")
        ),
        language_printing=_string(
            _pick(payload, "Language", "language", "Printing", "printing")
        ),
        front_image_url=front,
        back_image_url=back,
        warnings=warnings,
    )


def manual_provider_result(
    provider: GradingProvider,
    certificate: str,
) -> GradingCertificateResult:
    return GradingCertificateResult(
        provider=provider,
        certificate_number=certificate,
        status=CertificateLookupStatus.MANUAL_VERIFICATION_REQUIRED,
        automated=False,
        verified=False,
        source="OFFICIAL_VERIFICATION_PAGE",
        verification_url=provider_verification_url(provider, certificate),
        fetched_at=datetime.now(timezone.utc),
        warnings=["PROVIDER_MACHINE_ACCESS_NOT_APPROVED"],
    )


async def lookup_psa_certificate(
    certificate: str,
    *,
    token: str | None,
    client: httpx.AsyncClient | None = None,
) -> GradingCertificateResult:
    if not token:
        raise CertificateProviderConfigurationError(
            "PSA Public API token is not configured"
        )

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
    try:
        try:
            response = await client.get(
                f"{PSA_API_BASE}/cert/GetByCertNumber/{certificate}",
                headers={
                    "Authorization": f"bearer {token}",
                    "Accept": "application/json",
                },
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise CertificateProviderUpstreamError(
                "PSA certificate provider is unavailable"
            ) from exc

        if response.status_code in {401, 403, 429} or response.status_code >= 500:
            raise CertificateProviderUpstreamError(
                "PSA certificate provider is unavailable"
            )
        if response.status_code != 200:
            raise CertificateProviderUpstreamError(
                "PSA certificate lookup failed"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise CertificateProviderUpstreamError(
                "PSA returned an invalid response"
            ) from exc
        return normalize_psa_response(certificate, data)
    finally:
        if owns_client:
            await client.aclose()


async def lookup_grading_certificate(
    grader: str,
    certificate_number: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> GradingCertificateResult:
    provider = normalize_grading_provider(grader)
    certificate = normalize_certificate_number(provider, certificate_number)

    if provider is GradingProvider.PSA:
        effective_settings = settings or get_settings()
        return await lookup_psa_certificate(
            certificate,
            token=effective_settings.psa_public_api_token,
            client=client,
        )

    return manual_provider_result(provider, certificate)



SLAB_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "grader": {
            "type": "string",
            "enum": ["PSA", "ACE", "CGC", "BGS", "BVG", "BCCG", "Unknown"],
        },
        "certificate_number": {"type": "string"},
        "grade": {"type": "string"},
        "card_name": {"type": "string"},
        "card_number": {"type": "string"},
        "set_name": {"type": "string"},
        "year": {"type": "string"},
        "language": {"type": "string"},
        "label_lines": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 20,
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "grader",
        "certificate_number",
        "grade",
        "card_name",
        "card_number",
        "set_name",
        "year",
        "language",
        "label_lines",
        "confidence",
    ],
}

SLAB_VISION_INSTRUCTIONS = """
Read the grading label on this trading-card slab.

This is OCR/evidence extraction only. Do not decide authenticity, market value,
canonical Drop Rate identity, or whether the card should be listed.

Return the grading company only when visible. Supported labels are PSA, ACE, CGC,
BGS, BVG and BCCG; otherwise return Unknown. Copy the certificate/serial number
literally from the slab label. Copy the displayed grade literally. Extract card
name, collector/card number, set/product line, year and language only when they
are printed or clearly established by label text. Do not infer missing values
from the artwork or prior knowledge.

If a field is unreadable, return an empty string. Confidence measures the quality
of the visible slab-label evidence, not permission to auto-approve anything.
""".strip()


def _openai_output_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
            ):
                return part["text"]
    return ""


def grading_catalogue_search_seed(
    observation: GradingSlabObservation,
    provider_result: GradingCertificateResult | None,
) -> str | None:
    if provider_result is not None:
        for value in (provider_result.card_number, provider_result.subject):
            if value and value.strip():
                return value.strip()
    for value in (
        observation.card_number,
        observation.card_name,
        observation.set_name,
    ):
        if value and value.strip():
            return value.strip()
    return None


def grading_provider_conflicts(
    observation: GradingSlabObservation,
    provider_result: GradingCertificateResult | None,
) -> list[str]:
    if provider_result is None or not provider_result.verified:
        return []
    conflicts: list[str] = []
    if (
        observation.grade.strip()
        and provider_result.grade
        and observation.grade.strip().casefold() != provider_result.grade.strip().casefold()
    ):
        conflicts.append("GRADE_CONFLICT")
    if (
        observation.card_number.strip()
        and provider_result.card_number
        and re.sub(r"[^A-Za-z0-9]", "", observation.card_number).casefold()
        != re.sub(r"[^A-Za-z0-9]", "", provider_result.card_number).casefold()
    ):
        conflicts.append("CARD_NUMBER_CONFLICT")
    return conflicts


async def observe_graded_slab(
    image_data_url: str,
    *,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> GradingSlabObservation:
    if not settings.openai_api_key:
        raise CertificateProviderConfigurationError(
            "Graded slab vision is not configured"
        )

    try:
        decode_image_data_url(
            image_data_url,
            max_bytes=settings.recognition_max_image_bytes,
        )
    except RecognitionImageError as exc:
        raise ValueError(str(exc)) from exc

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
    try:
        try:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.recognition_model,
                    "store": False,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": SLAB_VISION_INSTRUCTIONS},
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
                            "name": "drop_rate_graded_slab_observation",
                            "strict": True,
                            "schema": SLAB_OBSERVATION_SCHEMA,
                        }
                    },
                    "max_output_tokens": 900,
                },
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise CertificateProviderUpstreamError(
                "Graded slab vision is unavailable"
            ) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise CertificateProviderUpstreamError(
                "Graded slab vision is unavailable"
            )
        if response.status_code >= 400:
            raise CertificateProviderUpstreamError(
                "Graded slab vision request was rejected"
            )

        try:
            payload = response.json()
            text = _openai_output_text(payload)
            raw = json.loads(text)
            return GradingSlabObservation.model_validate(raw)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CertificateProviderUpstreamError(
                "Graded slab vision returned invalid evidence"
            ) from exc
    finally:
        if owns_client:
            await client.aclose()


async def scan_graded_slab(
    image_data_url: str,
    *,
    settings: Settings | None = None,
    vision_client: httpx.AsyncClient | None = None,
    provider_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    effective_settings = settings or get_settings()
    observation = await observe_graded_slab(
        image_data_url,
        settings=effective_settings,
        client=vision_client,
    )

    provider_result: GradingCertificateResult | None = None
    provider_error: str | None = None
    normalized_provider: GradingProvider | None = None
    normalized_certificate: str | None = None

    if observation.grader != "Unknown" and observation.certificate_number.strip():
        try:
            normalized_provider = normalize_grading_provider(observation.grader)
            normalized_certificate = normalize_certificate_number(
                normalized_provider,
                observation.certificate_number,
            )
            provider_result = await lookup_grading_certificate(
                normalized_provider.value,
                normalized_certificate,
                settings=effective_settings,
                client=provider_client,
            )
        except CertificateProviderConfigurationError:
            provider_error = "PROVIDER_NOT_CONFIGURED"
        except CertificateProviderUpstreamError:
            provider_error = "PROVIDER_UNAVAILABLE"
        except ValueError:
            provider_error = "CERTIFICATE_FORMAT_INVALID"
    elif observation.grader == "Unknown":
        provider_error = "GRADER_UNREADABLE"
    else:
        provider_error = "CERTIFICATE_UNREADABLE"

    conflicts = grading_provider_conflicts(observation, provider_result)
    if conflicts:
        provider_error = "PROVIDER_LABEL_CONFLICT"

    return {
        "observation": observation.model_dump(),
        "provider_result": (
            provider_result.model_dump(mode="json") if provider_result else None
        ),
        "provider_error": provider_error,
        "normalized_provider": (
            normalized_provider.value if normalized_provider else None
        ),
        "normalized_certificate": normalized_certificate,
        "catalogue_search_seed": grading_catalogue_search_seed(
            observation,
            provider_result,
        ),
        "conflicts": conflicts,
        "requires_human_confirmation": True,
        "auto_mutates_inventory": False,
        "stores_source_image": False,
    }


async def _require_active_owner(
    request: Request,
    user: AuthenticatedUser,
) -> None:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await _owner(connection)


@router.get("/status")
async def grading_certificate_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    await _require_active_owner(request, user)
    settings = get_settings()
    return {
        "providers": {
            "PSA": {
                "mode": "AUTOMATED",
                "configured": bool(settings.psa_public_api_token),
                "source": "PSA_PUBLIC_API",
            },
            "ACE": {
                "mode": "MANUAL_VERIFICATION",
                "configured": True,
                "source": "OFFICIAL_VERIFICATION_PAGE",
            },
            "CGC": {
                "mode": "MANUAL_VERIFICATION",
                "configured": True,
                "source": "OFFICIAL_VERIFICATION_PAGE",
            },
            "BGS": {
                "mode": "MANUAL_VERIFICATION",
                "configured": True,
                "source": "OFFICIAL_VERIFICATION_PAGE",
            },
            "BVG": {
                "mode": "MANUAL_VERIFICATION",
                "configured": True,
                "source": "OFFICIAL_VERIFICATION_PAGE",
            },
            "BCCG": {
                "mode": "MANUAL_VERIFICATION",
                "configured": True,
                "source": "OFFICIAL_VERIFICATION_PAGE",
            },
        },
        "auto_mutates_inventory": False,
        "canonical_identity_decided_here": False,
    }




@router.post("/qr/resolve")
async def grading_qr_resolve(
    payload: GradingQrResolveRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    await _require_active_owner(request, user)
    try:
        parsed = parse_grading_qr_payload(payload.qr_value, payload.grader_hint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **parsed,
        "requires_provider_verification": True,
        "requires_human_confirmation": True,
    }


@router.post("/scan")
async def grading_slab_scan(
    payload: GradingSlabScanRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    await _require_active_owner(request, user)
    try:
        result = await scan_graded_slab(payload.image_data_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CertificateProviderConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Graded slab vision is not configured",
        ) from exc
    except CertificateProviderUpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail="Graded slab recognition provider is unavailable",
        ) from exc

    logger.info(
        "grading_slab_scan grader=%s cert_present=%s provider_error=%s conflicts=%s user_id=%s",
        result.get("normalized_provider") or result["observation"].get("grader"),
        bool(result.get("normalized_certificate")),
        result.get("provider_error"),
        result.get("conflicts"),
        user.user_id,
    )
    return result


@router.post("/lookup", response_model=GradingCertificateResult)
async def grading_certificate_lookup(
    payload: GradingCertificateLookupRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> GradingCertificateResult:
    await _require_active_owner(request, user)
    try:
        result = await lookup_grading_certificate(
            payload.grader,
            payload.certificate_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CertificateProviderConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="PSA certificate lookup is not configured",
        ) from exc
    except CertificateProviderUpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail="Grading certificate provider is unavailable",
        ) from exc

    logger.info(
        "grading_certificate_lookup provider=%s cert=%s status=%s automated=%s user_id=%s",
        result.provider.value,
        result.certificate_number,
        result.status.value,
        result.automated,
        user.user_id,
    )
    return result
