"""Offline D1 owner boundary: real SQLite shadow schema + verified OIDC.

No production connections, provider registration, key migration or Auth switch.
"""
from __future__ import annotations

from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth_oidc_shadow import (
    OIDCIdentityError,TrustedOIDCProvider,verify_external_token,
)
from app.d1_owner_authorization_shadow import (
    AUTHORIZATION_SQL,read_verified_d1_owner_scope,validate_owner_scope_rows,
)

SQL=(Path(__file__).resolve().parents[1]/
     "database/cloudflare_d1/0001_operational_shadow.sql").read_text()
DBID="11111111-1111-4111-8111-111111111111"
GEN="src-"+"a"*32
OWNER1="11111111-1111-4111-8111-111111111112"
OWNER2="11111111-1111-4111-8111-111111111113"
USER1="11111111-1111-4111-8111-111111111114"
USER2="11111111-1111-4111-8111-111111111115"
SHA="b"*64
TRUST=TrustedOIDCProvider(
    provider="external_oidc",issuer="https://id.example.com/",
    audience="drop-rate-private-api",
    jwks_url="https://id.example.com/.well-known/jwks.json",
)
KEY=rsa.generate_private_key(public_exponent=65537,key_size=2048)


class OfflineJwks:
    def get_signing_key_from_jwt(self,_token):
        return SimpleNamespace(key=KEY.public_key())


def verified(*,subject="external-1",**claims):
    now=int(datetime.now(timezone.utc).timestamp())
    body={"iss":TRUST.issuer,"aud":TRUST.audience,"sub":subject,
          "iat":now,"exp":now+300,"role":"PLATFORM_ADMIN",
          "owner_id":OWNER2,"founder_slot":2,
          "email":"forged-founder@example.com",
          "app_metadata":{"role":"PLATFORM_ADMIN"}}
    body.update(claims)
    token=jwt.encode(body,KEY,algorithm="RS256",headers={"kid":"offline"})
    return verify_external_token(token,TRUST,OfflineJwks())


class D1Adapter:
    def __init__(self,conn):
        self.conn=conn
        self.reads=0
        self.last_params=None
        self.last_sql=""
    def query(self,database_id,statement,params):
        assert database_id==DBID
        assert statement==AUTHORIZATION_SQL
        assert len(params)==3
        assert statement.lstrip().startswith("SELECT")
        self.last_sql=statement
        self.last_params=list(params)
        self.reads+=1
        rows=[dict(r) for r in self.conn.execute(statement,params)]
        return {"results":rows},0.0


@pytest.fixture
def d1():
    db=sqlite3.connect(":memory:")
    db.row_factory=sqlite3.Row
    db.executescript(SQL)
    db.execute("INSERT INTO ops_shadow_generations "
               "(generation_id,source_manifest_sha256,source_captured_at,source_schema_sha256,state) "
               "VALUES (?,?,?,?,'PARITY_VERIFIED')",
               (GEN,SHA,"2026-11-09T08:00:00Z",SHA))
    for user,owner,slot,kind,role,subject in (
        (USER1,OWNER1,1,"FOUNDER","PLATFORM_ADMIN","external-1"),
        (USER2,OWNER2,None,"CONSIGNOR","OWNER","external-2"),
    ):
        db.execute("""INSERT INTO ops_shadow_identity_map
            (generation_id,legacy_user_id,provider,external_subject,verified_at)
            VALUES(?,?,?,?,?)""",
            (GEN,user,TRUST.provider,subject,"2026-11-09T08:00:00Z"))
        db.execute("""INSERT INTO ops_shadow_owners
            (generation_id,id,display_name,owner_type,founder_slot,active,
             commission_bps,source_row_sha256,source_row_json)
            VALUES(?,?,?,?,?,1,?,?,?)""",
            (GEN,owner,"Synthetic",kind,slot,0 if kind=="FOUNDER" else 1000,SHA,"{}"))
        db.execute("""INSERT INTO ops_shadow_memberships
            (generation_id,id,legacy_user_id,owner_id,role,active,
             source_row_sha256,source_row_json)
            VALUES(?,?,?,?,?,1,?,?)""",
            (GEN,str(UUID(int=1000+len(db.execute(
                'SELECT 1 FROM ops_shadow_memberships').fetchall()))),
             user,owner,role,SHA,"{}"))
    yield db
    db.close()


def scope(d1,who=None):
    cloud=D1Adapter(d1)
    result=read_verified_d1_owner_scope(
        cloud,DBID,GEN,who or verified(),trust=TRUST,
    )
    assert cloud.reads==1
    assert cloud.last_params==[GEN,(who or verified()).provider,
                               (who or verified()).subject]
    return result


def test_signed_founder_subject_only_gets_owner_scope_not_global_admin(d1):
    access=scope(d1)
    assert access.legacy_user_id==UUID(USER1)
    assert access.owner_id==UUID(OWNER1)
    assert access.owner_type=="FOUNDER"
    assert access.membership_role=="PLATFORM_ADMIN"
    assert access.founder_slot==1
    assert access.owner_portal_allowed is True
    assert access.founder_roster_review_required is True
    assert access.founder_hq_allowed is False
    assert access.business_allowed is False
    assert access.portal=="OWNER_PORTAL"


