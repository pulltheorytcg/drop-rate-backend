"""Signed-workload-only owner-free R2 export. No network or production DB."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
import jwt
import pytest

from app import d1_r2_shadow_export as export
from app import r2_first_catalogue as codec
from app import r2_first_service as service


PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC = PRIVATE.public_key()
FIXED_UUID = "11111111-1111-5111-8111-111111111111"


def valid_claims(**changes):
    now = int(datetime.now(timezone.utc).timestamp())
    return {
        "iss":export.OIDC_ISSUER, "aud":export.OIDC_AUDIENCE,
        "sub":export.EXPECTED_SUBJECT,
        "exp":now+120, "iat":now-5, "nbf":now-10,
        "repository":export.EXPECTED_REPOSITORY,
        "repository_id":export.EXPECTED_REPOSITORY_ID,
        "repository_owner_id":export.EXPECTED_OWNER_ID,
        "ref":"refs/heads/main",
        "workflow_ref":export.EXPECTED_WORKFLOW_REF,
        "event_name":"push", "runner_environment":"github-hosted",
        "run_id":"123456789", "sha":"a"*40,
        **changes,
    }


def signed(claims=None):
    return jwt.encode(claims or valid_claims(), PRIVATE, algorithm="RS256", headers={"kid":"fake"})


class MockJWKClient:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=PUBLIC)


@pytest.fixture(autouse=True)
def fixed_jwk(monkeypatch):
    monkeypatch.setattr(export, "_jwks_client", MockJWKClient())
    monkeypatch.setenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID", FIXED_UUID)

    async def admin_only(conn):
        if conn.user_id != FIXED_UUID:
            raise ValueError("Unauthorized RLS actor")
        conn.admin_checked = True

    monkeypatch.setattr(export, "require_platform_admin", admin_only)


@pytest.mark.parametrize("changes", [
    {"repository": "another/repo"},
    {"repository_id": "3"},
    {"repository_owner_id": "3"},
    {"sub":"repo:pulltheorytcg/drop-rate-backend:ref:refs/heads/main"},
    {"workflow_ref": "pulltheorytcg/drop-rate-backend/.github/workflows/other.yml@refs/heads/main"},
    {"event_name":"pull_request"},
    {"ref":"refs/heads/dev"},
    {"sub":"repo:pulltheorytcg/drop-rate-backend:pull_request"},
    {"runner_environment":"self-hosted"},
    {"sha":"bad"},
    {"aud":"wrong-audience"},
    {"iss":"https://other.invalid"},
])
def test_signed_but_unauthorized_workflows_cannot_export(changes):
    with pytest.raises(Exception) as error:
        export.verify_github_oidc("Bearer " + signed(valid_claims(**changes)))
    assert getattr(error.value, "status_code", None) in {401,403}


def test_valid_signature_and_exact_workflow_only():
    got=export.verify_github_oidc("Bearer " + signed())
    assert got["run_id"] == "123456789"
    with pytest.raises(Exception) as err:
        export.verify_github_oidc("Bearer broken.header.token")
    assert err.value.status_code == 401
    with pytest.raises(Exception) as err:
        export.verify_github_oidc("Bearer " + "z"*9000)
    assert err.value.status_code == 401
    with pytest.raises(Exception) as err:
        export.verify_github_oidc(None)
    assert err.value.status_code == 401


def fixtures():
    row = {
        "provider":"lorcast", "system_code":"DISNEY_LORCANA", "language":"English",
        "provider_id":"lorcast:fixture-101", "product_type":"CARD",
        "name":"Test Lorcana Card","set_id":"TEST","set_name":"Synthetic Test",
        "card_number":"001","rarity":"rare","finish":None,"release_date":"2026-01-01",
        "source_url":"https://api.lorcast.com/v0/sets",
    }
    bundle=codec.prepare_catalogue([row], provider="lorcast",system_code="DISNEY_LORCANA",
       language="English",source_url="https://api.lorcast.com/v0/sets",
       source_revision="synthetic",permission_ref="https://lorcast.com/docs/api")
    manifest=bundle.manifest
    manifest_raw=bundle._manifest_bytes
    sha=hashlib.sha256(manifest_raw).hexdigest()
    parts={sha:manifest_raw}
    for p,part in zip(bundle.parts,manifest["parts"],strict=True):
        parts[part["sha256"]]=p
    publication={
        "provider":"lorcast","system_code":"DISNEY_LORCANA","language":"English",
        "manifest_sha256":sha,"source_revision":manifest["source_revision"],
        "source_url":manifest["source_url"],"permission_ref":manifest["permission_ref"],
        "record_count":manifest["record_count"],"raw_bytes":manifest["raw_bytes"],
    }
    return parts,publication,manifest


class FakeConn:
    def __init__(self,publication):
        self.publication=publication
        self.user_id=None
        self.admin_checked=False

    async def __aenter__(self): return self
    async def __aexit__(self,*a): return False
    def transaction(self, **opts):
        assert opts=={"readonly":True, "isolation":"repeatable_read"}
        return self
    async def execute(self, sql, *params):
        assert sql.startswith("select set_config(")
        if "tcg.user_id" in sql:
            self.user_id=params[0]
        elif "tcg.request_id" in sql:
            assert isinstance(params[0], str) and params[0]
        else:
            raise AssertionError("Unexpected SQL config")
    async def fetchrow(self, sql, *scope):
        assert self.user_id==FIXED_UUID
        assert self.admin_checked
        assert "where active" in sql.lower()
        assert scope == (self.publication["provider"], self.publication["system_code"],
                         self.publication["language"])
        return self.publication


class FakePool:
    def __init__(self,publication):
        self.conn=FakeConn(publication)
    def acquire(self): return self.conn


class FakeStorage:
    def __init__(self,parts): self.parts=parts
    def read_verified_reference_snapshot(self,sha):
        return self.parts[sha]


def make_client(monkeypatch, *, valid_source=True):
    parts, publication,manifest=fixtures()
    if not valid_source:
        publication["manifest_sha256"]="f"*64
    monkeypatch.setattr(service,"storage",lambda:FakeStorage(parts))
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=FakePool(publication)
    return TestClient(app),parts,manifest


def test_routes_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED",raising=False)
    client,_,_=make_client(monkeypatch)
    assert client.get("/api/v1/internal/d1-shadow/manifest").status_code==404


def test_validated_manifest_part_and_unknown_ordinal(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client,parts,manifest=make_client(monkeypatch)
    header={"Authorization":"Bearer " + signed()}
    assert client.get("/api/v1/internal/d1-shadow/manifest").status_code==401
    answer=client.get("/api/v1/internal/d1-shadow/manifest",headers=header)
    assert answer.status_code==200
    assert answer.json()==manifest
    assert answer.headers["cache-control"]=="no-store"
    item=client.get("/api/v1/internal/d1-shadow/part/0",headers=header)
    assert item.status_code==200
    assert hashlib.sha256(item.content).hexdigest()==manifest["parts"][0]["sha256"]
    assert client.get("/api/v1/internal/d1-shadow/part/99",headers=header).status_code==404


def test_forged_active_manifest_never_leaks_part(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client,_,_=make_client(monkeypatch,valid_source=False)
    assert client.get("/api/v1/internal/d1-shadow/manifest",
        headers={"Authorization":"Bearer "+signed()}).status_code==503


def test_real_source_failure_logs_closed_stage_and_type_without_sensitive_values(monkeypatch, caplog):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)

    class BrokenStorage:
        def read_verified_reference_snapshot(self, sha):
            raise RuntimeError("sensitive-r2-secret?token=hidden")

    monkeypatch.setattr(service, "storage", lambda: BrokenStorage())
    with caplog.at_level("WARNING", logger=export.__name__):
        result = client.get("/api/v1/internal/d1-shadow/manifest",
                            headers={"Authorization": "Bearer " + signed()})
    assert result.status_code == 503
    assert result.json()["detail"] == "Verified source unavailable"
    assert "stage=manifest_object_read error_type=RuntimeError" in caplog.text
    assert "sensitive-r2-secret" not in caplog.text
    assert "token=hidden" not in caplog.text
    assert "Bearer " not in caplog.text


def test_storage_configuration_failure_is_503_without_leaking_configuration(monkeypatch, caplog):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)

    def broken():
        raise RuntimeError("sensitive-cloudflare-credential")

    monkeypatch.setattr(service, "storage", broken)
    with caplog.at_level("WARNING", logger=export.__name__):
        result = client.get("/api/v1/internal/d1-shadow/manifest",
                            headers={"Authorization": "Bearer " + signed()})
    assert result.status_code == 503
    assert "stage=storage_configuration error_type=RuntimeError" in caplog.text
    assert "sensitive-cloudflare-credential" not in caplog.text



def test_valid_manifest_is_read_under_admin_rls_context(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)
    response = client.get("/api/v1/internal/d1-shadow/manifest",
                          headers={"Authorization":"Bearer "+signed()})
    assert response.status_code==200
    # The fake registry itself rejects reads without a verified maintenance
    # user context and admin roster check.


def test_no_or_unapproved_maintenance_actor_keeps_rls_and_returns_503(monkeypatch,caplog):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)
    monkeypatch.delenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID",raising=False)
    with caplog.at_level("WARNING", logger=export.__name__):
        no_actor=client.get("/api/v1/internal/d1-shadow/manifest",
                            headers={"Authorization":"Bearer "+signed()})
    assert no_actor.status_code==503
    assert "stage=rls_authorized_read error_type=ValueError" in caplog.text
    assert "TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID" not in caplog.text

    monkeypatch.setenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID",
                       "22222222-2222-4222-8222-222222222222")
    with caplog.at_level("WARNING", logger=export.__name__):
        unauthorized=client.get("/api/v1/internal/d1-shadow/manifest",
                                headers={"Authorization":"Bearer "+signed()})
    assert unauthorized.status_code==503
    assert "stage=rls_authorized_read error_type=ValueError" in caplog.text



def test_yugioh_export_permits_only_its_signed_workflow_and_approved_events(monkeypatch):
    old_claims=valid_claims(event_name="schedule", workflow_ref=export.YUGIOH_WORKFLOW_REF)
    with pytest.raises(Exception) as exc:
        export.verify_github_oidc("Bearer "+signed(old_claims))
    assert exc.value.status_code == 403
    good=export.verify_github_oidc(
        "Bearer "+signed(old_claims),
        workflow_ref=export.YUGIOH_WORKFLOW_REF,
        allowed_events=("push","schedule"))
    assert good["run_id"] == "123456789"
    with pytest.raises(Exception) as err:
        export.verify_github_oidc(
            "Bearer "+signed(valid_claims(workflow_ref="other.yml", event_name="schedule")),
            workflow_ref=export.YUGIOH_WORKFLOW_REF,
            allowed_events=("push","schedule"))
    assert err.value.status_code == 403
    with pytest.raises(Exception) as err:
        export.verify_github_oidc(
            "Bearer "+signed(valid_claims(event_name="workflow_dispatch",
                                          workflow_ref=export.YUGIOH_WORKFLOW_REF)),
            workflow_ref=export.YUGIOH_WORKFLOW_REF,
            allowed_events=("push","schedule"))
    assert err.value.status_code == 403


def test_yugioh_export_is_fixed_to_original_source_scope(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED", "true")
    original, pub, _ = fixtures()
    pub.update(provider="ygoprodeck",system_code="YUGIOH")
    # A Lorcana manifest cannot be switched into Yu-Gi-Oh! by changing a
    # PostgreSQL pointer alone; exact source manifest binding must reject it.
    monkeypatch.setattr(service, "storage", lambda:FakeStorage(original))
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=FakePool(pub)
    client=TestClient(app)
    header={"Authorization": "Bearer "+signed(valid_claims(
        workflow_ref=export.YUGIOH_WORKFLOW_REF,event_name="schedule"))}
    denied=client.get("/api/v1/internal/d1-shadow/yugioh/manifest",headers=header)
    assert denied.status_code==503
    assert client.get("/api/v1/internal/d1-shadow/manifest",headers=header).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/yugioh/manifest").status_code==401


def test_yugioh_export_source_is_exact_and_sha_checked(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED", "true")
    sample={
        "provider":"ygoprodeck","system_code":"YUGIOH","language":"English",
        "provider_id":"ygoprodeck:synthetic-123",
        "product_type":"CARD","name":"Sample Creature",
        "set_id":"SYNTH","set_name":"Synthetic","card_number":"001",
        "rarity":"Common","finish":None,"release_date":"2026-01-01",
        "source_url":"https://db.ygoprodeck.com/api/v7/cardinfo.php",
    }
    prepared=codec.prepare_catalogue(
        [sample],provider="ygoprodeck",system_code="YUGIOH",language="English",
        source_url="https://db.ygoprodeck.com/api/v7/cardinfo.php",
        source_revision="test-ygo",permission_ref="https://ygoprodeck.com/api-guide/")
    raw=prepared._manifest_bytes
    digest=hashlib.sha256(raw).hexdigest()
    objects={digest:raw}
    for item,part in zip(prepared.parts,prepared.manifest["parts"],strict=True):
        objects[part["sha256"]]=item
    monkeypatch.setattr(service,"storage",lambda:FakeStorage(objects))
    p={key:prepared.manifest[key] for key in (
        "provider","system_code","language","source_revision",
        "source_url","permission_ref","record_count","raw_bytes")}
    p["manifest_sha256"]=digest
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=FakePool(p)
    client=TestClient(app)
    header={"Authorization":"Bearer "+signed(valid_claims(
        workflow_ref=export.YUGIOH_WORKFLOW_REF,event_name="push"))}
    got=client.get("/api/v1/internal/d1-shadow/yugioh/manifest",headers=header)
    assert got.status_code==200
    assert got.json()==prepared.manifest
    part=client.get("/api/v1/internal/d1-shadow/yugioh/part/0",headers=header)
    assert part.status_code==200
    assert hashlib.sha256(part.content).hexdigest()==prepared.manifest["parts"][0]["sha256"]
    assert client.get("/api/v1/internal/d1-shadow/yugioh/part/4",headers=header).status_code==404



def test_magic_signed_source_isolated_from_yugioh_and_lorcana(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED", "true")
    row={
        "provider":"mtgjson","system_code":"MAGIC_THE_GATHERING",
        "language":"English",
        "provider_id":"mtgjson:11111111-1111-5111-8111-000000000001:nonfoil",
        "product_type":"CARD","name":"Synthetic Magic",
        "set_id":"TST","set_name":"Test Set","card_number":"1",
        "rarity":"rare","finish":"nonfoil","release_date":"2026-01-01",
        "source_url":"https://mtgjson.com/api/v5/AllPrintings.json.xz",
        "details":{"cardmarket_product_id":"2001"},
    }
    bundle=codec.prepare_catalogue(
        [row],provider="mtgjson",system_code="MAGIC_THE_GATHERING",
        language="English",source_url="https://mtgjson.com/api/v5/AllPrintings.json.xz",
        source_revision="synthetic-source",
        permission_ref="https://mtgjson.com/license/")
    raw=bundle._manifest_bytes
    digest=hashlib.sha256(raw).hexdigest()
    objects={digest:raw}
    for item,part in zip(bundle.parts,bundle.manifest["parts"],strict=True):
        objects[part["sha256"]]=item
    p={k:bundle.manifest[k] for k in (
        "provider","system_code","language","source_revision",
        "source_url","permission_ref","record_count","raw_bytes")}
    p["manifest_sha256"]=digest
    monkeypatch.setattr(service,"storage",lambda:FakeStorage(objects))
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=FakePool(p)
    client=TestClient(app)
    magic_claims=valid_claims(workflow_ref=export.MAGIC_WORKFLOW_REF,event_name="push")
    header={"Authorization":"Bearer "+signed(magic_claims)}
    retrieved=client.get("/api/v1/internal/d1-shadow/magic/manifest",headers=header)
    assert retrieved.status_code==200
    assert retrieved.json()==bundle.manifest
    part=client.get("/api/v1/internal/d1-shadow/magic/part/0",headers=header)
    assert part.status_code==200
    assert hashlib.sha256(part.content).hexdigest()==bundle.manifest["parts"][0]["sha256"]
    assert client.get("/api/v1/internal/d1-shadow/yugioh/manifest",headers=header).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/manifest",headers=header).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/magic/part/999",headers=header).status_code==404
    assert client.get("/api/v1/internal/d1-shadow/magic/manifest").status_code==401

    deny_schedule={"Authorization":"Bearer "+signed(valid_claims(
        workflow_ref=export.MAGIC_WORKFLOW_REF,event_name="schedule"))}
    assert client.get("/api/v1/internal/d1-shadow/magic/manifest",headers=deny_schedule).status_code==403


def test_magic_manifest_requires_original_r2_scope_and_admin_rls(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    parts, p, _=fixtures()
    monkeypatch.setattr(service,"storage",lambda:FakeStorage(parts))
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=FakePool(p)
    client=TestClient(app)
    header={"Authorization":"Bearer "+signed(valid_claims(
        workflow_ref=export.MAGIC_WORKFLOW_REF))}
    # A Lorcana registry object cannot be exposed as Magic source.
    assert client.get("/api/v1/internal/d1-shadow/magic/manifest",headers=header).status_code==503
    monkeypatch.delenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID",raising=False)
    assert client.get("/api/v1/internal/d1-shadow/magic/manifest",headers=header).status_code==503


def test_legacy_r2_export_preserves_admin_rls_and_fixed_source(monkeypatch):
    import json
    from contextlib import asynccontextmanager
    from uuid import UUID
    from app import catalogue_r2_live as legacy

    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    card_set={
        "provider":"example_provider","system_code":"POKEMON_TCG",
        "language":"English","set_id":"TEST-SET","name":"Synthetic Set",
        "release_date":"2026-01-01","declared_card_count":1,
    }
    raw=json.dumps([card_set],sort_keys=True,separators=(",",":")).encode()
    sha=hashlib.sha256(raw).hexdigest()
    manifest={
        "schema":legacy.SCHEMA,"generation":export.LEGACY_R2_SOURCE_GENERATION,
        "counts":{r:(1 if r=="reference_sets" else 0) for r in legacy.RELATIONS},
        "parts":[{"relation":"reference_sets","sha256":sha,
                  "raw_bytes":len(raw),"rows":1}],
        "raw_bytes":len(raw),
    }
    monkeypatch.setattr(export,"LEGACY_R2_EXPECTED_COUNTS",manifest["counts"])
    monkeypatch.setattr(export,"LEGACY_R2_EXPECTED_PARTS",1)
    monkeypatch.setattr(export,"LEGACY_R2_EXPECTED_RAW_BYTES",len(raw))

    class LegacySQL:
        def __init__(self):
            self.user_id=FIXED_UUID
            self.admin_checked=False
        async def fetchrow(self,sql):
            assert sql==legacy.STATE_SQL
            assert self.admin_checked
            return {"generation":export.LEGACY_R2_SOURCE_GENERATION,"published_generation":export.LEGACY_R2_SOURCE_GENERATION,
                    "manifest":manifest}

    @asynccontextmanager
    async def admin_read(_pool, actor, _request_id, *, readonly_snapshot):
        assert str(actor)==FIXED_UUID
        assert isinstance(actor,UUID)
        assert readonly_snapshot is True
        yield LegacySQL()

    monkeypatch.setattr(export,"user_connection",admin_read)
    monkeypatch.setattr(service,"storage",lambda:FakeStorage({sha:raw}))
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=object()
    client=TestClient(app)
    workflow_claims=valid_claims(workflow_ref=export.LEGACY_R2_WORKFLOW_REF)
    headers={"Authorization":"Bearer "+signed(workflow_claims)}
    reply=client.get("/api/v1/internal/d1-shadow/legacy/manifest",headers=headers)
    assert reply.status_code==200
    assert reply.json()==manifest
    assert reply.headers["cache-control"]=="no-store"
    record=client.get("/api/v1/internal/d1-shadow/legacy/part/0",headers=headers)
    assert record.status_code==200 and record.content==raw
    assert client.get("/api/v1/internal/d1-shadow/legacy/part/1",headers=headers).status_code==404

    # Independent daily D1 migrator must present the new exact workflow ref.
    # The source-only legacy audit may not use the mutating workflow's route.
    assert client.get("/api/v1/internal/d1-shadow/legacy-d1/manifest",
                      headers=headers).status_code==403
    writer_headers={"Authorization":"Bearer "+signed(valid_claims(
        workflow_ref=export.LEGACY_D1_WORKFLOW_REF,event_name="schedule"))}
    writer_manifest=client.get("/api/v1/internal/d1-shadow/legacy-d1/manifest",
                               headers=writer_headers)
    assert writer_manifest.status_code==200
    assert writer_manifest.json()==manifest
    writer_part=client.get("/api/v1/internal/d1-shadow/legacy-d1/part/0",
                           headers=writer_headers)
    assert writer_part.status_code==200
    assert hashlib.sha256(writer_part.content).hexdigest()==sha
    assert client.get("/api/v1/internal/d1-shadow/legacy-d1/part/2",
                      headers=writer_headers).status_code==404
    assert client.get("/api/v1/internal/d1-shadow/legacy/manifest",
                      headers=writer_headers).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/yugioh/manifest",
                      headers=writer_headers).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/legacy-d1/manifest").status_code==401
    dispatch={"Authorization":"Bearer "+signed(valid_claims(
        workflow_ref=export.LEGACY_D1_WORKFLOW_REF,event_name="workflow_dispatch"))}
    assert client.get("/api/v1/internal/d1-shadow/legacy-d1/manifest",
                      headers=dispatch).status_code==403

    assert client.get("/api/v1/internal/d1-shadow/legacy/manifest").status_code==401
    assert client.get("/api/v1/internal/d1-shadow/magic/manifest",headers=headers).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/legacy/manifest",
                      headers={"Authorization":"Bearer "+signed()}).status_code==403
    monkeypatch.delenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID",raising=False)
    assert client.get("/api/v1/internal/d1-shadow/legacy/manifest",headers=headers).status_code==503


def test_legacy_export_mismatched_generation_never_reaches_r2(monkeypatch):
    from contextlib import asynccontextmanager
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")

    class OldSQL:
        user_id=FIXED_UUID
        admin_checked=False
        async def fetchrow(self,sql):
            assert self.admin_checked
            return {"generation":export.LEGACY_R2_SOURCE_GENERATION,"published_generation":export.LEGACY_R2_SOURCE_GENERATION-1,
                    "manifest":{}}

    @asynccontextmanager
    async def old_source(_pool,actor,_request_id,*,readonly_snapshot):
        assert readonly_snapshot
        yield OldSQL()

    monkeypatch.setattr(export,"user_connection",old_source)
    monkeypatch.setattr(service,"storage",lambda:(_ for _ in ()).throw(
        AssertionError("Never read R2 when publication is incomplete")))
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=object()
    client=TestClient(app)
    headers={"Authorization":"Bearer "+signed(valid_claims(
        workflow_ref=export.LEGACY_R2_WORKFLOW_REF))}
    assert client.get("/api/v1/internal/d1-shadow/legacy/manifest",
                      headers=headers).status_code==503


def test_followon_workflow_identity_and_source_scope_never_cross_contaminate(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    scope=export.FOLLOWON_SOURCE_MAP["sports"]
    sample={
        "provider":scope[0],"system_code":scope[1],"language":scope[2],
        "provider_id":"cardcollectorcapital:test-1",
        "product_type":"CARD","name":"Synthetic Sports Reference",
        "set_id":"SPORTS","set_name":"Sports Set","card_number":"1",
        "rarity":"Base","finish":None,"release_date":"2026-01-01",
        "source_url":"https://example.org/source",
    }
    prepared=codec.prepare_catalogue(
        [sample],provider=scope[0],system_code=scope[1],language=scope[2],
        source_url="https://example.org/source",
        source_revision="synthetic-test",permission_ref="https://example.org/licence")
    raw=prepared._manifest_bytes
    manifest_sha=hashlib.sha256(raw).hexdigest()
    objects={manifest_sha:raw}
    for content,part in zip(prepared.parts,prepared.manifest["parts"],strict=True):
        objects[part["sha256"]]=content

    async def source_verified(_request, actual_scope):
        assert actual_scope==scope
        return FakeStorage(objects),{},prepared.manifest,raw

    monkeypatch.setattr(export,"_active_catalogue_manifest",source_verified)
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=object()
    client=TestClient(app)
    claims=valid_claims(workflow_ref=export.FOLLOWON_WORKFLOW_REF,event_name="schedule")
    headers={"Authorization":"Bearer "+signed(claims)}
    result=client.get("/api/v1/internal/d1-shadow/followon/sports/manifest",headers=headers)
    assert result.status_code==200
    assert result.json()==prepared.manifest
    part=client.get("/api/v1/internal/d1-shadow/followon/sports/part/0",headers=headers)
    assert part.status_code==200
    assert hashlib.sha256(part.content).hexdigest()==prepared.manifest["parts"][0]["sha256"]
    assert client.get("/api/v1/internal/d1-shadow/followon/unknown/manifest",headers=headers).status_code==404
    assert client.get("/api/v1/internal/d1-shadow/followon/sports/part/10",headers=headers).status_code==404
    assert client.get("/api/v1/internal/d1-shadow/followon/sports/manifest").status_code==401
    assert client.get("/api/v1/internal/d1-shadow/followon/sports/manifest",
                      headers={"Authorization":"Bearer "+signed()}).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/followon/sports/manifest",
                      headers={"Authorization":"Bearer "+signed(valid_claims(
                          workflow_ref=export.FOLLOWON_WORKFLOW_REF,
                          event_name="workflow_dispatch"))}).status_code==403
    assert client.get("/api/v1/internal/d1-shadow/legacy/manifest",headers=headers).status_code==403


def test_followon_source_with_wrong_rls_partition_fails_closed(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client,_,_=make_client(monkeypatch)
    headers={"Authorization":"Bearer "+signed(valid_claims(
        workflow_ref=export.FOLLOWON_WORKFLOW_REF))}
    assert client.get("/api/v1/internal/d1-shadow/followon/sports/manifest",
                      headers=headers).status_code==503
