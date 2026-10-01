from __future__ import annotations

from dataclasses import replace

import pytest

from app.grading_certificates import (
    CertificateLookupStatus,
    CertificateProviderConfigurationError,
    CertificateProviderUpstreamError,
    GradingProvider,
    lookup_grading_certificate,
    normalize_certificate_number,
    normalize_grading_provider,
    normalize_psa_response,
    provider_verification_url,
)
from app.settings import Settings


def _settings(**changes) -> Settings:
    base = Settings(
        database_url="postgresql://example",
        auth_issuer="https://example.supabase.co/auth/v1",
        auth_audience="authenticated",
        jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="publishable",
        environment="test",
        db_pool_min=1,
        db_pool_max=1,
        parse_api_key=None,
        ebay_client_id=None,
        ebay_client_secret=None,
        ebay_marketplace_id="EBAY_GB",
    )
    return replace(base, **changes)


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.calls = []

    async def get(self, url, *, headers):
        self.calls.append((url, headers))
        return self.response


def test_provider_aliases_and_certificate_normalization() -> None:
    assert normalize_grading_provider("PSA") is GradingProvider.PSA
    assert normalize_grading_provider("Ace Grading") is GradingProvider.ACE
    assert normalize_grading_provider("Beckett") is GradingProvider.BGS
    assert normalize_grading_provider("CGC Cards") is GradingProvider.CGC
    assert normalize_certificate_number(GradingProvider.PSA, " 62398872 ") == "62398872"
    assert normalize_certificate_number(GradingProvider.BGS, "0018-479-833") == "0018479833"

    with pytest.raises(ValueError):
        normalize_grading_provider("UNKNOWN")
    with pytest.raises(ValueError):
        normalize_certificate_number(GradingProvider.PSA, "12ABC")


@pytest.mark.asyncio
async def test_non_psa_providers_fail_closed_to_official_manual_verification() -> None:
    ace = await lookup_grading_certificate("ACE", "590532", settings=_settings())
    cgc = await lookup_grading_certificate("CGC", "1234567999", settings=_settings())
    bgs = await lookup_grading_certificate("BGS", "0018479833", settings=_settings())

    for result in (ace, cgc, bgs):
        assert result.status is CertificateLookupStatus.MANUAL_VERIFICATION_REQUIRED
        assert result.verified is False
        assert result.automated is False
        assert result.warnings == ["PROVIDER_MACHINE_ACCESS_NOT_APPROVED"]

    assert ace.verification_url == "https://acegrading.com/cert/590532"
    assert cgc.verification_url == "https://www.cgccards.com/certlookup/"
    assert "item_id=0018479833" in bgs.verification_url
    assert "item_type=BGS" in bgs.verification_url


@pytest.mark.asyncio
async def test_psa_requires_dedicated_token_and_never_reuses_parse_key() -> None:
    with pytest.raises(CertificateProviderConfigurationError):
        await lookup_grading_certificate(
            "PSA",
            "62398872",
            settings=_settings(parse_api_key="not-a-psa-token", psa_public_api_token=None),
        )


@pytest.mark.asyncio
async def test_psa_success_is_normalized_as_provider_evidence() -> None:
    client = _Client(
        _Response(
            200,
            {
                "IsValidRequest": True,
                "ServerMessage": "Request successful",
                "PSACert": {
                    "CertNumber": "62398872",
                    "Year": "2020",
                    "Brand": "Pokemon",
                    "Subject": "Charizard",
                    "CardNumber": "4",
                    "CardGrade": "10",
                    "Category": "TCG Cards",
                },
                "SecureScan": {
                    "FrontImage": "https://images.example/front.jpg",
                    "BackImage": "https://images.example/back.jpg",
                },
            },
        )
    )
    result = await lookup_grading_certificate(
        "PSA",
        "62398872",
        settings=_settings(psa_public_api_token="psa-secret"),
        client=client,
    )

    assert result.status is CertificateLookupStatus.VERIFIED
    assert result.verified is True
    assert result.provider is GradingProvider.PSA
    assert result.subject == "Charizard"
    assert result.card_number == "4"
    assert result.grade == "10"
    assert result.front_image_url == "https://images.example/front.jpg"
    assert result.back_image_url == "https://images.example/back.jpg"
    assert result.warnings == []
    assert client.calls[0][1]["Authorization"] == "bearer psa-secret"
    assert client.calls[0][0].endswith("/cert/GetByCertNumber/62398872")


def test_psa_no_data_and_invalid_are_not_verified() -> None:
    missing = normalize_psa_response(
        "62398872",
        {"IsValidRequest": True, "ServerMessage": "No data found"},
    )
    invalid = normalize_psa_response(
        "62398872",
        {"IsValidRequest": False, "ServerMessage": "Invalid CertNo"},
    )

    assert missing.status is CertificateLookupStatus.NOT_FOUND
    assert missing.verified is False
    assert invalid.status is CertificateLookupStatus.INVALID_CERTIFICATE
    assert invalid.verified is False


@pytest.mark.asyncio
async def test_psa_upstream_failure_fails_closed() -> None:
    client = _Client(_Response(403, {"error": "forbidden"}))
    with pytest.raises(CertificateProviderUpstreamError):
        await lookup_grading_certificate(
            "PSA",
            "62398872",
            settings=_settings(psa_public_api_token="wrong"),
            client=client,
        )


def test_verification_urls_are_official_and_no_scraping_endpoint_is_invented() -> None:
    assert provider_verification_url(GradingProvider.PSA, "62398872").startswith(
        "https://www.psacard.com/cert/"
    )
    assert provider_verification_url(GradingProvider.ACE, "590532").startswith(
        "https://acegrading.com/cert/"
    )
    assert provider_verification_url(GradingProvider.CGC, "1234567999") == (
        "https://www.cgccards.com/certlookup/"
    )
    assert provider_verification_url(GradingProvider.BGS, "0018479833").startswith(
        "https://www.beckett.com/grading/card-lookup?"
    )
