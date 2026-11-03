// Actual new migration/policies on disposable in-memory PostgreSQL (PGlite).
// No network, production DSN, credentials, schema writes or data imports occur.
// Existing pinned test-only PGlite runtime; no application dependency added.
import { PGlite } from '../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const db = new PGlite();
await db.waitReady;
const admin = '00000000-0000-4000-8000-000000000001';
const owner = '00000000-0000-4000-8000-000000000002';
const other = '00000000-0000-4000-8000-000000000003';
const outsider = '00000000-0000-4000-8000-000000000004';
const productOne = '00000000-0000-4000-8000-000000000101';
const productTwo = '00000000-0000-4000-8000-000000000102';
const provider = 'fixture_provider', system = 'DISNEY_LORCANA', language = 'English';
const sha = value => createHash('sha256').update(value).digest('hex');
const key = id => 'x:' + sha(JSON.stringify([provider, system, language, id]));
const one = key('card/one'), two = key('card/two');
const first = 'a'.repeat(64), second = 'b'.repeat(64);
const migration = new URL('../database/migrations/20261103222018_r2_first_catalogue_registry.sql', import.meta.url);
const asUser = id => db.query("select set_config('tcg.user_id',$1,false)", [id]);
const publications = () => db.query('select * from tcg_private.r2_first_catalogue_publications order by provider');
const events = () => db.query('select * from tcg_private.r2_first_catalogue_events order by generation');
const publish = (generation=1, actor=admin, overrides={}) => db.query(`
  insert into tcg_private.r2_first_catalogue_publications
    (provider,system_code,language,manifest_sha256,source_revision,permission_ref,source_url,
     record_count,released_record_count,raw_bytes,set_count,generation,published_by)
  values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`, [
    overrides.provider || provider, system, language, first, 'fixture-v1', 'docs/test-review.md',
    'https://provider.example.com/catalogue', 2, 1, 1000, 1, generation, actor]);
const link = (referenceKey, productId, providerId, digest, actor) => db.query(`
  insert into tcg_private.r2_first_catalogue_links
    (reference_key,catalogue_id,provider,system_code,language,provider_id,source_manifest_sha256,created_by)
  values($1,$2,$3,$4,$5,$6,$7,$8)`, [referenceKey, productId, provider, system, language, providerId, digest, actor]);
const bookmark = (user, referenceKey) => db.query(`
  insert into tcg.catalogue_saved_references(user_id,reference_key)
  values($1,$2) on conflict(user_id,reference_key) do nothing`, [user, referenceKey]);
const saved = () => db.query('select user_id,reference_key from tcg.catalogue_saved_references order by reference_key');
const rejected = (action, code) => assert.rejects(action, error => error.code === code);