def test_signed_consignor_subject_is_isolated_even_with_founder_jwt_claims(d1):
    user=verified(subject="external-2",owner_id=OWNER1,
                  founder_slot=1,role="PLATFORM_ADMIN")
    access=scope(d1,user)
    assert access.owner_id==UUID(OWNER2)
    assert access.membership_role=="OWNER"
    assert access.owner_type=="CONSIGNOR"
    assert access.founder_hq_allowed is False
    assert access.business_allowed is False
    assert not access.founder_roster_review_required


@pytest.mark.parametrize("actor",["external-3","external-1-wrong"])
def test_unlinked_subject_can_never_infer_owner_from_email_or_role(d1,actor):
    with pytest.raises(OIDCIdentityError,match="unique"):
        scope(d1,verified(subject=actor))


@pytest.mark.parametrize("table,field,where",[
    ("ops_shadow_memberships","active=0","legacy_user_id='"+USER1+"'"),
    ("ops_shadow_owners","active=0","id='"+OWNER1+"'"),
    ("ops_shadow_generations","state='STAGING'","generation_id='"+GEN+"'"),
    ("ops_shadow_memberships","role='SUSPENDED'","legacy_user_id='"+USER1+"'"),
    ("ops_shadow_memberships","role='OWNER'","legacy_user_id='"+USER1+"'"),
])
def test_revocations_or_role_inconsistencies_block_or_limit_access(d1,table,field,where):
    d1.execute(f"UPDATE {table} SET {field} WHERE {where}")
    if field=="role='OWNER'":
        # A genuine membership downgrade is owner-portal-only, not admin.
        access=scope(d1)
        assert access.membership_role=="OWNER"
        assert not access.founder_hq_allowed
        return
    with pytest.raises(OIDCIdentityError):
        scope(d1)


def test_two_active_memberships_for_one_external_subject_are_denied(d1):
    d1.execute("""INSERT INTO ops_shadow_memberships
      (generation_id,id,legacy_user_id,owner_id,role,active,
       source_row_sha256,source_row_json)
      VALUES(?,?,?,?, 'OWNER',1,?,?)""",
      (GEN,str(UUID(int=2222)),USER1,OWNER2,SHA,"{}"))
    with pytest.raises(OIDCIdentityError,match="unique"):
        scope(d1)


def test_no_trust_in_unapproved_provider_or_unverified_generation(d1):
    cloud=D1Adapter(d1)
    wrong_trust=TrustedOIDCProvider(
        provider="other_oidc",issuer="https://other.example.com/",
        audience=TRUST.audience,
        jwks_url="https://other.example.com/.well-known/jwks.json")
    with pytest.raises(OIDCIdentityError):
        read_verified_d1_owner_scope(cloud,DBID,GEN,verified(),trust=wrong_trust)
    with pytest.raises(OIDCIdentityError):
        read_verified_d1_owner_scope(cloud,DBID,"src-unknown",verified(),trust=TRUST)
    assert cloud.reads==0


def test_invalid_signature_and_unapproved_issuer_are_denied_before_d1(d1):
    now=int(datetime.now(timezone.utc).timestamp())
    forged=jwt.encode(
        {"iss":TRUST.issuer,"aud":TRUST.audience,"sub":"external-1",
         "iat":now,"exp":now+100,"role":"PLATFORM_ADMIN"},
        "attacker",algorithm="HS256",
    )
    with pytest.raises(OIDCIdentityError):
        verify_external_token(forged,TRUST,OfflineJwks())


def test_private_owner_join_uses_indexed_exact_provider_and_subject(d1):
    plan=[tuple(r) for r in d1.execute(
        "EXPLAIN QUERY PLAN "+AUTHORIZATION_SQL,
        (GEN,"external_oidc","external-1"))]
    description=" ".join(str(r[-1]) for r in plan).lower()
    assert "index" in description or "primary key" in description
    assert "external_subject=?" in AUTHORIZATION_SQL
    assert "JOIN ops_shadow_memberships" in AUTHORIZATION_SQL
    assert "JOIN ops_shadow_owners" in AUTHORIZATION_SQL
    assert "limit 3" in AUTHORIZATION_SQL.lower()


def test_transport_failure_denies_access_without_printing_user_identity(d1):
    class FailD1:
        def query(self,*_args,**_kwargs):
            raise RuntimeError("PRIVATE_EMAIL token and owner data")
    with pytest.raises(OIDCIdentityError) as exc:
        read_verified_d1_owner_scope(FailD1(),DBID,GEN,verified(),trust=TRUST)
    assert "PRIVATE_EMAIL" not in str(exc.value)


def test_bogus_role_claim_can_never_enable_founder_business(d1):
    for token_claim in (
        {"role":"PLATFORM_ADMIN","owner_id":OWNER2,"founder_slot":2},
        {"role":"OWNER","app_metadata":{"role":"PLATFORM_ADMIN"}},
        {"role":"root","email":"founder@example.com"},
    ):
        who=verified(**token_claim)
        access=scope(d1,who)
        assert access.owner_id==UUID(OWNER1)
        assert access.founder_hq_allowed is False
        assert access.business_allowed is False
