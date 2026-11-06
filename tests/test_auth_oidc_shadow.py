"""OIDC migration shadow: exact signatures and verified identity links, no role claims."""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth_oidc_shadow import (
    OIDCIdentityError, TrustedOIDCProvider, VerifiedExternalSubject,
    verify_external_token, verified_legacy_identity,
    read_verified_identity_link,
)

PRIVATE_KEY=rsa.generate_private_key(public_exponent=65537,key_size=2048)
PUBLIC_KEY=PRIVATE_KEY.public_key()
TRUST=TrustedOIDCProvider(
    provider="external_oidc",issuer="https://id.example.com/",
    audience="drop-rate-private-api",
    jwks_url="https://id.example.com/.well-known/jwks.json",
)
LEGACY="9babd7fc-2156-47fd-9ea5-73a87afc5dc2"
GEN="src-"+"a"*32


class OfflineJWKS:
    def get_signing_key_from_jwt(self,raw):
        return SimpleNamespace(key=PUBLIC_KEY)


def signed(**overrides):
    now=int(datetime.now(timezone.utc).timestamp())
    payload={
      "iss":TRUST.issuer,"aud":TRUST.audience,"sub":"external-subject-1",
      "iat":now,"exp":now+300,"email":"forged-admin@example.com",
      "role":"PLATFORM_ADMIN","founder_slot":1,"owner_id":"arbitrary-owned-uuid",
      "app_metadata":{"role":"PLATFORM_ADMIN"},
    }
    payload.update(overrides)
    return jwt.encode(payload,PRIVATE_KEY,algorithm="RS256",headers={"kid":"test-key"})


def link(**change):
    result={
      "generation_id":GEN,"legacy_user_id":LEGACY,
      "provider":"external_oidc","external_subject":"external-subject-1",
      "verified_at":"2026-11-06T20:00:00Z",
    }
    result.update(change)
    return result


def test_valid_signature_exposes_subject_but_never_claimed_privileges():
    who=verify_external_token(signed(),TRUST,OfflineJWKS())
    assert who==VerifiedExternalSubject("external_oidc","external-subject-1",TRUST.issuer)
    assert tuple(f.name for f in fields(who))==("provider","subject","issuer")
    assert verified_legacy_identity([link()],who,generation_id=GEN)==UUID(LEGACY)


@pytest.mark.parametrize("claims",[
    {"iss":"https://evil.example.com/"},{"aud":"different-audience"},
    {"exp":0},{"iat":None},{"sub":None},{"sub":""},{"is_anonymous":True},
])
def test_invalid_source_or_expired_or_anonymous_tokens_fail(claims):
    with pytest.raises(OIDCIdentityError):
        verify_external_token(signed(**claims),TRUST,OfflineJWKS())


def test_rejects_unsigned_and_hmac_role_forgery():
    now=int(datetime.now(timezone.utc).timestamp())
    claims={"iss":TRUST.issuer,"aud":TRUST.audience,
            "sub":"external-subject-1","iat":now,"exp":now+100,
            "role":"PLATFORM_ADMIN"}
    forged=jwt.encode(claims,"",algorithm="none")
    with pytest.raises(OIDCIdentityError):
        verify_external_token(forged,TRUST,OfflineJWKS())
    hmac=jwt.encode(claims,"attacker-secret",algorithm="HS256")
    with pytest.raises(OIDCIdentityError):
        verify_external_token(hmac,TRUST,OfflineJWKS())


@pytest.mark.parametrize("wrong",[
    {"provider":"other_provider"},{"external_subject":"different-external-sub"},
    {"verified_at":None},{"legacy_user_id":"not-a-uuid"},
    {"generation_id":"src-"+"b"*32},
])
def test_no_auto_link_on_email_or_unverified_ambiguous_claims(wrong):
    who=verify_external_token(signed(),TRUST,OfflineJWKS())
    with pytest.raises(OIDCIdentityError):
        verified_legacy_identity([link(**wrong)],who,generation_id=GEN)


def test_multiple_verified_links_denied_and_no_email_matching():
    who=verify_external_token(signed(),TRUST,OfflineJWKS())
    with pytest.raises(OIDCIdentityError):
        verified_legacy_identity([link(),link()],who,generation_id=GEN)
    with pytest.raises(OIDCIdentityError):
        verified_legacy_identity([],who,generation_id=GEN)


@pytest.mark.parametrize("issuer,jwks",[
    ("http://id.example.com/","https://id.example.com/.well-known/jwks.json"),
    ("https://id.example.com/","https://other.example.com/.well-known/jwks.json"),
    ("https://id.example.com/","https://id.example.com/unsafe?next=evil"),
    ("https://user:pass@id.example.com/","https://id.example.com/.well-known/jwks.json"),
])
def test_untrusted_idp_endpoints_are_rejected(issuer,jwks):
    with pytest.raises(OIDCIdentityError):
        TrustedOIDCProvider(
            provider="external_oidc",issuer=issuer,audience="drop-rate-private-api",
            jwks_url=jwks,
        )


class FakeD1:
    def __init__(self,rows):
        self.rows=rows
        self.sql=""
        self.params=[]
    def query(self,dbid,sql,params):
        self.sql=sql
        self.params=params
        assert dbid=="11111111-1111-4111-8111-111111111111"
        assert sql.startswith("SELECT")
        return {"results":self.rows},0.1


def test_identity_lookup_is_read_only_exact_generation_provider_subject():
    who=verify_external_token(signed(),TRUST,OfflineJWKS())
    client=FakeD1([link()])
    mapped=read_verified_identity_link(client,"11111111-1111-4111-8111-111111111111",GEN,who)
    assert mapped==UUID(LEGACY)
    assert client.params==[GEN,who.provider,who.subject]
    assert "email" not in client.sql.lower()
    assert "INSERT" not in client.sql and "UPDATE" not in client.sql


def test_lookup_unlinked_user_fails_without_creating_identity():
    who=verify_external_token(signed(),TRUST,OfflineJWKS())
    with pytest.raises(OIDCIdentityError):
        read_verified_identity_link(FakeD1([]),
            "11111111-1111-4111-8111-111111111111",GEN,who)
