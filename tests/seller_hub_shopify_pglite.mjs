// Isolated in-memory PostgreSQL contract: no production DSN or real customers.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { PGlite } from '../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const original = readFileSync(resolve(root, 'database/migrations/20261031190234_seller_hub_launch_waitlist.sql'), 'utf8');
const mirror = readFileSync(resolve(root, 'database/migrations/20261031210000_seller_hub_shopify_contact_sync.sql'), 'utf8');
const db = new PGlite();
const email = 'synthetic-seller@example.invalid';

async function scalar(sql, params = []) {
  const result = await db.query(sql, params);
  return Object.values(result.rows[0] || {})[0];
}

try {
  await db.exec(`
    create schema tcg;
    create schema tcg_private;
    create role anon;
    create role authenticated;
    create role service_role;
    create role tcg_api;
    grant usage on schema tcg_private to tcg_api;
  `);
  await db.exec(original);
  await db.exec(mirror);

  await db.query('select tcg_private.register_seller_hub_interest($1,$2,$3,$4)',
    ['synthetic-old@example.invalid', 'Earlier Signup', 'CARDS', true]);
  assert.equal(await scalar("select shopify_sync_state from tcg.seller_hub_launch_waitlist where email='synthetic-old@example.invalid'"), 'NOT_REQUESTED');

  await db.query('select tcg_private.register_seller_hub_interest_for_shopify($1,$2,$3,$4,$5)',
    [email.toUpperCase(), 'Synthetic Contact', 'SEALED', true, true]);
  assert.equal(await scalar('select shopify_sync_state from tcg.seller_hub_launch_waitlist where email=$1', [email]), 'PENDING');
  assert.equal(await scalar('select consent_version from tcg.seller_hub_launch_waitlist where email=$1', [email]), 'seller-hub-shopify-2026-10-31');

  // A pre-disclosure contact gets exported only after fresh disclosed consent.
  await db.query('select tcg_private.register_seller_hub_interest_for_shopify($1,$2,$3,$4,$5)',
    ['synthetic-old@example.invalid', 'Earlier Signup', 'CARDS', true, true]);
  assert.equal(await scalar("select shopify_sync_state from tcg.seller_hub_launch_waitlist where email='synthetic-old@example.invalid'"), 'PENDING');

  let denied = false;
  try {
    await db.query('select tcg_private.register_seller_hub_interest_for_shopify($1,$2,$3,$4,$5)',
      ['denied@example.invalid', '', 'CARDS', true, false]);
  } catch { denied = true; }
  assert.ok(denied, 'No Shopify mirror without explicit disclosure acknowledgement');

  const claims = (await db.query('select * from tcg_private.claim_seller_hub_shopify_sync(10)')).rows;
  assert.equal(claims.length, 2, 'Only explicitly disclosed contacts claimed');
  const first = claims.find(c => c.contact_email === email);
  const other = claims.find(c => c.contact_email !== email);
  assert.ok(first?.lease_token && other?.lease_token);
  assert.equal(await scalar('select tcg_private.finish_seller_hub_shopify_sync($1,$2,$3)',
    [first.waitlist_id, other.lease_token, 'gid://shopify/Customer/12345']), false, 'Wrong lease denied');
  assert.equal(await scalar('select tcg_private.finish_seller_hub_shopify_sync($1,$2,$3)',
    [first.waitlist_id, first.lease_token, null]), true, 'Temporary failure requeued');
  assert.equal(await scalar('select shopify_sync_state from tcg.seller_hub_launch_waitlist where email=$1', [email]), 'RETRY');
  assert.equal((await db.query('select * from tcg_private.claim_seller_hub_shopify_sync(10)')).rows.length, 0,
    'Pending claims stay leased and retries are delayed');

  await db.query('update tcg.seller_hub_launch_waitlist set shopify_next_attempt_at=now()-interval \'1 second\' where email=$1', [email]);
  const second = (await db.query('select * from tcg_private.claim_seller_hub_shopify_sync(1)')).rows[0];
  assert.equal(second.contact_email, email);
  assert.notEqual(second.lease_token, first.lease_token);
  assert.equal(await scalar('select tcg_private.finish_seller_hub_shopify_sync($1,$2,$3)',
    [first.waitlist_id, first.lease_token, 'gid://shopify/Customer/12345']), false, 'Expired lease cannot ack');
  assert.equal(await scalar('select tcg_private.finish_seller_hub_shopify_sync($1,$2,$3)',
    [second.waitlist_id, second.lease_token, 'gid://shopify/Customer/12345']), true);
  assert.equal(await scalar('select shopify_sync_state from tcg.seller_hub_launch_waitlist where email=$1', [email]), 'SYNCED');

  // A withdrawn registration is never included in the outbox claim.
  await db.query("update tcg.seller_hub_launch_waitlist set status='UNSUBSCRIBED' where email='synthetic-old@example.invalid'");
  assert.equal((await db.query('select * from tcg_private.claim_seller_hub_shopify_sync(10)')).rows.length, 0);

  // The role can execute limited functions but cannot inspect the contact table.
  await db.exec('set role tcg_api');
  let forbidden = false;
  try { await db.query('select email from tcg.seller_hub_launch_waitlist'); }
  catch { forbidden = true; }
  assert.ok(forbidden, 'tcg_api cannot read raw waitlist contacts');
  await db.exec('reset role');

  console.log('Seller Hub Shopify SQL: consent, legacy privacy, claims, retry, lease, unsubscribe and RLS passed');
} finally {
  await db.close();
}
