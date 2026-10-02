'use strict';

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const h = require('./helpers');
const { call } = h;

before(h.start);
after(h.stop);

const burst = (n, fn) => Promise.all(Array.from({ length: n }, (_, i) => fn(i)));
const count = (rs, status) => rs.filter((r) => r.status === status).length;
const total = async (t) => Object.values(await h.balances(t)).reduce((a, b) => a + b, 0);

test('50 clients sending the whole balance: exactly one succeeds', async () => {
  await h.reset();
  const t = await h.tokens();
  const rs = await burst(50, (i) => call('POST', '/payments', { token: t.ada, key: `k${i}`, body: { to_handle: 'bob', amount: 10000 } }));
  assert.equal(count(rs, 201), 1);
  assert.equal(count(rs, 409), 49);
  assert.deepEqual(await h.balances(t), { ada: 0, bob: 12500, cy: 0 });
});

test('concurrent identical requests with one key: one 201, the rest 200, one effect', async () => {
  await h.reset();
  const t = await h.tokens();
  const cases = [
    ['/payments', { to_handle: 'bob', amount: 100 }],
    ['/requests', { payer_handle: 'bob', amount: 100 }],
    ['/splits', { amount: 100, participant_handles: ['ada', 'bob', 'cy'] }],
  ];
  for (const [path, body] of cases) {
    const rs = await burst(50, () => call('POST', path, { token: t.ada, key: `same${path}`, body }));
    assert.equal(count(rs, 201), 1, path);
    assert.equal(count(rs, 200), 49, path);
    assert.equal(new Set(rs.map((r) => JSON.stringify(r.body))).size, 1, path);
  }
  assert.equal((await h.balances(t)).ada, 9900);
  const s = await burst(50, () => call('POST', '/settlements', { token: t.cy, key: 'st', body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }] } }));
  assert.equal(count(s, 201), 1);
  assert.equal(count(s, 200), 49);
  assert.equal((await h.balances(t)).ada, 9899);
});

test('same key, different bodies: only one takes effect', async () => {
  await h.reset();
  const t = await h.tokens();
  const rs = await burst(50, (i) => call('POST', '/payments', { token: t.ada, key: 'one', body: { to_handle: 'bob', amount: i + 1 } }));
  assert.equal(count(rs, 201), 1);
  assert.equal(count(rs, 409), 49);
  assert.equal(await total(t), 12500);
});

test('a request is paid at most once under pay/decline/cancel races', async () => {
  await h.reset();
  const t = await h.tokens();
  await call('POST', '/payments', { token: t.bob, key: 'seed', body: { to_handle: 'ada', amount: 2500 } });
  for (let round = 0; round < 5; round++) {
    const rq = (await call('POST', '/requests', { token: t.cy, key: `r${round}`, body: { payer_handle: 'ada', amount: 100 } })).body.request_id;
    const before = await h.balances(t);
    const rs = await Promise.all([
      ...Array.from({ length: 20 }, (_, i) => call('POST', `/requests/${rq}/pay`, { token: t.ada, key: `p${round}-${i}`, body: {} })),
      ...Array.from({ length: 5 }, () => call('POST', `/requests/${rq}/decline`, { token: t.ada })),
      ...Array.from({ length: 5 }, () => call('POST', `/requests/${rq}/cancel`, { token: t.cy })),
    ]);
    assert.ok(rs.every((r) => r.status < 500));
    const after = await h.balances(t);
    const final = (await call('GET', '/requests?limit=200', { token: t.cy })).body.requests.find((r) => r.request_id === rq).status;
    assert.equal(after.cy - before.cy, final === 'paid' ? 100 : 0);
    assert.equal(count(rs.slice(0, 20), 201), final === 'paid' ? 1 : 0);
  }
});

test('three-wallet payment cycle conserves the total and never goes negative', async () => {
  await h.reset({ ...h.FIXTURE, users: h.FIXTURE.users.map((u) => ({ ...u, balance: 1000 })), payments: [], requests: [] });
  const t = await h.tokens();
  const ring = [['ada', 'bob'], ['bob', 'cy'], ['cy', 'ada']];
  let negative = false;
  let reading = true;
  const watcher = (async () => {
    while (reading) {
      const b = await h.balances(t);
      if (Object.values(b).some((v) => v < 0)) negative = true;
    }
  })();
  const rs = await burst(150, (i) => {
    const [from, to] = ring[i % 3];
    return call('POST', '/payments', { token: t[from], key: `c${i}`, body: { to_handle: to, amount: 300 + (i % 7) * 100 } });
  });
  reading = false;
  await watcher;
  assert.ok(rs.every((r) => r.status === 201 || r.status === 409));
  assert.equal(negative, false);
  assert.equal(await total(t), 3000);
});

