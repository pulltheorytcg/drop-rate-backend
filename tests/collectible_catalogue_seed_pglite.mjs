// Actual PostgreSQL execution of the reviewed metadata seed; no hosted services.
import {PGlite} from '../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const render = spawnSync(process.env.PYTHON || 'python3', ['backend/scripts/seed_collectible_catalogue.py'], {
  cwd:root,env:{...process.env,PYTHONPATH:'backend'},encoding:'utf8',maxBuffer:2*1024*1024,
});
assert.ifError(render.error);
assert.equal(render.status,0,render.stderr);
const sql = render.stdout;
const manifest = JSON.parse(await readFile(new URL('../backend/data/collectible_catalogue_starter_20261103.json', import.meta.url),'utf8'));
const foundation = await readFile(new URL('../database/migrations/20260927180056_collectible_identity_foundation.sql', import.meta.url),'utf8');
const migration = await readFile(new URL('../database/migrations/20261103145218_seller_sports_figures_intake.sql', import.meta.url),'utf8');
const db = new PGlite(); await db.waitReady;
try {
  await db.exec(`create role tcg_api; create schema tcg;
    create function tcg.current_user_id() returns uuid language sql stable as $$select null::uuid$$;
    create function tcg.current_access_role() returns text language sql stable as $$select null::text$$;
    create table tcg.catalogue_products(id uuid primary key,identity_key text not null unique,
      product_type text not null check(product_type in ('CARD','SEALED','COLLECTION','COMIC','ACCESSORY')),
      game text not null,name text not null,set_name text not null,card_number text,variant text not null,
      rarity text not null,language text,created_at timestamptz not null default now());
    create table tcg.provider_catalogue_mappings(catalogue_id uuid,system_code text,
      provider_entity_type text check(provider_entity_type in ('CARD_PRINTING','SEALED_PRODUCT','COMIC_PRINTING','ACCESSORY')));
    create table tcg.inventory_items(id uuid primary key default gen_random_uuid(),catalogue_id uuid,
      condition text,seal_status text,grading_company text,grade text,certificate_number text);
    create table tcg.media_assets(id int primary key,rights_status text);
    create table tcg.reference_market_prices(id int primary key,price_minor int);
    insert into tcg.inventory_items(id) values('00000000-0000-4000-8000-000000000001');
    insert into tcg.media_assets values(1,'PENDING');
    insert into tcg.reference_market_prices values(1,12345);`);
  for (const table of ['collectible_systems','catalogue_product_profiles','taxonomy_schemas']) {
    const definition = foundation.match(new RegExp(`create table tcg\\.${table} \\([\\s\\S]*?\\n\\);`));
    assert.ok(definition,table); await db.exec(definition[0]);
  }
  await db.exec(migration);
  await db.exec(`create trigger catalogue_product_profiles_validate before insert or update on tcg.catalogue_product_profiles
    for each row execute function tcg.validate_catalogue_product_profile();`);
  const snapshot = async () => (await db.query(`select to_jsonb(p) as product,to_jsonb(pr) as profile
    from tcg.catalogue_products p join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id order by p.id`)).rows;
  const protectedSnapshot = async () => Promise.all(['inventory_items','media_assets','reference_market_prices'].map(
    async table => (await db.query(`select * from tcg.${table} order by id`)).rows));
  const systemsSnapshot = async () => (await db.query('select * from tcg.collectible_systems order by code')).rows;
  const untouched = await protectedSnapshot();
  await db.exec(sql);
  const first = await snapshot();
  assert.equal(first.length,6);
  assert.equal(first.filter(row=>row.profile.system_code==='SPORTS_CARDS'&&row.product.product_type==='CARD').length,4);
  assert.equal(first.filter(row=>row.profile.system_code==='FIGURES'&&row.product.product_type==='FIGURE').length,2);
  assert.ok(first.every(row=>row.profile.identity_status==='VERIFIED'&&row.profile.attributes.identity_source==='OFFICIAL_CATALOGUE'));
  assert.ok(first.every(row=>row.profile.attributes.verification_scope==='OFFICIAL_REFERENCE_METADATA_ONLY'));
  const systems = await systemsSnapshot();
  assert.deepEqual(systems.map(row=>[row.code,row.metadata.reference_catalogue_available,row.metadata.reference_catalogue_coverage,row.metadata.official_reference_count]),
    [['FIGURES',true,'STARTER_METADATA',2],['SPORTS_CARDS',true,'STARTER_METADATA',4]]);
  await db.exec(sql);
  assert.deepEqual(await snapshot(),first,'replay must perform zero product/profile changes');
  assert.deepEqual(await systemsSnapshot(),systems,'replay leaves coverage metadata and timestamps unchanged');
  assert.deepEqual(await protectedSnapshot(),untouched,'stock, artwork rights and market prices are unchanged');

  // A changed official reference must stop for review instead of overwriting it.
  await db.query("update tcg.catalogue_products set variant='Gold parallel' where id=$1",[manifest.entries[0].id]);
  const drift = await snapshot();
  await assert.rejects(()=>db.exec(sql),/Existing official catalogue identity needs review/);
  await db.exec('rollback');
  assert.deepEqual(await snapshot(),drift);
  assert.deepEqual(await systemsSnapshot(),systems,'failed reference validation cannot rewrite coverage');

  // A matching seller identity later in the batch blocks all earlier inserts.
  await db.exec('delete from tcg.catalogue_product_profiles; delete from tcg.catalogue_products;');
  const manual = manifest.entries[5], id='00000000-0000-4000-8000-000000000002';
  const p = manual.catalogue;
  await db.query(`insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
    values($1,'manual:v1:existing-unreviewed',$2,$3,$4,$5,$6,$7,$8,$9)`,
    [id,p.product_type,p.game,p.name.toLowerCase(),p.set_name,p.card_number,p.variant,p.rarity,p.language]);
  await db.query(`insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,identity_status,attributes)
    values($1,'FIGURES','FIGURE','NEEDS_REVIEW',$2::jsonb)`,[id,JSON.stringify({identity_source:'SELLER_ENTERED',figure_details:manual.figure_details,submitted_by_user_id:'owner-a'})]);
  const seller = await snapshot();
  await db.exec("update tcg.collectible_systems set metadata=metadata || '{\"reference_catalogue_available\":false,\"reference_catalogue_coverage\":\"NONE\",\"official_reference_count\":0}'::jsonb");
  const noCoverage = await systemsSnapshot();
  await assert.rejects(()=>db.exec(sql),/Equivalent collectible exists under another identity/);
  await db.exec('rollback');
  assert.deepEqual(await snapshot(),seller,'ambiguous seller reference is neither promoted nor merged; whole batch rolls back');
  assert.deepEqual(await systemsSnapshot(),noCoverage,'failed batch cannot announce coverage');
  assert.deepEqual(await protectedSnapshot(),untouched);
  console.log('Collectible starter PostgreSQL checks passed: six exact records, distinct editions, truthful category counts, unchanged replay, drift refusal, atomic seller-conflict rollback, no stock/price/media writes.');
} finally {await db.close();}
