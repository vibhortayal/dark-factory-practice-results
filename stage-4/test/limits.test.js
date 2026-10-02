'use strict';

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const h = require('./helpers');
const { call } = h;
const { allSpecs } = require('../src/routes');

before(h.start);
after(h.stop);

const code = (r) => r.body && r.body.error && r.body.error.code;

function rawRequest(text) {
  const port = Number(new URL(h.base()).port);
  return new Promise((resolve) => {
    const s = net.connect(port, '127.0.0.1', () => s.write(text));
    let data = '';
    s.on('data', (d) => { data += d; });
    s.on('close', () => resolve(data));
    s.on('error', () => resolve(data));
    setTimeout(() => s.destroy(), 4000);
  });
}

test('size and nesting caps answer 422 with the error body, never 400 or bare', async () => {
  await h.reset();
  const t = await h.tokens();
  const huge = JSON.stringify({ to_handle: 'bob', amount: 1, note: 'n'.repeat(9 * 1024 * 1024) });
  let r = await call('POST', '/payments', { token: t.ada, key: 'h1', body: huge });
  assert.equal(r.status, 422);
  assert.equal(code(r), 'validation_failed');
  r = await call('POST', '/payments', { key: 'h1', body: huge });
  assert.equal(r.status, 401);
  r = await call('POST', '/settlements', { token: t.ada, key: 'h1', body: huge });
  assert.equal(r.status, 403);
  r = await call('POST', '/auth/login', { body: huge });
  assert.equal(r.status, 422);
  assert.equal((await call('GET', '/health')).status, 200);

  const deepArray = (n) => '['.repeat(n) + ']'.repeat(n);
  for (const depth of [201, 999, 1001, 5000, 100000]) {
    const body = `{"to_handle":"bob","amount":1,"note":${deepArray(depth)}}`;
    r = await call('POST', '/payments', { token: t.ada, key: `d${depth}`, body });
    assert.equal(r.status, 422, `depth ${depth}`);
    assert.equal(code(r), 'validation_failed');
  }
  const ok = `{"to_handle":"bob","amount":1,"extra":${deepArray(900)}}`;
  const first = await call('POST', '/payments', { token: t.ada, key: 'deep-ok', body: ok });
  assert.equal(first.status, 201);
  assert.equal((await call('POST', '/payments', { token: t.ada, key: 'deep-ok', body: ok })).status, 200);
  assert.equal((await call('GET', '/_test/export')).status, 200);
});

test('request heads up to 1 MiB reach the service rules; beyond that 422 with a body', async () => {
  await h.reset();
  const t = await h.tokens();
  let r = await call('POST', '/payments', { token: t.ada, key: 'k'.repeat(17000), body: { to_handle: 'bob', amount: 1 } });
  assert.equal(r.status, 422);
  r = await call('GET', `/requests?limit=${'9'.repeat(17000)}`, { token: t.ada });
  assert.equal(r.status, 422);
  r = await call('GET', '/me', { token: 'x'.repeat(100000) });
  assert.equal(r.status, 401);
  const raw = await rawRequest(`GET /me HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer ${'x'.repeat(1100000)}\r\nConnection: close\r\n\r\n`);
  assert.match(raw, /^HTTP\/1.1 422 /);
  assert.match(raw, /"code":"validation_failed"/);
});

test('percent-encoded path parameters are the same resource and idempotency scope', async () => {
  await h.reset();
  const t = await h.tokens();
  const a = await call('POST', '/requests/rq%5F1/pay', { token: t.ada, key: 'enc', body: {} });
  assert.equal(a.status, 201);
  const b = await call('POST', '/requests/rq_1/pay', { token: t.ada, key: 'enc', body: {} });
  assert.equal(b.status, 200);
  assert.deepEqual(b.body, a.body);
  const bad = await call('POST', '/requests/%E0%A4%A/pay', { token: t.ada, key: 'x', body: {} });
  assert.equal(bad.status, 404);
  assert.equal(code(bad), 'not_found');
});

test('idempotent handlers are synchronous (atomic claim, effect and record)', () => {
  const idem = allSpecs().filter((s) => s.idem);
  assert.equal(idem.length, 10);
  for (const s of idem) {
    assert.notEqual(s.fn.constructor.name, 'AsyncFunction');
  }
});
