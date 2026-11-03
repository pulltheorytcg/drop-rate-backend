"""Disposable PostgreSQL 17, authentic RLS and typed quote-restore proof."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app import reference_quote_source_backup as backup
from app.object_storage import ObjectStorageError


ADMIN = UUID("00000000-0000-0000-0000-000000000001")
OTHER = UUID("00000000-0000-0000-0000-000000000002")


class PrivateR2Fixture:
    def __init__(self, *, corrupt=False):
        self.objects = {}
        self.corrupt = corrupt

    def put_verified_file(self, path: Path, *, category, content_type):
        assert category == "exports"
        assert content_type in {"application/gzip", "application/json"}
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        key = f"drop-rate/exports/{digest}{''.join(path.suffixes)}"
        self.objects[key] = payload
        return {"key": key, "size_bytes": len(payload), "sha256": digest, "verified": True}

    def download_verified_file(self, key, path, *, expected_sha256, expected_size):
        payload = self.objects[key]
        if self.corrupt:
            payload += b"corrupted"
        if (len(payload) != expected_size or
                hashlib.sha256(payload).hexdigest() != expected_sha256):
            raise ObjectStorageError("R2 fixture readback failed")
        path.write_bytes(payload)


SCHEMA_SQL = """
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

create table tcg.reference_market_prices (
 provider text not null, system_code text not null, language text not null,
 provider_id text not null, quotes jsonb not null check(jsonb_typeof(quotes)='array'),
 market_value_minor bigint, market_value_high_minor bigint,
 pricing_updated_at timestamptz, checked_at timestamptz not null,
 expires_at timestamptz not null check(expires_at>checked_at),
 refresh_revision integer not null default 0,
 primary key(provider,system_code,language,provider_id),
 check ((market_value_minor is null and market_value_high_minor is null)
       or (market_value_minor>0 and market_value_high_minor>=market_value_minor
           and jsonb_array_length(quotes)>0 and pricing_updated_at is not null))
);
create table tcg.reference_catalogue_prices (
 provider text not null, system_code text not null, language text not null,
 provider_id text not null, quotes jsonb not null check(jsonb_typeof(quotes)='array'),
 market_value_minor bigint, market_value_high_minor bigint,
 pricing_updated_at timestamptz, checked_at timestamptz not null,
 expires_at timestamptz not null check(expires_at>checked_at),
 primary key(provider,system_code,language,provider_id),
 check ((market_value_minor is null and market_value_high_minor is null)
       or (market_value_minor>0 and market_value_high_minor>=market_value_minor
           and jsonb_array_length(quotes)>0 and pricing_updated_at is not null))
);
alter table tcg.reference_market_prices enable row level security;
alter table tcg.reference_market_prices force row level security;
alter table tcg.reference_catalogue_prices enable row level security;
alter table tcg.reference_catalogue_prices force row level security;
create policy market_reference_read on tcg.reference_market_prices for select to tcg_api
 using((select tcg.current_user_id()) is not null);
create policy catalogue_reference_read on tcg.reference_catalogue_prices for select to tcg_api
 using((select tcg.current_user_id()) is not null);
grant usage on schema tcg to tcg_api;
grant select on tcg.owners,tcg.owner_memberships,
 tcg.reference_market_prices,tcg.reference_catalogue_prices to tcg_api;
"""


async def main():
    dsn = os.environ["REFERENCE_QUOTES_TEST_DSN"]
    parsed = urlsplit(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1"}
    assert parsed.path == "/reference_quotes_test"
    admin = await asyncpg.connect(dsn)
    pool = None
    try:
        assert not await admin.fetchval(
            "select exists(select 1 from pg_namespace where nspname='tcg')"
        ), "Only a fresh disposable database may run this test"
        await admin.execute(SCHEMA_SQL)
        checked = datetime(2026, 11, 2, 9, 1, tzinfo=timezone.utc)
        for table, count in (("reference_market_prices", 405), ("reference_catalogue_prices", 203)):
            for i in range(count):
                priced = i % 3 != 0
                quotes = ([{"source": "FIXTURE", "amount": 9007199254740993,
                            "characters": ["猫", {"id": i}]}] if priced else [])
                await admin.execute(f"""insert into tcg.{table}
                    (provider,system_code,language,provider_id,quotes,market_value_minor,
                     market_value_high_minor,pricing_updated_at,checked_at,expires_at
                     {',refresh_revision' if table == 'reference_market_prices' else ''})
                    values('EXACT','POKEMON_TCG','Japanese',$1,$2::jsonb,$3,$4,$5,$6,$7
                           {',$8' if table == 'reference_market_prices' else ''})""",
                    f"card-{i:05d}", json.dumps(quotes), 101 + i if priced else None,
                    151 + i if priced else None, checked if priced else None,
                    checked, checked + timedelta(days=1),
                    *([i % 7] if table == "reference_market_prices" else []),
                )
        before = {}
        for table in backup.TABLE_FIELDS:
            before[table] = await admin.fetchval(f"""select md5(string_agg(
                row_to_json(p)::text,'|' order by provider,system_code,language,provider_id))
                from tcg.{table} p""")

        async def use_restricted_role(connection):
            await connection.execute("set role tcg_api")

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3,
                                         setup=use_restricted_role)
        local = await backup.backup_reference_quote_sources(pool, ADMIN)
        assert local["status"] == "LOCAL_RESTORE_VERIFIED"
        assert local["total_rows"] == 608 and not local["uploaded"]
        assert local["bytes_reclaimed"] == local["rows_reclaimed"] == 0

        store = PrivateR2Fixture()
        uploaded = await backup.backup_reference_quote_sources(pool, ADMIN,
                                                                upload=True, store=store)
        assert uploaded["status"] == "R2_RESTORE_VERIFIED"
        assert uploaded["total_rows"] == 608
        assert len(store.objects) == 4
        assert uploaded["live_prices_untouched"] and not uploaded["physical_offload_authorized"]
        for table in backup.TABLE_FIELDS:
            assert await admin.fetchval(f"""select md5(string_agg(
                row_to_json(p)::text,'|' order by provider,system_code,language,provider_id))
                from tcg.{table} p""") == before[table]

        try:
            await backup.backup_reference_quote_sources(pool, OTHER)
        except HTTPException as error:
            assert error.status_code == 403
        else:
            raise AssertionError("Non-administrator was allowed to export price sources")

        try:
            await backup.backup_reference_quote_sources(pool, ADMIN,
                upload=True, store=PrivateR2Fixture(corrupt=True))
        except ObjectStorageError:
            pass
        else:
            raise AssertionError("Corrupted R2 download was accepted")

        await admin.execute("alter table tcg.reference_catalogue_prices add column unreviewed text")
        try:
            await backup.backup_reference_quote_sources(pool, ADMIN)
        except ObjectStorageError:
            pass
        else:
            raise AssertionError("Schema drift silently omitted source columns")

        print("R2 quote shadow: 608 exact priced/unpriced rows, private readback, "
              "restricted admin actor, lossless temp-table restore; no production writes")
    finally:
        if pool:
            await pool.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
