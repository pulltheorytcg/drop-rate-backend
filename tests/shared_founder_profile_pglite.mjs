// Execute the real roster and profile migrations against disposable PostgreSQL.
import {PGlite} from '../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const db = new PGlite(); await db.waitReady;
const ids = Array.from({length: 6}, (_, i) => `00000000-0000-4000-8000-${String(i+1).padStart(12, '0')}`);
const ownerIds = Array.from({length: 6}, (_, i) => `00000000-0000-4000-9000-${String(i+1).padStart(12, '0')}`);
const migration = name => readFile(new URL('../database/migrations/'+name, import.meta.url), 'utf8');
try {
  await db.exec(`create schema tcg; create schema auth;
    create role tcg_api; create role anon; create role authenticated;
    create table auth.users(id uuid primary key,email_confirmed_at timestamptz default now());
    create table tcg.owners(id uuid primary key,display_name text,owner_type text,founder_slot smallint,active bool default true,commission_bps integer default 0,created_at timestamptz default now());
    create table tcg.owner_memberships(id uuid default gen_random_uuid(),user_id uuid,owner_id uuid,role text,active bool default true);
    create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
    create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
    grant usage on schema tcg to tcg_api; grant execute on function tcg.current_user_id() to tcg_api;`);
  for (let i=0; i<6; i++) {
    await db.query('insert into auth.users(id) values($1)', [ids[i]]);
    await db.query('insert into tcg.owners(id,display_name,owner_type,founder_slot) values($1,$2,$3,$4)', [ownerIds[i], 'Account '+i, i<3?'FOUNDER':'CONSIGNOR', i<3?i+1:null]);
    await db.query('insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)', [ids[i],ownerIds[i],i===3?'OWNER':'PLATFORM_ADMIN']);
  }
  await db.exec(await migration('20261002024856_unified_founder_app_access.sql'));
  await db.exec(await migration('20260930230500_owner_profile_settings.sql'));
  await db.exec(await migration('20261104103233_shared_founder_profile.sql'));
  // No direct table grant; the function alone can update the caller's profile.
  await db.exec('set role tcg_api');
  for (let i=0; i<4; i++) {
    await db.query("select set_config('tcg.user_id',$1,false)", [ids[i]]);
    const result = await db.query('select * from tcg.update_owner_profile($1,$2)', ['Updated '+i,'account_'+i]);
    assert.equal(result.rows[0].owner_id, ownerIds[i]);
    assert.equal(result.rows[0].display_name, 'Updated '+i);
  }
  for (const id of [ids[4],ids[5],'']) {
    await db.query("select set_config('tcg.user_id',$1,false)", [id]);
    await assert.rejects(db.query("select * from tcg.update_owner_profile('Forbidden','forbidden')"), error => error.code==='42501');
  }
  await db.exec('reset role');
  // Revoke a founder in the real roster. Neither a role nor a stale session grants access.
  await db.query('update tcg.founder_app_accounts set active=false where user_id=$1',[ids[0]]);
  await db.exec('set role tcg_api');
  await db.query("select set_config('tcg.user_id',$1,false)",[ids[0]]);
  await assert.rejects(db.query("select * from tcg.update_owner_profile('Revoked',null)"),error=>error.code==='42501');
  await db.query("select set_config('tcg.user_id',$1,false)",[ids[1]]);
  await assert.rejects(db.query("select * from tcg.update_owner_profile('Duplicate','account_3')"),error=>error.code==='23505');
  await assert.rejects(db.query("update tcg.owners set display_name='Cross-owner' where id=$1",[ownerIds[3]]),error=>error.code==='42501');
  await db.exec('reset role');
  const audit = await db.query("select * from tcg.audit_events where action='OWNER_PROFILE_UPDATED' order by actor");
  assert.equal(audit.rows.length,4);
  for (let i=0;i<4;i++) {
    assert.equal(audit.rows[i].actor,ids[i]);assert.equal(audit.rows[i].entity_id,ownerIds[i]);
    assert.equal(audit.rows[i].old_values.display_name,'Account '+i);
    assert.equal(audit.rows[i].new_values.display_name,'Updated '+i);
  }
  const unchanged = await db.query('select display_name from tcg.owners where id=$1',[ownerIds[4]]);
  assert.equal(unchanged.rows[0].display_name,'Account 4');
  console.log('PASS: real PostgreSQL founder roster, personal-only profile, three founders + seller, generic-admin denial, revocation, uniqueness, direct-write denial and audit.');
} finally {await db.close();}
