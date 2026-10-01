import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { setup, k, balanceSum, login } from './helper.js';

let c, t;
before(async () => ({ c, t } = await setup()));
after(() => c.stop());
const all = () => [t.ada, t.bob, t.cy, t.op];
const count = (rs, s) => rs.filter((r) => r.status === s).length;

test('F7: 20-way identical race on each idempotent path', async () => {
  const jobs = [
    ['/payments', t.ada, { to_handle: 'bob', amount: 100 }],
    ['/requests', t.bob, { payer_handle: 'ada', amount: 100 }],
    ['/splits', t.ada, { amount: 100, participant_handles: ['bob', 'cy'] }],
    ['/settlements', t.op, { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 100 }] }],
  ];
  for (const [path, tok, body] of jobs) {
    const key = k();
    const rs = await Promise.all(Array.from({ length: 20 }, () => c.post(path, { token: tok, key, body })));
    assert.equal(count(rs, 201), 1, path);
    assert.equal(count(rs, 200), 19, path);
    assert.equal(new Set(rs.map((r) => r.text)).size, 1);
  }
  // effect applied once: ada paid 100 (payment) + 100 (settlement)
  assert.equal((await c.get('/me', { token: t.ada })).json.balance, 9800);
  assert.equal(await balanceSum(c, all()), 12500);
  const act = (await c.get('/activity?limit=200', { token: t.ada })).json.payments;
  assert.equal(act.length, 2);
});

test('F7: pay with a shared key races once', async () => {
  const rq = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 50 } })).json.request_id;
  const key = k();
  const rs = await Promise.all(Array.from({ length: 20 }, () => c.post(`/requests/${rq}/pay`, { token: t.ada, key, body: {} })));
  assert.equal(count(rs, 201), 1); assert.equal(count(rs, 200), 19);
  assert.equal((await c.get('/me', { token: t.ada })).json.balance, 9750);
});

test('G14: a request moves money at most once (different keys, and against decline/cancel)', async () => {
  const before = (await c.get('/me', { token: t.bob })).json.balance;
  const rq = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 40 } })).json.request_id;
  const rs = await Promise.all(Array.from({ length: 20 }, () => c.post(`/requests/${rq}/pay`, { token: t.ada, key: k(), body: {} })));
  assert.equal(count(rs, 201), 1);
  assert.equal(count(rs, 409), 19);
  assert.ok(rs.filter((r) => r.status === 409).every((r) => r.json.error.code === 'request_not_pending'));
  assert.equal((await c.get('/me', { token: t.bob })).json.balance, before + 40);
  for (let i = 0; i < 10; i++) {
    const id = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 1 } })).json.request_id;
    const [pay, dec, can] = await Promise.all([
      c.post(`/requests/${id}/pay`, { token: t.ada, key: k(), body: {} }),
      c.post(`/requests/${id}/decline`, { token: t.ada }),
      c.post(`/requests/${id}/cancel`, { token: t.bob }),
    ]);
    const final = (await c.get('/requests?limit=200', { token: t.bob })).json.requests.find((r) => r.request_id === id);
    const wins = [pay.status === 201, dec.status === 200, can.status === 200];
    assert.equal(wins.filter(Boolean).length, 1, JSON.stringify([pay.json, dec.json, can.json]));
    assert.equal(final.status, pay.status === 201 ? 'paid' : dec.status === 200 ? 'declined' : 'cancelled');
  }
  assert.equal(await balanceSum(c, all()), 12500);
});

test('H2: burst over one wallet, and A<->B cross payments', async () => {
  // cy funded with 1000, 50 concurrent payments of 30 => exactly 33 succeed
  await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 1000 } });
  const rs = await Promise.all(Array.from({ length: 50 }, () => c.post('/payments', { token: t.cy, key: k(), body: { to_handle: 'op', amount: 30 } })));
  assert.equal(count(rs, 201), 33);
  assert.equal(count(rs, 409), 17);
  assert.equal((await c.get('/me', { token: t.cy })).json.balance, 10);
  assert.equal(await balanceSum(c, all()), 12500);
  const x = [];
  for (let i = 0; i < 25; i++) {
    x.push(c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 7 } }));
    x.push(c.post('/payments', { token: t.bob, key: k(), body: { to_handle: 'ada', amount: 5 } }));
  }
  const rr = await Promise.all(x);
  assert.ok(rr.every((r) => r.status === 201));
  assert.equal(await balanceSum(c, all()), 12500);
});

test('J14: settlements and payments over the same wallets', async () => {
  const sum0 = await balanceSum(c, all());
  const a0 = (await c.get('/me', { token: t.ada })).json.balance;
  const jobs = [];
  for (let i = 0; i < 25; i++) {
    jobs.push(c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 400 }, { from_handle: 'bob', to_handle: 'cy', amount: 100 }] } }));
    jobs.push(c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 300 } }));
  }
  const rs = await Promise.all(jobs);
  assert.ok(rs.every((r) => r.status === 201 || (r.status === 409 && r.json.error.code === 'insufficient_funds')));
  assert.equal(await balanceSum(c, all()), sum0);
  for (const tok of all()) assert.ok((await c.get('/me', { token: tok })).json.balance >= 0);
  const a1 = (await c.get('/me', { token: t.ada })).json.balance;
  const ok = rs.filter((r) => r.status === 201).length;
  assert.ok(a0 - a1 >= 0 && ok > 0);
  assert.equal(a1 >= 0, true);
});

test('A5: 50-way mixed load completes quickly', async () => {
  const start = Date.now();
  const jobs = [];
  for (let i = 0; i < 20; i++) jobs.push(login(c, 'bob@example.com'));
  for (let i = 0; i < 15; i++) jobs.push(c.get('/activity', { token: t.ada }));
  for (let i = 0; i < 15; i++) jobs.push(c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 1 } }));
  const rs = await Promise.all(jobs);
  assert.ok(rs.every((r) => typeof r === 'string' || r.status < 500));
  assert.ok(Date.now() - start < 5000, `took ${Date.now() - start}ms`);
});

test('A5: 50 concurrent signups and a 300-user reset stay inside limits', async () => {
  const s = Date.now();
  const rs = await Promise.all(Array.from({ length: 50 }, (_, i) => c.post('/auth/signup', { body: { email: `load${i}@x.io`, password: 'longenough', display_name: 'L' } })));
  assert.ok(rs.every((r) => r.status === 201));
  assert.ok(Date.now() - s < 5000, `signups took ${Date.now() - s}ms`);
  const users = Array.from({ length: 300 }, (_, i) => ({ id: `u${i}`, email: `u${i}@x.io`, password: 'correct horse', display_name: `U${i}`, handle: `u${i}`, balance: 1000 }));
  const r0 = Date.now();
  assert.equal((await c.reset({ currency: 'EUR', minor_units: 2, users })).status, 204);
  assert.ok(Date.now() - r0 < 10000, `reset took ${Date.now() - r0}ms`);
  const l0 = Date.now();
  const logins = await Promise.all(Array.from({ length: 50 }, (_, i) => c.post('/auth/login', { body: { email: `u${i}@x.io`, password: 'correct horse' } })));
  assert.ok(logins.every((r) => r.status === 200));
  assert.ok(Date.now() - l0 < 5000);
  const e0 = Date.now();
  const ex = await c.get('/_test/export');
  assert.equal(ex.status, 200);
  assert.equal((await c.post('/_test/import', { body: ex.json })).status, 204);
  assert.ok(Date.now() - e0 < 10000);
});
