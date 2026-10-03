import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../Resources/session-bridge.js', import.meta.url), 'utf8');
const key = 'drop_rate_hub_session';
function fixture({bootstrap = null, existing = null, initial = {}, origin = 'https://drop-rate-api-live-production.up.railway.app', main = true} = {}) {
  class Storage {
    data = new Map();
    getItem(k) { return this.data.get(String(k)) ?? null; }
    setItem(k, v) { this.data.set(String(k), String(v)); }
    removeItem(k) { this.data.delete(String(k)); }
    clear() { this.data.clear(); }
  }
  const sessionStorage = new Storage(), localStorage = new Storage(), messages = [], listeners = {};
  for (const [k, value] of Object.entries(initial)) sessionStorage.setItem(k, value);
  if (existing) sessionStorage.setItem(key, JSON.stringify(existing));
  const window = {webkit: {messageHandlers: {hubSession: {postMessage: m => messages.push(JSON.parse(JSON.stringify(m)))}}},
    addEventListener: (event, callback) => { listeners[event] = callback; }};
  window.top = main ? window : {};
  runInNewContext(source.replace('__DROP_RATE_BOOTSTRAP__', JSON.stringify(bootstrap)), {
    window, location: {origin}, Storage, sessionStorage, localStorage,
  });
  return {sessionStorage, localStorage, messages, listeners};
}
test('restores Keychain session before the unchanged hub starts without publishing credentials to another channel', () => {
  const session = {access_token: 'fixture', refresh_token: 'fixture-refresh'};
  const f = fixture({bootstrap: session});
  assert.deepEqual(JSON.parse(f.sessionStorage.getItem(key)), session);
  assert.equal(f.messages.length, 0);
});
test('never overwrites a newer session during owner/founder navigation', () => {
  const f = fixture({bootstrap: {access_token: 'old'}, existing: {access_token: 'new'}});
  assert.equal(JSON.parse(f.sessionStorage.getItem(key)).access_token, 'new');
});
test('persists refresh rotation, logout and storage.clear in order', () => {
  const f = fixture();
  f.sessionStorage.setItem(key, '{"access_token":"rotated","refresh_token":"rotated"}');
  f.sessionStorage.removeItem(key);
  f.sessionStorage.clear();
  assert.deepEqual(f.messages.map(m => m.value), ['{"access_token":"rotated","refresh_token":"rotated"}', null, null]);
});
test('does not persist other keys, forms, local storage or profile data', () => {
  const f = fixture();
  f.sessionStorage.setItem('draft', 'private card data');
  f.localStorage.setItem(key, 'another application');
  f.localStorage.clear();
  assert.equal(f.messages.length, 0);
});
test('does not inject or listen on external pages and subframes', () => {
  for (const config of [{origin: 'https://evil.test'}, {main: false}]) {
    const f = fixture({...config, bootstrap: {access_token: 'must-stay-private'}});
    assert.equal(f.sessionStorage.getItem(key), null);
    f.sessionStorage.setItem(key, 'external');
    assert.equal(f.messages.length, 0);
  }
});
test('the actual shared hub logout removes the native session', () => {
  const f = fixture({bootstrap: {access_token: 'fixture', refresh_token: 'fixture-refresh'}});
  f.sessionStorage.removeItem(key);
  f.listeners['hub-session-cleared']();
  assert.deepEqual(f.messages.at(-1), {type: 'session', value: null});
});
test('logout immediately followed by navigation cannot restore a stale native snapshot', () => {
  const bootstrap = {access_token: 'old-account', refresh_token: 'old-refresh'};
  for (const logout of [s => s.removeItem(key), s => s.clear()]) {
    const first = fixture({bootstrap});
    logout(first.sessionStorage);
    const nextPage = fixture({bootstrap, initial: Object.fromEntries(first.sessionStorage.data)});
    assert.equal(nextPage.sessionStorage.getItem(key), null);
  }
});
