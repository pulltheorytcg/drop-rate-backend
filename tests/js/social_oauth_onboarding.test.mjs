import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const ownerSource = readFileSync(path.join(root, 'backend/app/static/owner-join.js'), 'utf8');
const loginSource = readFileSync(path.join(root, 'backend/app/static/app.js'), 'utf8');

function element() {
  const classes = new Set(['hidden']);
  return {
    value: '',
    textContent: '',
    className: '',
    focus() { this.focused = true; },
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
  };
}

function ownerHarness({email = 'seller@example.com', metadata = {}, acknowledged = true} = {}) {
  const nodes = new Map();
  const values = new Map();
  const registrations = [];
  const redirects = [];
  const context = vm.createContext({
    document: {getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, element());
      return nodes.get(id);
    }},
    localStorage: {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: key => values.delete(key),
    },
    window: {location: {replace: url => redirects.push(url)}},
    fetch: async () => ({ok: true, json: async () => ({email, user_metadata: metadata})}),
    testRegistrations: registrations,
  });
  // Evaluate real production functions, excluding DOM event wiring/startup.
  vm.runInContext(ownerSource.slice(0, ownerSource.indexOf('byId("owner-join-google").addEventListener')), context);
  vm.runInContext(`state.config = {supabase_url:'https://supabase.test',publishable_key:'public'};
    state.acknowledgementVersion = 1; state.invite = {acknowledgement_version:1};
    completeSellerRegistration = async (_session, name) => { testRegistrations.push(name); };`, context);
  if (acknowledged) values.set('drop_rate_pending_owner_ack', '1');
  const session = {access_token: 'test-only-access-token', refresh_token: 'test-only-refresh-token'};
  return {
    nodes,
    registrations,
    redirects,
    async finish(name = null) {
      context.testSession = session;
      context.testName = name;
      return vm.runInContext('finishAuthenticatedOnboarding(testSession, testName)', context);
    },
  };
}

test('Apple sign-in with no name asks for a name before creating an owner', async () => {
  const browser = ownerHarness();
  await browser.finish();
  assert.equal(browser.nodes.get('owner-oauth-name-form').classList.contains('hidden'), false);
  assert.equal(browser.nodes.get('owner-oauth-name').focused, true);
  assert.deepEqual(browser.registrations, []);
  assert.deepEqual(browser.redirects, []);
});

test('providing the missing name completes registration using the same authenticated session', async () => {
  const browser = ownerHarness();
  await browser.finish();
  await browser.finish('  Casey Collector  ');
  assert.deepEqual(browser.registrations, ['Casey Collector']);
  assert.deepEqual(browser.redirects, ['/owner?welcome=1']);
});

test('social sign-in never skips the seller acknowledgement', async () => {
  const browser = ownerHarness({acknowledged: false});
  await assert.rejects(browser.finish('Casey Collector'), /acknowledgement/);
  assert.deepEqual(browser.registrations, []);
});

test('a provider account without an email cannot register as a seller', async () => {
  const browser = ownerHarness({email: null});
  await assert.rejects(browser.finish('Casey Collector'), /verified seller email/);
  assert.deepEqual(browser.registrations, []);
});

test('Google sign-in with a name does not require the extra step', async () => {
  const browser = ownerHarness({metadata: {full_name: 'Google Collector'}});
  await browser.finish();
  assert.deepEqual(browser.registrations, ['Google Collector']);
  assert.deepEqual(browser.redirects, ['/owner?welcome=1']);
});

test('Google/Apple callbacks return to /app, not the public launch landing page', () => {
  const redirects = [];
  const context = vm.createContext({
    document: {getElementById: () => element()},
    window: {location: {
      origin: 'https://app.droprate.co.uk',
      assign: url => redirects.push(url),
    }},
    URL,
  });
  vm.runInContext(loginSource.slice(0, loginSource.indexOf('function parseOAuthSession()')), context);
  vm.runInContext(`state.config = {supabase_url:'https://supabase.test'};
    state.providers.google = true; state.providers.apple = true;
    startOAuth('google'); startOAuth('apple');`, context);
  assert.deepEqual(redirects.map(url => new URL(url).searchParams.get('redirect_to')),
    ['https://app.droprate.co.uk/app', 'https://app.droprate.co.uk/app']);
});
