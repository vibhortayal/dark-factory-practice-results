import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { setup, k, balanceSum } from './helper.js';

let c, t;
before(async () => ({ c, t } = await setup()));
after(() => c.stop());

const rawRequest = (port, bytes) => new Promise((resolve) => {
  const s = net.connect(port, '127.0.0.1', () => s.write(bytes));
  let out = '';
  s.on('data', (d) => (out += d.toString('latin1')));
  s.on('close', () => resolve(out));
  setTimeout(() => { s.destroy(); }, 1500);
});

test('D9: hostile input never produces 5xx and the server survives', async () => {
  const bodies = [
    '[' .repeat(100000), '{"a":'.repeat(50000), '{"to_handle":"bob","amount":1e400}', '{"amount":1e999999999}',
    '{"note":"' + 'x'.repeat(3000000) + '"}', '\u0000', '﻿{}', '"str"', 'null', '123', 'true', '{"a":}', '{"to_handle":"bob","amount":' + '9'.repeat(5000) + '}',
    JSON.stringify({ participant_handles: Array.from({ length: 5000 }, (_, i) => `u${i}`), amount: 1 }),
    JSON.stringify({ transfers: Array.from({ length: 5000 }, () => ({})) }),
    '{"__proto__":{"x":1},"to_handle":"bob","amount":1}', '{"constructor":1}',
  ];
  for (const raw of bodies) {
    for (const p of ['/payments', '/requests', '/splits', '/settlements', '/requests/x/pay', '/auth/signup', '/auth/login', '/_test/import', '/_test/reset']) {
      const tok = p === '/settlements' ? t.op : t.ada;
      const r = await c.post(p, { token: tok, key: k(), raw });
      assert.ok(r.status < 500, `${p} ${r.status} ${raw.slice(0, 30)}`);
      if (r.status >= 400) assert.ok(r.json && r.json.error && typeof r.json.error.code === 'string');
    }
  }
  const r = await c.get('/health');
  assert.equal(r.status, 200);
});

test('D9: invalid UTF-8 and bad percent-encoding', async () => {
  const bad = Buffer.from([0x7b, 0x22, 0x61, 0x22, 0x3a, 0x22, 0xff, 0xfe, 0x22, 0x7d]);
  const r = await fetch(c.base + '/payments', { method: 'POST', headers: { authorization: `Bearer ${t.ada}`, 'idempotency-key': k(), 'content-type': 'application/json' }, body: bad });
  assert.equal(r.status, 400);
  assert.equal((await r.json()).error.code, 'malformed_request');
  const q = await c.get('/activity?limit=%ZZ', { token: t.ada });
  assert.equal(q.status, 422);
  const u = await c.get('/requests/%ZZ', { token: t.ada });
  assert.ok(u.status < 500);
  const x = await c.post('/requests/%ZZ/cancel', { token: t.ada });
  assert.equal(x.status, 404);
});

test('D6: a 10 kB Idempotency-Key reaches validation', async () => {
  const r = await c.post('/payments', { token: t.ada, key: 'k'.repeat(10000), body: { to_handle: 'bob', amount: 1 } });
  assert.equal(r.status, 422);
  assert.equal(r.json.error.code, 'validation_failed');
});

test('D9: malformed HTTP gets an envelope, not a crash', async () => {
  const port = new URL(c.base).port;
  const out = await rawRequest(port, 'GARBAGE\r\n\r\n');
  assert.match(out, /400/);
  assert.equal((await c.get('/health')).status, 200);
  assert.equal(await balanceSum(c, [t.ada, t.bob, t.cy, t.op]), 12500);
});
