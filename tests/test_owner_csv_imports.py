"""Seller Hub collections import: reuse founder adapter with strict owner isolation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import imports, owner_imports
from app.import_review import remaining_issues_after_catalogue_selection


def request():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="seller-csv-tests"),
    )


def test_owner_api_is_allowlisted_and_founder_apis_remain_admin_only():
    from pathlib import Path
    from fastapi.routing import APIRoute
    prefix = "/api/v1/owner/imports"
    paths = {
        (route.path, tuple(sorted(route.methods))): route
        for route in owner_imports.router.routes if isinstance(route, APIRoute)
    }
    expected = {
        (prefix + "/preview", ("POST",)),
        (prefix, ("GET",)),
        (prefix + "/{batch_id}", ("GET",)),
        (prefix + "/{batch_id}/commit", ("POST",)),
        (prefix + "/{batch_id}/candidates/{candidate_id}/resolve", ("POST",)),
        (prefix + "/{batch_id}/candidates/{candidate_id}/skip", ("POST",)),
        (prefix + "/catalogue-search", ("GET",)),
    }
    assert set(paths) == expected
    assert all(route.dependencies for route in paths.values())
    assert all(any(dependency.dependency.__name__ == "require_owner_portal_request"
                   for dependency in route.dependencies) for route in paths.values())
    main = (Path(__file__).resolve().parents[1] / "backend/app/main.py").read_text()
    assert "app.include_router(owner_csv_imports_router)" in main
    assert "app.include_router(imports_router, dependencies=[Depends(require_platform_admin_request)])" in main
    assert "app.include_router(import_enrichment_router, dependencies=[Depends(require_platform_admin_request)])" in main
    assert "app.include_router(import_review_router, dependencies=[Depends(require_platform_admin_request)])" in main
    owner_api = (Path(__file__).resolve().parents[1] / "backend/app/owner_imports.py").read_text()
    assert "from .import_enrichment import" not in owner_api
    assert "import_enrichment_router" not in owner_api
    assert "require_owner_portal_request" in owner_api


@pytest.mark.parametrize("name", ["portfolio.csv", "portfolio.CSV", "set.tsv"])
def test_supported_csv_tsv_extensions(name):
    data = imports.ImportPreviewRequest(filename=name, content="Card,Set\nName,OP01")
    assert data.filename == name


@pytest.mark.parametrize("name", ["bad.xlsx", "bad.json", "bad.pdf", "bad.txt"])
def test_unsupported_formats_are_not_misrepresented_as_working(name):
    with pytest.raises(ValidationError):
        imports.ImportPreviewRequest(filename=name, content="Name,Set\nSome,OP01")


def test_mapping_unknown_or_blank_database_field_is_rejected():
    for mapping in ({"owner_id": "Email"}, {"name": ""}, {"shopify_product_id": "42"}):
        with pytest.raises(ValidationError):
            imports.ImportPreviewRequest(
                filename="other.csv", content="x\ny", column_mapping=mapping,
            )


def test_friendly_holodex_and_generic_column_mapping_is_explicit():
    r = imports.ImportPreviewRequest(
        filename="holodex.csv", content="Character,Expansion\nLuffy,OP01",
        column_mapping={"name": "Character", "set_name": "Expansion"},
        adapter="HOLODEX",
    )
    assert r.column_mapping["name"] == "Character"


def test_manual_catalogue_choice_clears_only_identity_review_issues():
    result = remaining_issues_after_catalogue_selection([
        "catalogue_not_found", "catalogue_admin_review_required",
        "unrecognised_card_condition",
    ])
    assert result == ["unrecognised_card_condition"]


@pytest.fixture
def fake_preview_db(monkeypatch):
    owner_id = uuid4()
    role = {"value": "OWNER"}
    calls = {"batch": [], "candidates": []}
    catalogue_id = uuid4()

    class Connection:
        async def fetchrow(self, statement, *args):
            assert "where owner_id = $1 and source_sha256 = $2" in statement
            assert args[0] == owner_id
            return None

        async def execute(self, statement, *args):
            if "insert into tcg.import_batches" in statement:
                assert args[1] == owner_id
                calls["batch"].append(args)
            elif "insert into tcg.import_candidates" in statement:
                assert args[1] == owner_id
                calls["candidates"].append(args)
            else:
                raise AssertionError(statement)
            return "INSERT 0 1"

        @asynccontextmanager
        async def transaction(self):
            yield

    @asynccontextmanager
    async def fake_connection(pool, user_id, request_id):
        yield Connection()

    async def fake_owner(connection):
        return {"id": owner_id, "role": role["value"], "owner_type": "CONSIGNOR"}

    async def fake_match(connection, normalized):
        if normalized.get("name") == "Known Card":
            return catalogue_id, []
        return None, ["catalogue_not_found"]

    async def fake_previous(connection, owner):
        assert owner == owner_id
        return None, {}

    monkeypatch.setattr(imports, "user_connection", fake_connection)
    monkeypatch.setattr(imports, "_owner", fake_owner)
    monkeypatch.setattr(imports, "_catalogue_match", fake_match)
    monkeypatch.setattr(imports, "_collectr_previous_snapshot", fake_previous)
    return SimpleNamespace(owner_id=owner_id, role=role, calls=calls, catalogue_id=catalogue_id)


def test_collectr_seller_unknown_canonical_goes_to_review_not_public_catalogue(fake_preview_db):
    csv_text = (
        "Portfolio Name,Product Name,Game,Set,Number,Variance,Quantity,Average Cost Paid,Language\n"
        "Mine,Unlisted Card,One Piece,OP01,001,Foil,3,1.25,English\n"
    )
    payload = imports.ImportPreviewRequest(
        filename="collectr-export.csv", content=csv_text, adapter="COLLECTR",
    )
    response = asyncio.run(imports.preview_import(
        payload, request(), SimpleNamespace(user_id=uuid4())
    ))
    assert response["adapter"] == "COLLECTR"
    assert response["physical_units"] == 3
    assert response["ready_units"] == 0
    assert response["review_rows"] == 1
    candidate = response["candidates"][0]
    assert candidate["status"] == "REVIEW"
    assert "catalogue_admin_review_required" in candidate["issues"]
    assert "catalogue_not_found" in candidate["issues"]
    assert not candidate["normalized_record"].get("collectr_create_catalogue")
    assert len(fake_preview_db.calls["batch"]) == 1
    assert len(fake_preview_db.calls["candidates"]) == 1


def test_founder_collectr_canonical_provision_flow_unchanged(fake_preview_db):
    fake_preview_db.role["value"] = "PLATFORM_ADMIN"
    payload = imports.ImportPreviewRequest(
        filename="collectr-export.csv",
        content="Portfolio Name,Product Name,Game,Set,Number,Variance,Quantity,Average Cost Paid,Language\n"
                "Mine,Unlisted Card,One Piece,OP01,001,Foil,3,1.25,English",
        adapter="COLLECTR",
    )
    result = asyncio.run(imports.preview_import(
        payload, request(), SimpleNamespace(user_id=uuid4()),
    ))
    assert result["ready_units"] == 3
    assert result["review_rows"] == 0
    assert result["candidates"][0]["normalized_record"]["collectr_create_catalogue"] is True


def test_other_tsv_with_explicit_column_mapping_uses_existing_catalogue(fake_preview_db):
    payload = imports.ImportPreviewRequest(
        filename="custom.tsv",
        content="Character\tExpansion\tCollector\tCopies\n"
                "Known Card\tOP01\t001\t2",
        adapter="GENERIC_CSV",
        default_game="One Piece",
        default_language="English",
        column_mapping={
            "name": "Character", "set_name": "Expansion",
            "card_number": "Collector", "quantity": "Copies",
        },
    )
    result = asyncio.run(imports.preview_import(
        payload, request(), SimpleNamespace(user_id=uuid4()),
    ))
    assert result["adapter"] == "GENERIC_CSV"
    assert result["ready_units"] == 2
    assert result["review_rows"] == 0
    assert result["detected_columns"]["name"] == "Character"
    assert result["detected_columns"]["quantity"] == "Copies"


def test_unsupported_file_header_mapping_never_commits(fake_preview_db):
    payload = imports.ImportPreviewRequest(
        filename="custom.csv",
        content="Character,Expansion\nKnown Card,OP01",
        adapter="GENERIC_CSV",
        column_mapping={"name": "Not in source"},
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(imports.preview_import(payload, request(), SimpleNamespace(user_id=uuid4())))
    assert exc.value.status_code == 422
    assert fake_preview_db.calls["batch"] == []
    assert fake_preview_db.calls["candidates"] == []


def test_seller_cannot_create_unreviewed_shared_canonical_during_commit(monkeypatch):
    owner_id=uuid4()
    batch_id=uuid4()
    values={"writes":[]}

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield

        async def fetchrow(self, sql, *args):
            if "select * from tcg.import_batches" in sql:
                assert args[1] == owner_id
                return {"id":batch_id,"version":1,"status":"PREVIEW","adapter":"COLLECTR"}
            if "select normalized_record" in sql:
                return {"normalized_record":{"collectr_baseline_batch_id":None}}
            raise AssertionError(sql)

        async def fetchval(self, sql, *args):
            if "select id from tcg.owners" in sql:
                assert args == (owner_id,)
                return owner_id
            if "from tcg.import_batches" in sql:
                return None
            raise AssertionError(sql)

        async def fetch(self, sql, *args):
            if "from tcg.import_candidates" in sql and "status = 'READY'" in sql:
                return [{"id":uuid4(),"normalized_record":{"collectr_create_catalogue":True}}]
            raise AssertionError(sql)

        async def execute(self, sql, *args):
            values["writes"].append((sql, args))

    @asynccontextmanager
    async def fake_connection(pool, user_id, request_id):
        yield Connection()

    async def fake_owner(conn):
        return {"id":owner_id,"role":"OWNER"}

    monkeypatch.setattr(imports,"user_connection",fake_connection)
    monkeypatch.setattr(imports,"_owner",fake_owner)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(imports.commit_import_batch(
            batch_id, imports.ImportCommitRequest(version=1),
            request(), SimpleNamespace(user_id=uuid4()),
        ))
    assert exc.value.status_code == 409
    assert not values["writes"]


def test_collectr_skipped_new_row_never_becomes_baseline_inventory(monkeypatch):
    owner=uuid4()
    batch=uuid4()
    def normalized(name, *, qty, previous):
        return {
            "game":"One Piece","name":name,"set_name":"OP01","card_number":"001",
            "product_type":"CARD","rarity":"R","language":"English","variant":"",
            "snapshot_quantity":qty,"quantity":qty,"previous_quantity":previous,
        }

    class Connection:
        async def fetchrow(self, sql, *args):
            assert args == (owner,)
            return {"id":batch}
        async def fetch(self, sql, *args):
            assert args == (batch, owner)
            return [
                {"raw_record":{},"normalized_record":normalized("New skipped",qty=4,previous=0),
                 "catalogue_id":None,"status":"SKIPPED"},
                {"raw_record":{},"normalized_record":normalized("Previously owned",qty=3,previous=3),
                 "catalogue_id":uuid4(),"status":"SKIPPED"},
                {"raw_record":{},"normalized_record":normalized("Newly imported",qty=2,previous=0),
                 "catalogue_id":uuid4(),"status":"COMMITTED"},
            ]

    baseline_id, snapshots = asyncio.run(imports._collectr_previous_snapshot(Connection(), owner))
    assert baseline_id == batch
    by_name = {record["normalized_record"]["name"]:record["quantity"] for record in snapshots.values()}
    assert by_name == {"Previously owned":3,"Newly imported":2}
