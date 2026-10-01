import { test } from 'vitest';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { liveProxy } from './live-proxy.mjs';
async function run(method, url, headers = {}, body = '') {
  const req = Readable.from([Buffer.from(body)]);
  Object.assign(req, {method, url, headers: {host:'127.0.0.1:8085', ...headers}});
  let forwarded;
  const res = {writeHead(status) {this.status = status; return this;}, end(body) {this.body = body;}};
  await liveProxy(req, res, async (url, options) => { forwarded = {url, options}; return new Response('{}'); });
  return {res, forwarded};
}
test('only viewing and same-origin sign-in reach the fixed service', async () => {
  const read = await run('GET','/api/v1/access/me');
  assert.equal(read.forwarded.url, 'https://drop-rate-api-live-production.up.railway.app/api/v1/access/me');
  const login = await run('POST','/api/v1/public/owner-session',{origin:'http://127.0.0.1:8085'},'{}');
  assert.equal(login.res.status,200);
  for (const [method,path,headers] of [
    ['PATCH','/api/v1/inventory/1',{}], ['POST','/api/v1/recognition/resolve',{}],
    ['DELETE','/api/v1/inventory/1',{}], ['POST','/api/v1/public/owner-session',{}],
    ['GET','/api/v1/access/me',{origin:'https://other.invalid'}],
    ['GET','/api/v1/access/me',{host:'other.invalid'}], ['GET','/api/v1/../../secret',{}],
  ]) {
    const result = await run(method,path,headers);
    assert.equal(result.res.status,403); assert.equal(result.forwarded,undefined);
  }
});
test('oversized sign-in payload never leaves the preview',async () => {
 const result = await run('POST','/api/v1/public/owner-session',{origin:'http://127.0.0.1:8085'},'a'.repeat(16385));
 assert.equal(result.res.status,413); assert.equal(result.forwarded,undefined);
});
