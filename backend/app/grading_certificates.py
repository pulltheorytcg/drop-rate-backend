from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner
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
BECKETT_CERT_URL = "https://www.beckett.com/grading/card-lookup"

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
        return f"{BECKETT_CERT_URL}?{urlencode({'item_id': certificate, 'item_type': provider.value})}"
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