test('50 concurrent logins and signups of one identity', async () => {
  await h.reset();
  const t0 = Date.now();
  const logins = await burst(50, () => call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } }));
  assert.ok(logins.every((r) => r.status === 200));
  assert.ok(Date.now() - t0 < 5000);
  const signups = await burst(20, () => call('POST', '/auth/signup', { body: { email: 'new@x.io', password: 'longenough', display_name: 'N' } }));
  assert.equal(count(signups, 201), 1);
  assert.equal(count(signups, 409), 19);
  const same = await burst(20, (i) => call('POST', '/auth/signup', { body: { email: `same${i}@a.io`.replace(/same\d+/, 'dup') + '', password: 'longenough', display_name: 'N' } }));
  assert.equal(count(same, 201), 1);
});

test('reset with 200 users is fast', async () => {
  const users = Array.from({ length: 200 }, (_, i) => ({ id: `u${i}`, email: `u${i}@x.io`, password: 'password1', display_name: 'U', handle: `u${i}`, balance: 10 }));
  const t0 = Date.now();
  await h.reset({ currency: 'EUR', minor_units: 2, users });
  assert.ok(Date.now() - t0 < 5000, `took ${Date.now() - t0} ms`);
});

test('exact arithmetic near 2^53', async () => {
  const big = 2 ** 53 - 2;
  await h.reset({ currency: 'BHD', minor_units: 3, users: h.FIXTURE.users.map((u, i) => ({ ...u, balance: i === 0 ? big : 0 })) });
  const t = await h.tokens();
  const r = await call('POST', '/payments', { token: t.ada, key: 'x', body: { to_handle: 'bob', amount: 1 } });
  assert.equal(r.status, 201);
  assert.match(r.text, /"amount":1,/);
  const me = await call('GET', '/me', { token: t.ada });
  assert.equal(me.body.balance, big - 1);
  assert.match(me.text, new RegExp(`"balance":${big - 1},`));
  assert.equal(me.body.minor_units, 3);
});

test('hostile input never yields a 5xx', async () => {
  await h.reset();
  const t = await h.tokens();
  const bodies = ['', '{', '[]', 'null', '1', '"s"', '{"amount":1e999}', '[' .repeat(50000), '{"a":'.repeat(5000) + '1' + '}'.repeat(5000), '\u0000', '{"to_handle":"bob","amount":1,"note":"' + 'x'.repeat(100000) + '"}'];
  const paths = [['POST', '/payments'], ['POST', '/requests'], ['POST', '/splits'], ['POST', '/settlements'], ['POST', '/requests/rq_1/pay'], ['POST', '/auth/signup'], ['POST', '/auth/login'], ['POST', '/_test/import'], ['POST', '/requests/rq_1/decline']];
  for (const [m, p] of paths) {
    for (const body of bodies) {
      const r = await call(m, p, { token: t.cy, key: 'f' + Math.random(), body });
      assert.ok(r.status < 500, `${m} ${p} -> ${r.status}`);
      if (r.status >= 400) assert.equal(typeof r.body.error.code, 'string');
    }
  }
  for (const path of ['/%', '/%zz', '/requests/%E0%A4%A/pay', '//', '/me/', '/_test/', '/requests/a/b/c', '/payments?limit=%']) {
    const r = await call('GET', path, { token: t.ada });
    assert.ok(r.status < 500, path);
  }
  const big = await call('POST', '/payments', { token: t.ada, key: 'big', body: Buffer.alloc(3 * 1024 * 1024, 0x20) });
  assert.equal(big.status, 400);
  assert.equal((await call('GET', '/health')).status, 200);
});

