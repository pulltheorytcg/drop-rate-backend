"""Disposable PostgreSQL 17 verification of the lossless R2 source backup."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.object_storage import ObjectStorageError
from app import reference_source_backup as backup


ADMIN = UUID("00000000-0000-0000-0000-000000000001")
OTHER = UUID("00000000-0000-0000-0000-000000000002")


class PrivateR2Fixture:
    def __init__(self, corrupt_download=False):
        self.objects = {}
        self.corrupt_download = corrupt_download

    def put_verified_file(self, path: Path, *, category: str, content_type: str):
        assert category == "exports"
        assert content_type in {"application/gzip", "application/json"}
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        key = f"drop-rate/exports/{digest}{''.join(path.suffixes)}"
        self.objects[key] = raw
        return {"key": key, "size_bytes": len(raw), "sha256": digest, "verified": True}

    def download_verified_file(self, key, path, *, expected_sha256, expected_size):
        raw = self.objects[key]
        if self.corrupt_download:
            raw = b"corrupt" + raw
        if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ObjectStorageError("R2 fixture readback failed")
        path.write_bytes(raw)


async def main():
    dsn = os.environ["REFERENCE_SOURCE_TEST_DSN"]
    parsed = urlsplit(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1"}
    assert parsed.path == "/reference_source_test"
    admin = await asyncpg.connect(dsn)
    pool = None
    try:
        assert not await admin.fetchval(
            "select exists(select 1 from pg_namespace where nspname='tcg')"
        ), "Fresh disposable database only"
        await admin.execute("""
            create schema tcg;
            create role tcg_api nologin nosuperuser nobypassrls;
            create function tcg.current_user_id() returns uuid language sql stable as
                $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
            create function tcg.is_platform_admin() returns boolean language sql stable as
                $$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
            create table tcg.owners(id uuid primary key,display_name text,
                owner_type text,active boolean,founder_slot integer);
            create table tcg.owner_memberships(id uuid primary key,user_id uuid,
                owner_id uuid,role text,active boolean,created_at timestamptz default now());
            insert into tcg.owners values
                ('10000000-0000-0000-0000-000000000001','Founder','FOUNDER',true,1),
                ('10000000-0000-0000-0000-000000000002','Other','CONSIGNOR',true,null);
            insert into tcg.owner_memberships(id,user_id,owner_id,role,active) values
                ('20000000-0000-0000-0000-000000000001',
                 '00000000-0000-0000-0000-000000000001',
                 '10000000-0000-0000-0000-000000000001','PLATFORM_ADMIN',true),
                ('20000000-0000-0000-0000-000000000002',
                 '00000000-0000-0000-0000-000000000002',
                 '10000000-0000-0000-0000-000000000002','OWNER',true);
            create table tcg.reference_cards (
                provider text not null,system_code text not null,language text not null,
                provider_id text not null,set_id text,name text,card_number text,
                number_key text,finish text,rarity text,image_url text,source_url text,
                evidence jsonb,refreshed_at timestamptz,
                primary key(provider,system_code,language,provider_id)
            );
            alter table tcg.reference_cards enable row level security;
            alter table tcg.reference_cards force row level security;
            create policy reference_read on tcg.reference_cards for select to tcg_api
                using((select tcg.current_user_id()) is not null);
            grant usage on schema tcg to tcg_api;
            grant select on tcg.owners,tcg.owner_memberships,tcg.reference_cards to tcg_api;
        """)
        for i in range(403):
            await admin.execute("""insert into tcg.reference_cards values(
                'EXACT','POKEMON','Japanese',$1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)""",
                f"{i:05d}", f"set-{i//10}", f"Pokémon card {i}",str(i),str(i),
                None if i % 2 else "Holo", "Common", f"https://example.test/{i}.png",
                None if i % 3 else f"https://source.test/{i}",
                json.dumps({"source": "fixture", "rare": i % 7, "nested": ["猫", {"v": i}]}),
                datetime(2026, 10, 29, 12, 13, 14, i % 1_000_000, tzinfo=timezone.utc),
            )
        before = await admin.fetchval("""select md5(string_agg(
            row_to_json(c)::text,'|' order by provider,system_code,language,provider_id))
            from tcg.reference_cards c""")

        async def setup(conn):
            await conn.execute("set role tcg_api")

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3, setup=setup)
        local = await backup.backup_reference_cards(pool, ADMIN)
        assert local["status"] == "LOCAL_RESTORE_VERIFIED"
        assert local["row_count"] == 403
        assert local["bytes_reclaimed"] == 0 and not local["uploaded"]

        fixture = PrivateR2Fixture()
        uploaded = await backup.backup_reference_cards(pool, ADMIN, upload=True, store=fixture)
        assert uploaded["status"] == "R2_RESTORE_VERIFIED"
        assert uploaded["row_count"] == 403
        assert uploaded["restoration_verified"]
        assert len(fixture.objects) == 2  # Private archive and private manifest.
        assert uploaded["rows_reclaimed"] == 0
        assert await admin.fetchval("select count(*) from tcg.reference_cards") == 403
        assert await admin.fetchval("""select md5(string_agg(
            row_to_json(c)::text,'|' order by provider,system_code,language,provider_id))
            from tcg.reference_cards c""") == before

        for actor in (OTHER,):
            try:
                await backup.backup_reference_cards(pool, actor)
            except HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("Non-admin exported source cards")
        try:
            await backup.backup_reference_cards(
                pool, ADMIN, upload=True, store=PrivateR2Fixture(corrupt_download=True)
            )
        except ObjectStorageError:
            pass
        else:
            raise AssertionError("Corrupted R2 readback was accepted")

        await admin.execute("alter table tcg.reference_cards add column unreviewed text")
        try:
            await backup.backup_reference_cards(pool, ADMIN)
        except ObjectStorageError:
            pass
        else:
            raise AssertionError("Source schema drift silently dropped columns")

        assert await admin.fetchval("select count(*) from tcg.reference_cards") == 403
        print("Reference source R2: 403 complete rows, temporary typed restore, immutable private readback, no source writes passed")
    finally:
        if pool:
            await pool.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
