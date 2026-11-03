// Disposable PostgreSQL execution of the actual migration, triggers and policies.
// No hosted database, production credentials or provider calls are involved.
import {PGlite} from '../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const db = new PGlite(); await db.waitReady;
const source = await readFile(new URL('../database/migrations/20260927180056_collectible_identity_foundation.sql', import.meta.url), 'utf8');
const migration = await readFile(new URL('../database/migrations/20261103145218_seller_sports_figures_intake.sql', import.meta.url), 'utf8');
const actor = '00000000-0000-4000-8000-000000000001', other = '00000000-0000-4000-8000-000000000002';
const ids = Array.from({length: 9}, (_, i) => `00000000-0000-4000-9000-${String(i + 1).padStart(12, '0')}`);
try {
  await db.exec(`create role tcg_api; create role anon; create role authenticated;
    create schema tcg;
    create function tcg.current_user_id() returns uuid language sql stable as
      $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
    create function tcg.current_access_role() returns text language sql stable as
      $$select nullif(current_setting('tcg.access_role',true),'')$$;
    create function tcg.is_platform_admin() returns boolean language sql stable as
      $$select tcg.current_access_role()='PLATFORM_ADMIN'$$;
    create table tcg.catalogue_products(id uuid primary key, identity_key text unique,
      product_type text check(product_type in ('CARD','SEALED','COLLECTION','COMIC','ACCESSORY')));
    create table tcg.provider_catalogue_mappings(catalogue_id uuid,system_code text,
      provider_entity_type text check(provider_entity_type in ('CARD_PRINTING','SEALED_PRODUCT','COMIC_PRINTING','ACCESSORY')));
    create table tcg.inventory_items(id uuid primary key default gen_random_uuid(),catalogue_id uuid references tcg.catalogue_products(id),
      owner_id uuid,condition text,seal_status text check(seal_status in ('SEALED','UNSEALED')),
      grading_company text,grade text,certificate_number text);
    grant usage on schema tcg to tcg_api; grant execute on all functions in schema tcg to tcg_api;`);
  for (const table of ['collectible_systems', 'catalogue_product_profiles', 'taxonomy_schemas']) {
    const definition = source.match(new RegExp(`create table tcg\\.${table} \\([\\s\\S]*?\\n\\);`));
    assert.ok(definition, table); await db.exec(definition[0]);
  }
  // The live predecessor is wider than the historical two-kind foundation.
  // Keep legacy systems present while applying this migration so a narrowing
  // constraint fails here before any production deployment.
  await db.exec(`alter table tcg.collectible_systems drop constraint collectible_systems_system_kind_check;
    alter table tcg.collectible_systems add constraint collectible_systems_system_kind_check
      check(system_kind in ('TCG','COMICS','SPORTS_CARD','FIGURE','CONSTRUCTION_SET'));
    insert into tcg.collectible_systems(code,display_name,franchise,system_kind) values
      ('LEGACY_SPORT','Existing sports system','Existing sport','SPORTS_CARD'),
      ('LEGACY_FIGURE','Existing figure system','Existing figures','FIGURE'),
      ('LEGACY_BUILD','Existing construction system','Existing construction','CONSTRUCTION_SET');`);
  const legacySystems = (await db.query("select * from tcg.collectible_systems where code like 'LEGACY_%' order by code")).rows;
  await db.exec(`insert into tcg.collectible_systems(code,display_name,franchise,system_kind)
    values ('FIXTURE_TCG','Fixture TCG','Fixture','TCG'),('FIXTURE_COMIC','Fixture Comics','Fixture','COMICS');
    alter table tcg.catalogue_product_profiles enable row level security;
    alter table tcg.catalogue_product_profiles force row level security;
    alter table tcg.inventory_items enable row level security;
    alter table tcg.inventory_items force row level security;
    create policy own_copy on tcg.inventory_items to tcg_api using(owner_id=tcg.current_user_id()) with check(owner_id=tcg.current_user_id());
    grant select on tcg.collectible_systems,tcg.taxonomy_schemas to tcg_api;
    grant select,insert on tcg.catalogue_products to tcg_api;
    grant select,insert,update on tcg.catalogue_product_profiles,tcg.inventory_items to tcg_api;`);
  for (const name of ['api_read', 'api_insert', 'api_update']) {
    const policy = source.match(new RegExp(`create policy ${name} on tcg\\.catalogue_product_profiles\\n[\\s\\S]*?;`));
    assert.ok(policy); await db.exec(policy[0]);
  }
  await db.exec(migration);
  assert.deepEqual((await db.query("select * from tcg.collectible_systems where code like 'LEGACY_%' order by code")).rows,legacySystems,
    'migration must preserve every existing system kind and row');
  await db.exec("insert into tcg.collectible_systems(code,display_name,franchise,system_kind) values('NEW_BUILD','New construction system','Construction','CONSTRUCTION_SET')");
  await assert.rejects(() => db.exec("insert into tcg.collectible_systems(code,display_name,franchise,system_kind) values('BAD_KIND','Unsupported kind','Unsupported','SPORTS')"), e => e.code === '23514');
  await db.exec(`create trigger catalogue_product_profiles_validate before insert or update on tcg.catalogue_product_profiles
      for each row execute function tcg.validate_catalogue_product_profile();
    create trigger inventory_physical_validate before insert or update on tcg.inventory_items
      for each row execute function tcg.validate_inventory_condition_state();
    create trigger provider_catalogue_mappings_validate before insert or update on tcg.provider_catalogue_mappings
      for each row execute function tcg.validate_provider_catalogue_mapping();`);
  assert.deepEqual((await db.query("select code,system_kind from tcg.collectible_systems where code in ('SPORTS_CARDS','FIGURES') order by code")).rows,
    [{code:'FIGURES',system_kind:'FIGURE'},{code:'SPORTS_CARDS',system_kind:'SPORTS_CARD'}]);
  const kinds = ['CARD','FIGURE','FIGURE','CARD','SEALED','FIGURE','COMIC','CARD','FIGURE'];
  for (let i = 0; i < ids.length; i++) await db.query('insert into tcg.catalogue_products values($1,$2,$3)', [ids[i], 'manual:v1:fixture-'+i, kinds[i]]);
  await db.exec('set role tcg_api');
  await db.query("select set_config('tcg.user_id',$1,false),set_config('tcg.access_role','OWNER',false)", [actor]);
  const attrs = (kind, user=actor) => JSON.stringify({identity_source:'SELLER_ENTERED',submitted_by_user_id:user,
    [kind === 'FIGURE' ? 'figure_details' : 'sports_card']:{system_code:kind === 'FIGURE' ? 'FIGURES' : 'SPORTS_CARDS'}});
  const profile = (id, system, kind, status='NEEDS_REVIEW', attributes=attrs(kind)) => db.query(`insert into tcg.catalogue_product_profiles
    (catalogue_id,system_code,collectible_type,identity_status,attributes) values($1,$2,$3,$4,$5::jsonb)`, [id,system,kind,status,attributes]);
  await profile(ids[0],'SPORTS_CARDS','CARD'); await profile(ids[1],'FIGURES','FIGURE');
  await assert.rejects(() => profile(ids[2],'FIGURES','FIGURE','VERIFIED'), e => e.code === '42501');
  await assert.rejects(() => profile(ids[2],'FIGURES','FIGURE','NEEDS_REVIEW',attrs('FIGURE',other)), e => e.code === '42501');
  await assert.rejects(() => profile(ids[2],'FIGURES','CARD'), e => e.code === '23514');
  await assert.rejects(() => profile(ids[3],'FIGURES','CARD'), e => e.code === '23514');
  await assert.rejects(() => profile(ids[4],'SPORTS_CARDS','SEALED'), e => e.code === '23514');
  await assert.rejects(() => profile(ids[5],'FIXTURE_TCG','FIGURE'), e => e.code === '23514');
  assert.equal((await db.query("update tcg.catalogue_product_profiles set identity_status='VERIFIED' returning catalogue_id")).rows.length,0);
  const copy = (cat, condition, seal=null, grading=null, owner=actor) => db.query(`insert into tcg.inventory_items
    (catalogue_id,owner_id,condition,seal_status,grading_company,grade) values($1,$2,$3,$4,$5,$6) returning id`, [cat,owner,condition,seal,grading,grading?'10':null]);
  const figureCopy = (await copy(ids[1],'Like New','UNSEALED')).rows[0].id;
  await copy(ids[1],null); await copy(ids[1],'New','SEALED'); await copy(ids[0],'Near Mint');
  await assert.rejects(() => copy(ids[1],'Lightly Played'), e => e.code === '23514');
  await assert.rejects(() => copy(ids[1],null,null,'PSA'), e => e.code === '23514');
  await assert.rejects(() => copy(ids[0],'New'), e => e.code === '23514');
  await assert.rejects(() => copy(ids[0],'Near Mint','SEALED'), e => e.code === '23514');
  await assert.rejects(() => copy(ids[1],'New',null,null,other), e => e.code === '42501');
  await db.query("select set_config('tcg.user_id',$1,false)", [other]);
  assert.equal((await db.query('select id from tcg.inventory_items where id=$1',[figureCopy])).rows.length,0);
  assert.equal((await db.query("update tcg.inventory_items set condition='Damaged' where id=$1 returning id",[figureCopy])).rows.length,0);
  await db.exec('reset role');
  await db.query("insert into tcg.provider_catalogue_mappings values($1,'FIGURES','FIGURE_PRODUCT')",[ids[1]]);
  await assert.rejects(() => db.query("insert into tcg.provider_catalogue_mappings values($1,'FIGURES','CARD_PRINTING')",[ids[1]]), e => e.code === '23514');
  await db.exec("insert into tcg.taxonomy_schemas(system_code,scope_kind,dimension_code,display_name,cardinality) values('FIGURES','FIGURE','EDITION','Edition','SINGLE')");
  for (const role of ['anon','authenticated']) {
    await db.exec('set role '+role);
    await assert.rejects(() => db.query('select * from tcg.inventory_items'), e => e.code === '42501');
    await assert.rejects(() => db.query('select * from tcg.catalogue_product_profiles'), e => e.code === '42501');
    await db.exec('reset role');
  }
  console.log('Sports/Figures PostgreSQL checks passed: exact category guards, explicit seller attribution, no self-verification, physical state, owner isolation, taxonomy and provider mapping type.');
} finally { await db.close(); }