try {
  // Minimal fixtures for existing authentication/canonical-product contracts.
  // Only the NEW migration below is under test; its policy SQL is unmodified.
  await db.exec(`
    create role anon; create role authenticated; create role service_role; create role tcg_api;
    create schema auth; create schema tcg; create schema tcg_private;
    create table auth.users(id uuid primary key);
    create table tcg.owner_memberships(user_id uuid primary key, role text not null, active boolean not null);
    create table tcg.collectible_systems(code text primary key);
    create table tcg.catalogue_products(id uuid primary key, identity_key text not null unique);
    create function tcg.current_user_id() returns uuid language sql stable as
      $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
    create function tcg.current_access_role() returns text language sql stable security definer
      set search_path=pg_catalog as
      $$select role from tcg.owner_memberships where user_id=tcg.current_user_id() and active$$;
    create function tcg.is_platform_admin() returns boolean language sql stable security definer
      set search_path=pg_catalog as $$select coalesce(tcg.current_access_role()='PLATFORM_ADMIN',false)$$;
    grant usage on schema tcg,tcg_private to tcg_api;
    grant select on tcg.catalogue_products,tcg.collectible_systems to tcg_api;
    grant execute on function tcg.current_user_id(),tcg.current_access_role(),tcg.is_platform_admin() to tcg_api;
  `);
  await db.query('insert into auth.users values($1),($2),($3),($4)', [admin,owner,other,outsider]);
  await db.query("insert into tcg.owner_memberships values($1,'PLATFORM_ADMIN',true),($2,'OWNER',true),($3,'OWNER',true)",
    [admin,owner,other]);
  await db.query('insert into tcg.collectible_systems values($1)', [system]);
  await db.query('insert into tcg.catalogue_products values($1,$2),($3,$4)',
    [productOne, 'r2:v1:' + one.slice(2), productTwo, 'r2:v1:' + two.slice(2)]);
  await db.exec(await readFile(new URL('../database/migrations/20261103143718_catalogue_saved_references.sql', import.meta.url), 'utf8'));
  await db.exec(await readFile(migration, 'utf8'));
  // JS/Python compact JSON arrays and PostgreSQL array_to_json must preserve
  // the exact Unicode identity tuple, delimiters, quotes and backslashes.
  for (const providerId of ['card/one', 'a:b/c', 'caf\u00e9/\u5fc3', 'cafe\u0301',
      'quoted "printing"', 'back\\slash', '\ud83c\udccf/foil', 'a\u2028b']) {
    const tuple = [provider,system,language,providerId];
    const actual = (await db.query(`select encode(sha256(convert_to(
      array_to_json($1::text[])::text,'UTF8')),'hex') digest`,[tuple])).rows[0].digest;
    assert.equal(actual,sha(JSON.stringify(tuple)));
  }
  assert.notEqual(key('caf\u00e9'),key('cafe\u0301'),'normalization must not silently merge provider IDs');
  const guarded = (await db.query(`select relname,relrowsecurity,relforcerowsecurity from pg_class
    where oid in ('tcg_private.r2_first_catalogue_publications'::regclass,
      'tcg_private.r2_first_catalogue_events'::regclass,'tcg_private.r2_first_catalogue_links'::regclass)`)).rows;
  assert.equal(guarded.length, 3);
  assert(guarded.every(row => row.relrowsecurity && row.relforcerowsecurity));
  const security = (await db.query(`select prosecdef from pg_proc
    where oid='tcg_private.r2_first_publication_audit()'::regprocedure`)).rows[0];
  assert.equal(security.prosecdef, false, 'audit must not be a privilege bypass');
  await db.exec('set role tcg_api');
  await asUser(admin);
  await rejected(() => publish(2), '23514');
  assert.equal((await publications()).rows.length, 0);
  assert.equal((await events()).rows.length, 0);
  await rejected(() => publish(1, owner), '42501');
  assert.equal((await publications()).rows.length, 0);
  await publish();
  assert.equal((await publications()).rows[0].manifest_sha256, first);
  const initial = (await events()).rows;
  assert.equal(initial.length, 1);
  assert.equal(initial[0].old_manifest_sha256, null);
  assert.equal(initial[0].new_manifest_sha256, first);
  assert.equal(initial[0].actor_user_id, admin);

  await asUser(owner);
  assert.equal((await publications()).rows.length, 1);
  assert.equal((await events()).rows.length, 0);
  await rejected(() => publish(1, owner, {provider:'other_provider'}), '42501');
  const ownerUpdate = await db.query('update tcg_private.r2_first_catalogue_publications set generation=generation+1 returning provider');
  assert.equal(ownerUpdate.rows.length, 0);
  // SELECT FOR SHARE also applies UPDATE RLS. Seller intake must use the
  // publisher-coordinated advisory lock, NOT weaken publication UPDATE RLS.
  const ownerLockedRead = await db.query('select provider from tcg_private.r2_first_catalogue_publications for share');
  assert.equal(ownerLockedRead.rows.length, 0);
  console.log('Verified owner SELECT returns 1 but SELECT FOR SHARE returns 0 under admin-only publication UPDATE RLS.');
  await rejected(() => link(one, productOne, 'card/one', first, other), '42501');
  await rejected(() => link(one, productOne, 'card/one', second, owner), '42501');
  await rejected(() => link(two, productOne, 'card/two', first, owner), '42501');
  await rejected(() => link(one, productOne, 'not-the-same-provider-id', first, owner), '23514');
  await link(one, productOne, 'card/one', first, owner);
  await rejected(() => link(one, productOne, 'card/one', first, owner), '23505');
  await rejected(() => db.query('update tcg_private.r2_first_catalogue_links set created_by=$1',[other]), '42501');
  await rejected(() => db.query('delete from tcg_private.r2_first_catalogue_links'), '42501');

  await bookmark(owner, one);
  await bookmark(owner, one);
  assert.deepEqual((await saved()).rows, [{user_id:owner,reference_key:one}]);
  await asUser(other);
  assert.equal((await saved()).rows.length, 0);
  await rejected(() => bookmark(owner, two), '42501');
  await bookmark(other, two);
  assert.deepEqual((await saved()).rows, [{user_id:other,reference_key:two}]);
  await rejected(() => bookmark(other, 'x:' + 'A'.repeat(64)), '23514');
  await rejected(() => bookmark(other, 'x:invalid'), '23514');
  for (const legacy of ['r:'+'a'.repeat(32), 's:'+'b'.repeat(32), 'c:'+productOne]) {
    await bookmark(other, legacy);
  }
  await asUser(owner);
  await db.query('delete from tcg.catalogue_saved_references where user_id=$1',[other]);
  assert.equal((await saved()).rows.length, 1);
  await rejected(() => db.query('update tcg.catalogue_saved_references set user_id=$1',[other]), '42501');

  await asUser(admin);
  await rejected(() => db.query('update tcg_private.r2_first_catalogue_publications set generation=generation'), '23514');
  await rejected(() => db.query('update tcg_private.r2_first_catalogue_publications set generation=generation+2'), '23514');
  await rejected(() => db.query("update tcg_private.r2_first_catalogue_publications set provider='other_provider',generation=generation+1"), '23514');
  assert.equal((await publications()).rows[0].generation, 1);
  assert.equal((await events()).rows.length, 1);
  await db.query('update tcg_private.r2_first_catalogue_publications set active=false,generation=2,published_by=$1',[admin]);
  assert.equal((await events()).rows.length, 2);
  await asUser(owner);
  await rejected(() => link(two, productTwo, 'card/two', first, owner), '42501');
  assert.equal((await db.query('select * from tcg_private.r2_first_catalogue_links')).rows.length, 1);
  await asUser(admin);
  await db.query(`update tcg_private.r2_first_catalogue_publications
    set manifest_sha256=$1,source_revision='fixture-v2',active=true,generation=3,published_by=$2`,[second,admin]);
  await asUser(owner);
  await rejected(() => link(two, productTwo, 'card/two', first, owner), '42501');
  await link(two, productTwo, 'card/two', second, owner);
  const immutable = (await db.query('select reference_key,source_manifest_sha256 from tcg_private.r2_first_catalogue_links order by reference_key')).rows;
  assert.equal(immutable.find(row => row.reference_key===one).source_manifest_sha256,first);
  assert.equal(immutable.find(row => row.reference_key===two).source_manifest_sha256,second);

  // Privilege failure in the INVOKER audit trigger rolls the pointer back too.
  await db.exec('reset role; revoke insert on tcg_private.r2_first_catalogue_events from tcg_api; set role tcg_api');
  await asUser(admin);
  await rejected(() => db.query('update tcg_private.r2_first_catalogue_publications set generation=4'), '42501');
  assert.equal((await publications()).rows[0].generation, 3);
  assert.equal((await events()).rows.length, 3);
  await db.exec('reset role; grant insert on tcg_private.r2_first_catalogue_events to tcg_api; set role tcg_api');
  await asUser(admin);
  await rejected(() => db.query('update tcg_private.r2_first_catalogue_events set active=false'), '42501');
  await rejected(() => db.query('delete from tcg_private.r2_first_catalogue_events'), '42501');
  await rejected(() => db.query('delete from tcg_private.r2_first_catalogue_publications'), '42501');
  await asUser(outsider);
  assert.equal((await publications()).rows.length, 0);
  assert.equal((await db.query('select * from tcg_private.r2_first_catalogue_links')).rows.length, 0);
  await rejected(() => publish(1,outsider,{provider:'outsider_provider'}), '42501');
  await asUser('');
  assert.equal((await publications()).rows.length, 0);
  for (const role of ['anon','authenticated','service_role']) {
    await db.exec('reset role; set role '+role);
    await rejected(publications, '42501');
    await rejected(events, '42501');
    await rejected(() => db.query('select * from tcg_private.r2_first_catalogue_links'), '42501');
    await rejected(saved, '42501');
  }
  await db.exec('reset role');
  const checks = (await db.query(`select constraint_name from information_schema.table_constraints
    where table_schema='tcg' and table_name='catalogue_saved_references' and constraint_type='CHECK'`)).rows;
  assert(checks.some(row=>row.constraint_name==='catalogue_saved_references_reference_key_check'));
  console.log('R2-first registry PostgreSQL checks passed: forced RLS, member read/admin publication, actor binding, exact generation, audit atomicity and immutability, active/current manifest links, owner bookmarks, legacy keys and unprivileged-role denial.');
} finally {
  await db.close();
}
