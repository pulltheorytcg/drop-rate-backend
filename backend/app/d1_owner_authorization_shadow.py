"""INACTIVE OIDC-to-owner authorization proof for Cloudflare D1 migration.

PostgreSQL RLS does not exist in D1. This code does not authenticate raw JWTs,
issue sessions, trust role claims, create users or switch FastAPI auth. It MUST
only receive a subject returned by verify_external_token(...) with a fixed
server-side TrustedOIDCProvider; it queries an independently verified private
D1 source generation, and grants exactly ONE owner-scoped context.

The platform-admin roster is an additional unimplemented cutover gate. Even a
valid PLATFORM_ADMIN membership remains owner-portal-only here. Never infer
founder business privileges from claims or founder_slot alone.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import UUID

from .auth_oidc_shadow import (
    OIDCIdentityError, TrustedOIDCProvider, VerifiedExternalSubject,
)

GENERATION_RE = re.compile(r"src-[0-9a-f]{32,64}\Z")
D1_ID_RE = re.compile(r"[0-9a-f-]{36}\Z")


@dataclass(frozen=True, slots=True)
class D1OwnerScope:
    legacy_user_id: UUID
    owner_id: UUID
    owner_type: str
    membership_role: str
    founder_slot: int | None
    portal: str
    owner_portal_allowed: bool
    founder_hq_allowed: bool
    business_allowed: bool
    founder_roster_review_required: bool


AUTHORIZATION_SQL = """
SELECT
  g.state AS generation_state,
  l.generation_id, l.legacy_user_id, l.provider,
  l.external_subject, l.verified_at,
  m.owner_id, m.role AS membership_role,
  m.active AS membership_active,
  o.owner_type, o.active AS owner_active, o.founder_slot
FROM ops_shadow_identity_map AS l
JOIN ops_shadow_generations AS g
  ON g.generation_id=l.generation_id
JOIN ops_shadow_memberships AS m
  ON m.generation_id=l.generation_id AND m.legacy_user_id=l.legacy_user_id
JOIN ops_shadow_owners AS o
  ON o.generation_id=m.generation_id AND o.id=m.owner_id
WHERE l.generation_id=? AND l.provider=? AND l.external_subject=?
LIMIT 3
"""


def _canonical_uuid(value: object) -> UUID:
    try:
        parsed = UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise OIDCIdentityError("Invalid privately mapped UUID") from None
    if str(parsed) != value:
        raise OIDCIdentityError("Noncanonical privately mapped UUID")
    return parsed


def validate_owner_scope_rows(
    rows: object, token: VerifiedExternalSubject,
    *, trust: TrustedOIDCProvider, generation_id: str,
) -> D1OwnerScope:
    """Fail closed on inactive/revoked/ambiguous/forged memberships."""
    if (not isinstance(token,VerifiedExternalSubject)
        or not isinstance(trust,TrustedOIDCProvider)
        or token.provider != trust.provider
        or token.issuer != trust.issuer
        or not isinstance(token.subject,str)
        or not token.subject):
        raise OIDCIdentityError("Identity provider is not independently verified")
    if not isinstance(generation_id,str) or GENERATION_RE.fullmatch(generation_id) is None:
        raise OIDCIdentityError("Unapproved private identity generation")
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        raise OIDCIdentityError("No unique verified active owner membership")
    row=rows[0]
    if (row.get("generation_state")!="PARITY_VERIFIED"
        or row.get("generation_id")!=generation_id
        or row.get("provider")!=token.provider
        or row.get("external_subject")!=token.subject
        or not isinstance(row.get("verified_at"),str)
        or not row["verified_at"].strip()
        or type(row.get("membership_active")) is not int
        or row["membership_active"]!=1
        or type(row.get("owner_active")) is not int
        or row["owner_active"]!=1):
        raise OIDCIdentityError("Identity mapping or owner membership is inactive/unverified")
    role=row.get("membership_role")
    owner_type=row.get("owner_type")
    slot=row.get("founder_slot")
    if role not in ("OWNER","PLATFORM_ADMIN") or owner_type not in ("FOUNDER","CONSIGNOR"):
        raise OIDCIdentityError("Unexpected private membership role/type")
    if (owner_type=="FOUNDER" and (type(slot) is not int or slot not in (1,2,3))
        or owner_type=="CONSIGNOR" and slot is not None
        or role=="PLATFORM_ADMIN" and owner_type!="FOUNDER"):
        raise OIDCIdentityError("Founder role and owner roster are inconsistent")
    user_id=_canonical_uuid(row.get("legacy_user_id"))
    owner_id=_canonical_uuid(row.get("owner_id"))
    # Do NOT trust owner_id, role, founder_slot, email, or app_metadata in
    # external JWT claims. A separately signed founder-roster proof is still
    # needed before any platform-admin/business authorization can be enabled.
    return D1OwnerScope(
        legacy_user_id=user_id,owner_id=owner_id,
        owner_type=owner_type,membership_role=role,founder_slot=slot,
        portal="OWNER_PORTAL",
        owner_portal_allowed=True,
        founder_hq_allowed=False,
        business_allowed=False,
        founder_roster_review_required=(role=="PLATFORM_ADMIN"),
    )


def read_verified_d1_owner_scope(
    client, d1_database_id: str, generation_id: str,
    token: VerifiedExternalSubject, *, trust: TrustedOIDCProvider,
) -> D1OwnerScope:
    """Resolve verified external subject to unique active owner, read-only."""
    if (not isinstance(d1_database_id,str)
        or D1_ID_RE.fullmatch(d1_database_id) is None):
        raise OIDCIdentityError("Unexpected private D1 selector")
    # Fail before even constructing a D1 query with an unapproved provider.
    if (not isinstance(trust,TrustedOIDCProvider)
        or not isinstance(token,VerifiedExternalSubject)
        or token.issuer!=trust.issuer or token.provider!=trust.provider
        or not isinstance(generation_id,str)
        or GENERATION_RE.fullmatch(generation_id) is None):
        raise OIDCIdentityError("Unverified external identity or D1 generation")
    try:
        response,_=client.query(
            d1_database_id,AUTHORIZATION_SQL,
            [generation_id,token.provider,token.subject],
        )
        rows=response.get("results") if isinstance(response,dict) else None
    except Exception:
        raise OIDCIdentityError("Private owner authorization unavailable") from None
    return validate_owner_scope_rows(
        rows,token,trust=trust,generation_id=generation_id,
    )
