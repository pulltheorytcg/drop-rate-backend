"""Disposable PostgreSQL contract for exact Pokémon image repair."""
import asyncio
import hashlib
import json
import os
from urllib.parse import urlsplit

import asyncpg

from app.pokemon_artwork_repair import READ_SQL, WRITE_SQL, SETS, candidate, M1S_REVIEW_PATH, M1S_REVIEW_SHA256
from app.reference_library import save_reference_set


async def main():
    dsn = os.environ["POKEMON_ARTWORK_TEST_DSN"]
    address = urlsplit(dsn)
    assert address.hostname in {"localhost", "127.0.0.1"} and address.path == "/pokemon_artwork_test"
    db = await asyncpg.connect(dsn)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute("""create schema tcg;
            create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,
              release_date date,declared_card_count int,source_url text,refreshed_at timestamptz,
              primary key(provider,system_code,language,set_id));
            create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,
              name text,card_number text,number_key text,finish text,rarity text,image_url text,source_url text,
              evidence jsonb default '{}'::jsonb,refreshed_at timestamptz,
              primary key(provider,system_code,language,provider_id));
            create table tcg.inventory_items(id int primary key,owner_id text,store_price_minor int);
            insert into tcg.inventory_items values(1,'founder-a',900),(2,'founder-b',1500);
            create table tcg.reference_market_prices(id int primary key,market_value_minor int);
            insert into tcg.reference_market_prices values(1,1000);
        """)
        record = {"provider": "TCGdex", "system_code": "POKEMON_TCG", "language": "Japanese",
                  "set_id": "SM12a", "name": "Fixture set", "source_url": "source"}
        def card(local, **change):
            return {"provider_id": "SM12a-" + local, "name": "Reference " + local,
                    "card_number": local + "/173",
                    "source_url": "https://api.tcgdex.net/v2/ja/cards/SM12a-" + local,
                    "evidence": {"provider_local_id": local, "original": True}, **change}
        cards = [card("001"), card("002"), card("003"), card("004"),
                 card("005", image_url="https://existing.example/keep.webp")]
        await save_reference_set(db, record, cards)
        await save_reference_set(db, dict(record, language="English"), cards)
        snapshot = await db.fetch(READ_SQL, list(SETS["English"]), list(SETS["Japanese"]), 5000, None, None, None)
        assert len(snapshot) == 4
        following = await db.fetch(READ_SQL, list(SETS["English"]), list(SETS["Japanese"]), 5000,
                                   "Japanese", "SM12a", "SM12a-002")
        assert [entry["provider_id"] for entry in following] == ["SM12a-003", "SM12a-004"]
        payload = []
        for row in snapshot:
            item = candidate(dict(row))
            assert item
            item["image_reference"] = {"verification": "fixture", "content_sha256": "a" * 64}
            payload.append(item)
        before = await db.fetchval("""select md5(string_agg(row_to_json(x)::text,'' order by id))
                                     from tcg.inventory_items x""")
        price_before = await db.fetchval("select row_to_json(x)::text from tcg.reference_market_prices x")
        # Simulated concurrent edits to source identity, number and local ID must refuse writes.
        await db.execute("update tcg.reference_cards set name='Changed' where language='Japanese' and provider_id='SM12a-002'")
        await db.execute("update tcg.reference_cards set card_number='999/173' where language='Japanese' and provider_id='SM12a-003'")
        await db.execute("""update tcg.reference_cards set evidence='{"provider_local_id":"999"}'
                            where language='Japanese' and provider_id='SM12a-004'""")
        changed = await db.fetch(WRITE_SQL, json.dumps(payload))
        assert len(changed) == 1 and changed[0]["provider_id"] == "SM12a-001"
        assert not await db.fetch(WRITE_SQL, json.dumps(payload)), "Replay overwrote artwork"
        value = await db.fetchrow("select * from tcg.reference_cards where language='Japanese' and provider_id='SM12a-001'")
        assert value["image_url"] == "https://assets.tcgdex.net/ja/SM/SM12a/001/high.webp"
        assert json.loads(value["evidence"])["original"] is True
        assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese' and provider_id='SM12a-005'") == "https://existing.example/keep.webp"
        assert await db.fetchval("select count(*) from tcg.reference_cards where language='English' and image_url is null") == 4
        assert before == await db.fetchval("select md5(string_agg(row_to_json(x)::text,'' order by id)) from tcg.inventory_items x")
        assert price_before == await db.fetchval("select row_to_json(x)::text from tcg.reference_market_prices x")
        # Rollback must restore a blank URL and remove the attached repair evidence.
        await save_reference_set(db, record, [card("006")])
        sixth = await db.fetchrow("select * from tcg.reference_cards where language='Japanese' and provider_id='SM12a-006'")
        six = candidate(dict(sixth))
        six["image_reference"] = {"verification": "rollback"}
        tr = db.transaction()
        await tr.start()
        assert len(await db.fetch(WRITE_SQL, json.dumps([six]))) == 1
        await tr.rollback()
        assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese' and provider_id='SM12a-006'") is None
        # A future release cannot be updated even if eligibility changes after the read.
        await db.execute("update tcg.reference_sets set release_date=current_date+1 where language='Japanese'")
        assert not await db.fetch(WRITE_SQL, json.dumps([six]))
        await db.execute("update tcg.reference_sets set release_date=null where language='Japanese'")
        # Existing sparse-sync rules preserve this evidence for the unchanged exact printing.
        for blank in (None, "", " \t\n"):
            await save_reference_set(db, record, [card("001", image_url=blank)])
            assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese' and provider_id='SM12a-001'") == "https://assets.tcgdex.net/ja/SM/SM12a/001/high.webp"
            assert await db.fetchval("select evidence->'image_reference'->>'verification' from tcg.reference_cards where language='Japanese' and provider_id='SM12a-001'") == "fixture"
        await save_reference_set(db, record, [card("001", name="Reassigned identity")])
        assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese' and provider_id='SM12a-001'") is None
        # Same-name identity changes must also discard a previous image.
        for changed_fields in ({"card_number": "001/999"},
                               {"source_url": "https://api.tcgdex.net/v2/ja/cards/other"},
                               {"evidence": {"provider_local_id": "999"}}):
            await save_reference_set(db, record, [card("001")])
            original = await db.fetchrow("select * from tcg.reference_cards where language='Japanese' and provider_id='SM12a-001'")
            image = candidate(dict(original))
            image["image_reference"] = {"verification": "identity"}
            assert len(await db.fetch(WRITE_SQL, json.dumps([image]))) == 1
            await save_reference_set(db, record, [card("001", image_url=" \t\n", **changed_fields)])
            changed_identity = await db.fetchrow("select * from tcg.reference_cards where language='Japanese' and provider_id='SM12a-001'")
            assert changed_identity["image_url"] is None
            assert "image_reference" not in json.loads(changed_identity["evidence"])

        # Individually reviewed M1S corrections must survive a provider later
        # returning the known misnumbered nominal path for unchanged identity.
        reviewed_record = dict(record, set_id="M1S")
        override_sha = hashlib.sha256(M1S_REVIEW_PATH.with_name("pokemon_artwork_m1s_overrides_20261027.json").read_bytes()).hexdigest()
        for local, name, asset, verification, manifest_sha in (
            ("001", "モンジャラ", "001", "TCGDEX_REVIEWED_IMAGE_BYTES_V1", M1S_REVIEW_SHA256),
            ("057", "あやしい時計", "078", "TCGDEX_REVIEWED_ASSET_OVERRIDE_V1", override_sha),
        ):
            reviewed_url = f"https://assets.tcgdex.net/ja/M/M1S/{asset}/high.webp"
            nominal_url = f"https://assets.tcgdex.net/ja/M/M1S/{local}/low.webp"
            reviewed_card = {"provider_id": f"M1S-{local}", "name": name, "card_number": f"{local}/63",
                             "source_url": f"https://api.tcgdex.net/v2/ja/cards/M1S-{local}",
                             "evidence": {"provider_local_id": local}}
            proof = {"verification": verification, "image_url": reviewed_url,
                     "source_url": reviewed_card["source_url"], "scope": "REFERENCE_ONLY_NOT_APPROVED_MEDIA",
                     "content_sha256": "a" * 64, "review_manifest_sha256": manifest_sha}
            reviewed_proof = dict(proof)
            await save_reference_set(db, reviewed_record, [dict(reviewed_card, image_url=reviewed_url,
                evidence={"provider_local_id": local, "image_reference": reviewed_proof})])
            for incoming in (None, " \t\n", nominal_url):
                await save_reference_set(db, reviewed_record, [dict(reviewed_card, image_url=incoming)])
                stored = await db.fetchrow("select image_url,evidence from tcg.reference_cards where language='Japanese' and provider_id=$1", f"M1S-{local}")
                assert stored["image_url"] == reviewed_url
                assert json.loads(stored["evidence"])["image_reference"] == reviewed_proof
            await save_reference_set(db, reviewed_record, [dict(reviewed_card, name="Different identity", image_url=nominal_url)])
            stored = await db.fetchrow("select image_url,evidence from tcg.reference_cards where language='Japanese' and provider_id=$1", f"M1S-{local}")
            assert stored["image_url"] == nominal_url and "image_reference" not in json.loads(stored["evidence"])
        # Incomplete proof or ordinary provider art must not acquire this pin.
        for mutation in ({"verification": "fixture"}, {"image_url": nominal_url},
                         {"content_sha256": "invalid"}, {"review_manifest_sha256": "invalid"},
                         {"review_manifest_sha256": "b" * 64},
                         {"review_manifest_sha256": M1S_REVIEW_SHA256},
                         {"source_url": "https://api.tcgdex.net/v2/ja/cards/M1S-999"},
                         {"scope": "UNREVIEWED"}):
            await save_reference_set(db, reviewed_record, [dict(reviewed_card, image_url=reviewed_url,
                evidence={"provider_local_id": "057", "image_reference": {**proof, **mutation}})])
            await save_reference_set(db, reviewed_record, [dict(reviewed_card, image_url=nominal_url)])
            assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese' and provider_id='M1S-057'") == nominal_url
    finally:
        await db.close()
    print("PASS: exact image repair, identity races, replay, rollback, release guard, sparse-sync preservation, unchanged inventory/current prices")


asyncio.run(main())
