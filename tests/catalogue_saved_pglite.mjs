// Actual PostgreSQL policy/privilege assertions in a disposable in-memory DB.
// No network, remote DSN, Supabase project or production credentials are used.
import { PGlite } from '../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const db=new PGlite();await db.waitReady;
const a='00000000-0000-4000-8000-000000000001',b='00000000-0000-4000-8000-000000000002';
const key='r:'+'a'.repeat(32),other='s:'+'b'.repeat(32);
try{
  await db.exec(`create role anon;create role authenticated;create role service_role;create role tcg_api;
    create schema auth;create schema tcg;
    create table auth.users(id uuid primary key);
    create function tcg.current_user_id() returns uuid language sql stable as
      $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
    grant usage on schema tcg to tcg_api;
    grant execute on function tcg.current_user_id() to tcg_api;`);
  await db.query('insert into auth.users values($1),($2)',[a,b]);
  await db.exec(await readFile(new URL('../database/migrations/20261103143718_catalogue_saved_references.sql',import.meta.url),'utf8'));
  await db.exec('set role tcg_api');
  const asUser=id=>db.query("select set_config('tcg.user_id',$1,false)",[id]);
  const put=(user,keys)=>db.query('insert into tcg.catalogue_saved_references(user_id,reference_key) select $1,reference_key from unnest($2::text[]) as reference_key on conflict (user_id,reference_key) do nothing',[user,keys]);
  const list=()=>db.query('select user_id,reference_key from tcg.catalogue_saved_references');
  await asUser(a);await put(a,[key]);await put(a,[key]);
  assert.deepEqual((await list()).rows,[{user_id:a,reference_key:key}]);
  await asUser(b);assert.equal((await list()).rows.length,0);
  await assert.rejects(()=>put(a,[other]),error=>error.code==='42501');
  await db.query('delete from tcg.catalogue_saved_references where user_id=$1',[a]);
  await put(b,[other]);assert.deepEqual((await list()).rows,[{user_id:b,reference_key:other}]);
  await asUser(a);assert.deepEqual((await list()).rows,[{user_id:a,reference_key:key}]);
  await assert.rejects(()=>db.query('update tcg.catalogue_saved_references set user_id=$1',[b]),error=>error.code==='42501');
  await assert.rejects(()=>put(a,['r:invalid']),error=>error.code==='23514');
  await asUser('');assert.equal((await list()).rows.length,0);
  await assert.rejects(()=>put(a,[other]),error=>error.code==='42501');
  await db.exec('reset role');
  assert.equal((await db.query("select relforcerowsecurity from pg_class where oid='tcg.catalogue_saved_references'::regclass")).rows[0].relforcerowsecurity,true);
  for(const role of ['anon','authenticated','service_role']){
    await db.exec('set role '+role);
    await assert.rejects(list,error=>error.code==='42501');
    await assert.rejects(()=>put(a,[other]),error=>error.code==='42501');
    await db.exec('reset role');
  }
  await db.exec('set role tcg_api');await asUser(a);
  await db.query('delete from tcg.catalogue_saved_references where user_id=$1 and reference_key=$2',[a,key]);
  assert.equal((await list()).rows.length,0);
  await asUser(b);assert.equal((await list()).rows.length,1);
  console.log('Saved references PostgreSQL checks passed: own read/write/delete, duplicate safety, cross-account denial, no identity reassignment, anonymous denial and strict keys.');
}finally{await db.close();}