test('over-long values far beyond the limit still get their 422', async () => {
  await h.reset();
  const t = await h.tokens();
  const note = await call('POST', '/payments', { token: t.ada, key: 'big1', body: JSON.stringify({ to_handle: 'bob', amount: 1, note: 'n'.repeat(2200000) }) });
  assert.equal(note.status, 422);
  const many = Array.from({ length: 40000 }, () => ({ from_handle: 'ada', to_handle: 'bob', amount: 1 }));
  assert.equal((await call('POST', '/settlements', { token: t.cy, key: 'big2', body: { transfers: many } })).status, 422);
  const key = await call('POST', '/payments', { token: t.ada, key: 'k'.repeat(17000), body: { to_handle: 'bob', amount: 1 } });
  assert.equal(key.status, 422);
  assert.equal(key.body.error.code, 'validation_failed');
  assert.equal((await call('GET', `/activity?limit=${'9'.repeat(17000)}`, { token: t.ada })).status, 422);
  assert.equal((await call('GET', '/me', { token: 'x'.repeat(17000) })).status, 401);
});

test('holds under concurrency: available never negative, captures never exceed, totals conserved', async () => {
  await h.reset();
  const t = await h.tokens();
  const fresh = async () => (await call('POST', '/authorizations', { token: t.ada, key: `a${Math.random()}`, body: { to_handle: 'bob', amount: 4000 } })).body.authorization_id;
  // 50 authorisations of 4000 against 10000: at most two fit
  const rs = await burst(50, (i) => call('POST', '/authorizations', { token: t.ada, key: `h${i}`, body: { to_handle: 'bob', amount: 4000 } }));
  assert.equal(count(rs, 201), 2);
  assert.equal(count(rs, 409), 48);
  // payments cannot spend held money, concurrently
  const pays = await burst(50, (i) => call('POST', '/payments', { token: t.ada, key: `s${i}`, body: { to_handle: 'cy', amount: 1000 } }));
  assert.equal(count(pays, 201), 2);
  let m = (await call('GET', '/me', { token: t.ada })).body;
  assert.deepEqual([m.total, m.held, m.available], [8000, 8000, 0]);
  // 50-way capture of the first hold with distinct keys: remainder 4000 allows exactly one full capture
  const ids = rs.filter((r) => r.status === 201).map((r) => r.body.authorization_id);
  const caps = await burst(50, (i) => call('POST', `/authorizations/${ids[0]}/capture`, { token: t.bob, key: `c${i}`, body: { amount: 1500, final: false } }));
  assert.equal(count(caps, 201), 2);
  assert.equal(count(caps.filter((r) => r.status !== 201), 422), 48);
  // capture vs void vs second capture race on the second hold
  const mixed = await Promise.all([
    ...Array.from({ length: 20 }, (_, i) => call('POST', `/authorizations/${ids[1]}/capture`, { token: t.bob, key: `m${i}`, body: { amount: 1000, final: false } })),
    ...Array.from({ length: 20 }, () => call('POST', `/authorizations/${ids[1]}/void`, { token: t.ada })),
  ]);
  assert.ok(mixed.every((r) => r.status < 500));
  const reads = await Promise.all([t.ada, t.bob, t.cy].map((tok) => call('GET', '/me', { token: tok })));
  const sum = reads.reduce((a, r) => a + r.body.total, 0);
  assert.equal(sum, 12500);
  assert.ok(reads.every((r) => r.body.available >= 0 && r.body.available === r.body.total - r.body.held));
  const list = (await call('GET', '/authorizations?limit=200', { token: t.ada })).body.authorizations;
  const heldSum = list.reduce((a, x) => a + x.remaining_amount, 0);
  assert.equal(heldSum, reads[0].body.held);
  const moved = list.reduce((a, x) => a + x.captured_amount, 0);
  assert.equal(moved, 3000 + (list.find((x) => x.authorization_id === ids[1]).captured_amount));
  void fresh; void m;
});

test('same-key capture burst: one 201, the rest 200', async () => {
  await h.reset();
  const t = await h.tokens();
  const id = (await call('POST', '/authorizations', { token: t.ada, key: 'z', body: { to_handle: 'bob', amount: 900 } })).body.authorization_id;
  const rs = await burst(50, () => call('POST', `/authorizations/${id}/capture`, { token: t.bob, key: 'same-cap', body: { amount: 900 } }));
  assert.equal(count(rs, 201), 1);
  assert.equal(count(rs, 200), 49);
  assert.equal((await call('GET', '/me', { token: t.bob })).body.total, 3400);
});
