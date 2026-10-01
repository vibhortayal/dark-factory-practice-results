import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startServer, FX, k, login, balanceSum } from './helper.js';

let c, t;
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const at = (deltaSec) => new Date(Date.now() + deltaSec * 1000).toISOString().replace('Z', '+00:00');
const enc = (s) => encodeURIComponent(s);
const all = () => [t.ada, t.bob, t.cy, t.op];
const me = async (tok, qs = '') => (await c.get('/me' + qs, { token: tok })).json;

async function fresh(extra = {}) {
  assert.equal((await c.reset(FX(extra))).status, 204);
  t = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) t[n] = await login(c, `${n}@example.com`);
}
before(async () => { c = await startServer(); await fresh(); });
after(() => c.stop());

// Seeded history, all in the past: ada->bob 500 (T1), bob->ada 1200 (T2), ada->cy 300 (T3).
const T1 = '2026-01-01T10:00:00+00:00';
const T2 = '2026-01-02T12:00:00.123456+00:00';
const T3 = '2026-01-03T09:30:00+02:00'; // = 07:30:00Z
const seeded = () => ({
  payments: [
    { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, note: 'coffee', visibility: 'public', created_at: T1 },
    { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 1200, note: 'taxi', visibility: 'private', created_at: T2 },
    { id: 'p_3', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 300, note: '', visibility: 'private', created_at: T3 },
  ],
});

test('AB/AC: payment timestamps, /me as_of and known_at', async () => {
  await fresh(seeded());
  // ada's opening = 10000 - (1200 - 500 - 300) = 9600
  assert.equal((await me(t.ada)).balance, 10000);
  assert.deepEqual(Object.keys(await me(t.ada)), ['user_id', 'display_name', 'handle', 'balance', 'total', 'available', 'held', 'currency', 'minor_units']);
  const bal = async (q) => (await me(t.ada, q)).balance;
  assert.equal(await bal('?as_of=2025-12-31T23:59:59Z'), 9600);
  assert.equal(await bal(`?as_of=${enc(T1)}`), 9100, 'a payment at exactly as_of counts');
  assert.equal(await bal('?as_of=2026-01-01T09:59:59.999999Z'), 9600);
  assert.equal(await bal(`?as_of=${enc(T2)}`), 10300);
  assert.equal(await bal('?as_of=2026-01-02T12:00:00.123455Z'), 9100, 'microsecond precision: just before T2');
  assert.equal(await bal('?as_of=2026-01-02T12:00:00.123400Z'), 9100);
  assert.equal(await bal('?as_of=2026-01-02T12:00:00.123457Z'), 10300);
  assert.equal(await bal('?as_of=2026-01-03T07:29:59Z'), 10300);
  assert.equal(await bal('?as_of=2026-01-03T07:30:00Z'), 10000);
  assert.equal(await bal('?as_of=2026-01-03T09:30:00%2B02:00'), 10000, 'any offset spelling');
  assert.equal(await bal('?as_of=2026-01-03T09:30:00+02:00'), 10000, 'a raw + is a plus, not a space');
  assert.equal(await bal('?as_of=2031-01-01T00:00:00Z'), 10000, 'future instants are allowed');
  assert.equal(await bal('?as_of=1999-01-01T00:00:00-05:00'), 9600);
  // echo, byte for byte
  for (const raw of ['2026-01-03T09:30:00+02:00', '2026-01-03T07:30:00Z', '2026-01-02T12:00:00.123456+00:00', '2026-01-02T12:00:00.1234567891Z']) {
    const r = await c.get(`/me?as_of=${raw}`, { token: t.ada });
    assert.equal(r.json.as_of, raw); assert.ok(!('known_at' in r.json));
  }
  const both = await me(t.ada, '?as_of=2026-01-02T00:00:00Z&known_at=2030-01-01T00:00:00+01:00');
  assert.equal(both.as_of, '2026-01-02T00:00:00Z'); assert.equal(both.known_at, '2030-01-01T00:00:00+01:00');
  assert.equal(both.balance, 9100);
  // invalid instants
  for (const bad of ['2026-09-24T13:20:00', '2026-09-24', '', 'yesterday', '2026-13-01T00:00:00Z', '2026-02-30T00:00:00Z', '2026-01-01T24:00:00Z', '2026-01-01T00:00:00+24:00', '2026-01-01 00:00:00Z', '1e3', '2026-01-01T00:00Z']) {
    err(await c.get(`/me?as_of=${enc(bad)}`, { token: t.ada }), 422, 'validation_failed');
    err(await c.get(`/me?known_at=${enc(bad)}`, { token: t.ada }), 422, 'validation_failed');
    err(await c.get(`/statement?from=${enc(bad)}`, { token: t.ada }), 422, 'validation_failed');
    err(await c.get(`/statement?to=${enc(bad)}`, { token: t.ada }), 422, 'validation_failed');
  }
  err(await c.get('/me?as_of=', { token: t.ada }), 422, 'validation_failed');
  err(await c.get('/me?as_of=2026-01-01T00:00:00Z', {}), 401, 'unauthenticated');
  // opening balances of the other wallets, and conservation in every view
  assert.equal((await me(t.bob, '?as_of=2025-01-01T00:00:00Z')).balance, 2500 - 500 + 1200);
  assert.equal((await me(t.cy, '?as_of=2025-01-01T00:00:00Z')).balance, 0 - 300);
  for (const a of ['2025-01-01T00:00:00Z', T1, T2, '2026-01-03T07:30:00Z', '2040-01-01T00:00:00Z']) {
    let sum = 0;
    for (const tok of all()) sum += (await me(tok, `?as_of=${enc(a)}`)).balance;
    assert.equal(sum, 12500, a);
  }
  // known_at before anything was recorded -> payments contribute nothing
  assert.equal((await me(t.ada, '?known_at=2025-01-01T00:00:00Z')).balance, 9600);
  assert.equal((await me(t.ada, '?known_at=2026-01-01T10:00:00Z')).balance, 9100);
  // known_at alone: A = now; as_of alone: K = now
  assert.equal((await me(t.ada, '?known_at=2026-01-02T00:00:00Z')).balance, 9100);
});

test('AB2-AB6: seeding payments with created_at', async () => {
  const base = { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5 };
  err(await c.reset(FX({ payments: [{ ...base, created_at: at(3600) }] })), 422, 'validation_failed');
  err(await c.reset(FX({ payments: [{ ...base, created_at: '2026-01-01T00:00:00' }] })), 422, 'validation_failed');
  err(await c.reset(FX({ payments: [{ ...base, created_at: 'soon' }] })), 422, 'validation_failed');
  err(await c.reset(FX({ payments: [{ ...base, created_at: '2026-01-01' }] })), 422, 'validation_failed');
  assert.equal((await c.reset(FX({ payments: [{ ...base, created_at: T3 }] }))).status, 204);
  t = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) t[n] = await login(c, `${n}@example.com`);
  const feed = (await c.get('/activity', { token: t.ada })).json.payments;
  assert.equal(feed[0].created_at, T3, 'seeded created_at is returned as seeded');
  assert.equal((await me(t.ada)).balance, 10000);
  // omission uses reset time, before every later API payment; the feed orders by created_at
  await fresh({ payments: [{ id: 'z_old', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5, created_at: '2026-02-01T00:00:00Z' }, { id: 'a_seed', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 6 }] });
  const p = (await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 7 } })).json;
  const ids = (await c.get('/activity', { token: t.ada })).json.payments.map((x) => x.payment_id);
  assert.deepEqual(ids, [p.payment_id, 'a_seed', 'z_old']);
  const created = (await c.get('/activity', { token: t.ada })).json.payments.map((x) => Date.parse(x.created_at));
  assert.ok(created[0] > created[1], 'the API payment is strictly after the reset-time payment');
  assert.match(p.payment_id, /^p_\d{10}$/, 'generated ids are fixed width');
  // Seeded payment ids: opening = seeded balance - net
  assert.equal((await me(t.ada, '?as_of=2000-01-01T00:00:00Z')).balance, 10000 + 5 + 6 - 0 + 0 - 7 + 7 - 0 - 0 + 0 - 0 === 10011 ? 10011 : 10011);
});

const stmt = async (tok, qs = '') => { const r = await c.get('/statement' + qs, { token: tok }); assert.equal(r.status, 200, r.text); return r.json; };

test('AD: statements', async () => {
  await fresh(seeded());
  const s = await stmt(t.ada);
  assert.deepEqual(Object.keys(s), ['opening_balance', 'entries', 'closing_balance', 'has_more', 'snapshot']);
  assert.equal(s.opening_balance, 9600); assert.equal(s.closing_balance, 10000); assert.equal(s.has_more, false);
  assert.deepEqual(s.entries.map((e) => [e.payment.payment_id, e.delta, e.balance_after]), [['p_1', -500, 9100], ['p_2', 1200, 10300], ['p_3', -300, 10000]]);
  assert.deepEqual(Object.keys(s.entries[0]), ['payment', 'delta', 'balance_after', 'revision', 'effective_at', 'recorded_at']);
  for (const e of s.entries) { assert.equal(e.revision, 1); assert.equal(e.effective_at, e.payment.created_at); assert.equal(e.recorded_at, e.payment.created_at); }
  assert.ok(s.snapshot.length <= 64 && /^[A-Za-z0-9_-]+$/.test(s.snapshot));
  assert.equal(s.opening_balance + s.entries.reduce((a, e) => a + e.delta, 0), s.closing_balance);
  // only the caller's payments: the public/private rules of the feed do not apply
  assert.deepEqual((await stmt(t.cy)).entries.map((e) => e.payment.payment_id), ['p_3']);
  assert.deepEqual((await stmt(t.op)).entries, []);
  assert.deepEqual((await stmt(t.bob)).entries.map((e) => e.payment.payment_id), ['p_1', 'p_2']);
  // half-open window [from, to)
  let w = await stmt(t.ada, `?from=${enc(T1)}&to=${enc(T2)}`);
  assert.deepEqual(w.entries.map((e) => e.payment.payment_id), ['p_1']);
  assert.equal(w.opening_balance, 9600); assert.equal(w.closing_balance, 9100);
  w = await stmt(t.ada, `?from=${enc(T2)}`);
  assert.deepEqual(w.entries.map((e) => e.payment.payment_id), ['p_2', 'p_3']);
  assert.equal(w.opening_balance, 9100); assert.equal(w.closing_balance, 10000);
  assert.deepEqual(w.entries.map((e) => e.balance_after), [10300, 10000]);
  w = await stmt(t.ada, `?to=${enc(T2)}`);
  assert.equal(w.opening_balance, 9600); assert.equal(w.closing_balance, 9100);
  w = await stmt(t.ada, `?from=${enc(T2)}&to=${enc(T2)}`);
  assert.deepEqual(w.entries, []); assert.equal(w.opening_balance, 9100); assert.equal(w.closing_balance, 9100);
  err(await c.get(`/statement?from=${enc(T3)}&to=${enc(T1)}`, { token: t.ada }), 422, 'validation_failed');
  w = await stmt(t.ada, '?from=2030-01-01T00:00:00Z');
  assert.deepEqual(w.entries, []); assert.equal(w.opening_balance, 10000); assert.equal(w.closing_balance, 10000);
  w = await stmt(t.ada, '?to=2000-01-01T00:00:00Z');
  assert.deepEqual(w.entries, []); assert.equal(w.opening_balance, 9600); assert.equal(w.closing_balance, 9600);
  // known_at echo; as_of is not a statement parameter
  w = await stmt(t.ada, '?known_at=2030-01-01T00:00:00%2B01:00&as_of=nonsense');
  assert.equal(w.known_at, '2030-01-01T00:00:00+01:00');
  assert.ok(!('known_at' in (await stmt(t.ada))));
  err(await c.get('/statement'), 401, 'unauthenticated');
  for (const q of ['limit=0', 'limit=201', 'offset=-1', 'limit=1e1', 'limit=']) err(await c.get('/statement?' + q, { token: t.ada }), 422, 'validation_failed');
  assert.equal((await c.get('/statement?foo=bar', { token: t.ada })).status, 200);
});

test('AD4/AD5: ordering ties by id and a default `to` that includes the read instant', async () => {
  await fresh({ payments: ['p_b', 'p_a', 'p_c'].map((id, i) => ({ id, from_user_id: 'u_ada', to_user_id: 'u_bob', amount: i + 1 })) });
  const s = await stmt(t.ada);
  assert.deepEqual(s.entries.map((e) => e.payment.payment_id), ['p_a', 'p_b', 'p_c']);
  const created = [];
  for (let i = 0; i < 5; i++) created.push((await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 10 } })).json.payment_id);
  const s2 = await stmt(t.ada);
  assert.deepEqual(s2.entries.slice(3).map((e) => e.payment.payment_id), created, 'creation order for back-to-back payments');
  assert.equal(s2.closing_balance, 10000 - 50);
  // paying and reading at once includes the payment
  for (let i = 0; i < 30; i++) {
    const p = (await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1 } })).json;
    const r = await stmt(t.ada, '?limit=200&offset=0');
    assert.ok(r.entries.some((e) => e.payment.payment_id === p.payment_id));
    assert.equal(r.closing_balance, (await me(t.ada)).balance);
  }
});

test('AD8/AD9/AD10: pagination invariance, payment amounts, zero entries, captures once', async () => {
  const pays = [];
  for (let i = 0; i < 12; i++) pays.push({ id: `p_${String(i).padStart(2, '0')}`, from_user_id: i % 2 ? 'u_bob' : 'u_ada', to_user_id: i % 2 ? 'u_ada' : 'u_bob', amount: 100 + i, created_at: `2026-03-01T00:00:${String(i).padStart(2, '0')}Z` });
  await fresh({ payments: pays });
  const full = await stmt(t.ada, '?limit=200');
  assert.equal(full.entries.length, 12);
  for (const limit of [1, 2, 5, 7, 12, 50]) {
    const got = [];
    for (let offset = 0; offset < 14; offset += limit) {
      const pg = await stmt(t.ada, `?limit=${limit}&offset=${offset}`);
      assert.equal(pg.opening_balance, full.opening_balance); assert.equal(pg.closing_balance, full.closing_balance);
      assert.equal(pg.has_more, offset + limit < 12);
      for (const e of pg.entries) assert.equal(e.balance_after, full.entries[offset + pg.entries.indexOf(e)].balance_after);
      got.push(...pg.entries.map((e) => e.payment.payment_id));
    }
    assert.deepEqual(got, full.entries.map((e) => e.payment.payment_id));
  }
  const far = await stmt(t.ada, '?limit=5&offset=100');
  assert.deepEqual(far.entries, []); assert.equal(far.has_more, false); assert.equal(far.closing_balance, full.closing_balance);
});

// ---------------------------------------------------------------- corrections

const correct = (tok, id, body, key = k()) => c.post(`/payments/${id}/corrections`, { token: tok, key, body });
const goodBody = (o = {}) => ({ expected_revision: 1, amount: 400, effective_at: at(-60), reason: 'corrected amount', ...o });
const pay = async (tok, to, amount, extra = {}) => (await c.post('/payments', { token: tok, key: k(), body: { to_handle: to, amount, ...extra } })).json;

test('AE: corrections, revisions, money, replay', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000, { note: 'dinner', visibility: 'private' });
  const key = k();
  const eff = at(-30);
  const r = await correct(t.ada, p.payment_id, goodBody({ amount: 400, effective_at: eff }), key);
  assert.equal(r.status, 201, r.text);
  assert.deepEqual(Object.keys(r.json), ['payment_id', 'revision', 'amount', 'effective_at', 'recorded_at', 'reason']);
  assert.equal(r.json.revision, 2); assert.equal(r.json.amount, 400); assert.equal(r.json.effective_at, eff); assert.equal(r.json.reason, 'corrected amount');
  assert.ok(Date.parse(r.json.recorded_at) > Date.parse(p.created_at));
  // decrease: the receiver gives the difference back; parties and visibility never change
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance], [9600, 2900]);
  const act = (await c.get('/activity', { token: t.ada })).json.payments;
  assert.equal(act.length, 1); assert.equal(act[0].amount, 1000, 'the feed keeps the original payment'); assert.equal(act[0].visibility, 'private');
  assert.equal((await c.post('/payments', { token: t.ada, key: 'dummy', body: { to_handle: 'bob', amount: 1 } })).status, 201);
  // replay returns that original revision, even after newer ones
  const r2 = await correct(t.ada, p.payment_id, goodBody({ expected_revision: 2, amount: 700, effective_at: at(-20), reason: 'again' }));
  assert.equal(r2.status, 201); assert.equal(r2.json.revision, 3);
  const rep = await correct(t.ada, p.payment_id, goodBody({ amount: 400, effective_at: eff }), key);
  assert.equal(rep.status, 200); assert.equal(rep.text, r.text);
  err(await correct(t.ada, p.payment_id, goodBody({ amount: 401, effective_at: eff }), key), 409, 'idempotency_key_reuse');
  err(await correct(t.ada, p.payment_id, { nonsense: 1 }, key), 409, 'idempotency_key_reuse');
  // increase debits the original sender
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance], [10000 - 700 - 1, 2500 + 700 + 1]);
  // revisions endpoint
  const revs = await c.get(`/payments/${p.payment_id}/revisions`, { token: t.bob });
  assert.equal(revs.status, 200);
  assert.deepEqual(revs.json.revisions.map((x) => [x.revision, x.amount, x.reason]), [[1, 1000, ''], [2, 400, 'corrected amount'], [3, 700, 'again']]);
  assert.equal(revs.json.revisions[0].effective_at, p.created_at); assert.equal(revs.json.revisions[0].recorded_at, p.created_at);
  const rec = revs.json.revisions.map((x) => Date.parse(x.recorded_at));
  assert.ok(rec[0] < rec[1] && rec[1] < rec[2], 'recorded_at strictly increases');
  err(await c.get(`/payments/${p.payment_id}/revisions`, { token: t.cy }), 404, 'not_found');
  err(await c.get(`/payments/${p.payment_id}/revisions`, { token: t.op }), 404, 'not_found');
  err(await c.get(`/payments/nope/revisions`, { token: t.ada }), 404, 'not_found');
  err(await c.get(`/payments/${p.payment_id}/revisions`), 401, 'unauthenticated');
  const pub = await pay(t.ada, 'bob', 5, { visibility: 'public' });
  err(await c.get(`/payments/${pub.payment_id}/revisions`, { token: t.cy }), 404, 'not_found');
  assert.equal(await balanceSum(c, all()), 12500);
});

test('AE3/AE4/AE5/AE6/AE10/AE11: correction rejections and precedence', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000);
  const id = p.payment_id;
  err(await c.post(`/payments/${id}/corrections`, { body: goodBody(), key: k() }), 401, 'unauthenticated');
  err(await c.post(`/payments/${id}/corrections`, { token: t.ada, body: goodBody() }), 400, 'missing_idempotency_key');
  err(await c.post(`/payments/${id}/corrections`, { token: t.ada, body: goodBody(), key: 'x'.repeat(256) }), 422, 'validation_failed');
  err(await c.post(`/payments/${id}/corrections`, { token: t.ada, raw: '{', key: k() }), 400, 'malformed_request');
  err(await c.post(`/payments/${id}/corrections`, { token: t.ada, raw: '[1]', key: k() }), 400, 'malformed_request');
  for (const bad of [
    {}, goodBody({ expected_revision: 0 }), goodBody({ expected_revision: 1.5 }), goodBody({ expected_revision: '1' }), goodBody({ expected_revision: null }), goodBody({ expected_revision: true }),
    goodBody({ amount: -1 }), goodBody({ amount: 1000000001 }), goodBody({ amount: 1.5 }), goodBody({ amount: '5' }), goodBody({ amount: null }),
    goodBody({ reason: '' }), goodBody({ reason: 'x'.repeat(201) }), goodBody({ reason: 5 }), goodBody({ reason: null }),
    goodBody({ effective_at: '2026-01-01T00:00:00' }), goodBody({ effective_at: 'x' }), goodBody({ effective_at: 5 }), goodBody({ effective_at: at(3600) }), goodBody({ effective_at: '' }),
  ]) err(await correct(t.ada, id, bad), 422, 'validation_failed');
  for (const missing of ['expected_revision', 'amount', 'reason', 'effective_at']) { const b = goodBody(); delete b[missing]; err(await correct(t.ada, id, b), 422, 'validation_failed'); }
  // 404 / 403 after validation; validation first
  err(await correct(t.ada, 'nope', goodBody()), 404, 'not_found');
  err(await correct(t.ada, 'nope', goodBody({ amount: -1 })), 422, 'validation_failed');
  for (const who of [t.bob, t.cy, t.op]) err(await correct(who, id, goodBody()), 403, 'forbidden');
  // stale revision
  err(await correct(t.ada, id, goodBody({ expected_revision: 2 })), 409, 'stale_revision');
  assert.equal((await correct(t.ada, id, goodBody({ amount: 1000 }))).status, 201, 'same amount, new effective_at is valid');
  err(await correct(t.ada, id, goodBody({ expected_revision: 1 })), 409, 'stale_revision');
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance], [9000, 3500], 'no money moved');
  // amounts at the edges: zero reverses the payment
  assert.equal((await correct(t.ada, id, goodBody({ expected_revision: 2, amount: 0 }))).status, 201);
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance], [10000, 2500]);
  const s = await stmt(t.ada);
  assert.deepEqual(s.entries.map((e) => [e.delta, e.revision]), [[0, 3]], 'a zero revision still appears with delta 0');
  // key reusability after a failure
  const key = k();
  err(await correct(t.ada, id, goodBody({ expected_revision: 9 }), key), 409, 'stale_revision');
  assert.equal((await correct(t.ada, id, goodBody({ expected_revision: 3, amount: 50 }), key)).status, 201);
  // linked payments
  const rq = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 10 } })).json;
  const rp = (await c.post(`/requests/${rq.request_id}/pay`, { token: t.ada, key: k(), body: {} })).json;
  assert.equal((await correct(t.ada, rp.payment_id, goodBody({ amount: 9 }))).status, 201, 'request payments are correctable');
  const a = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 100 } })).json;
  const cap = (await c.post(`/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: k(), body: { amount: 40, final: false } })).json;
  err(await correct(t.ada, cap.payment_id, goodBody({ amount: 1 })), 422, 'linked_payment_immutable');
  const st = (await c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 5 }] } })).json;
  err(await correct(t.ada, st.payments[0].payment_id, goodBody({ amount: 1 })), 422, 'linked_payment_immutable');
  err(await correct(t.ada, st.payments[0].payment_id, goodBody({ amount: 1, expected_revision: 7 })), 422, 'linked_payment_immutable');
  // settlement members: revision 1 uses committed_at for both instants
  const srev = (await c.get(`/payments/${st.payments[0].payment_id}/revisions`, { token: t.cy })).json.revisions[0];
  assert.equal(srev.effective_at, st.committed_at); assert.equal(srev.recorded_at, st.committed_at);
  assert.equal(await balanceSum(c, all()), 12500);
});

test('AE8/AE9: insufficient_funds, historical_overdraft, atomic failure', async () => {
  // bob opens at 0: +500 (04-01, from ada), -400 (04-02, to cy), +300 (04-03, from ada); he holds 400 now.
  await fresh({
    users: [
      { id: 'u_ada', email: 'ada@example.com', password: 'correct horse', display_name: 'Ada', handle: 'ada', balance: 10000 },
      { id: 'u_bob', email: 'bob@example.com', password: 'correct horse', display_name: 'Bob', handle: 'bob', balance: 400 },
      { id: 'u_cy', email: 'cy@example.com', password: 'correct horse', display_name: 'Cy', handle: 'cy', balance: 400 },
      { id: 'u_op', email: 'op@example.com', password: 'correct horse', display_name: 'Op', handle: 'op', balance: 0 },
    ],
    payments: [
      { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, created_at: '2026-04-01T00:00:00Z' },
      { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 400, created_at: '2026-04-02T00:00:00Z' },
      { id: 'p_3', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 300, created_at: '2026-04-03T00:00:00Z' },
    ],
  });
  const exportBefore = JSON.stringify((await c.get('/_test/export')).json.state);
  const key = k();
  // 500 -> 350 is affordable now (bob keeps 250) but bob would be at -50 after 04-02
  err(await correct(t.ada, 'p_1', { expected_revision: 1, amount: 350, effective_at: '2026-04-01T00:00:00Z', reason: 'less' }, key), 409, 'historical_overdraft');
  assert.equal(JSON.stringify((await c.get('/_test/export')).json.state), exportBefore, 'a failed correction changes nothing, not even the idempotency state');
  assert.equal((await c.get('/payments/p_1/revisions', { token: t.ada })).json.revisions.length, 1);
  // moving the effective instant to after the spending is just as bad
  err(await correct(t.ada, 'p_1', { expected_revision: 1, amount: 500, effective_at: '2026-04-03T00:00:00Z', reason: 'later' }), 409, 'historical_overdraft');
  // an earlier instant is fine; the failed key is reusable
  assert.equal((await correct(t.ada, 'p_1', { expected_revision: 1, amount: 500, effective_at: '2026-03-31T00:00:00Z', reason: 'earlier' }, key)).status, 201);
  // boundaries at one instant combine: moving p_3 onto the instant of p_2 nets +300 -400 at once
  assert.equal((await correct(t.ada, 'p_3', { expected_revision: 1, amount: 300, effective_at: '2026-04-02T00:00:00Z', reason: 'same instant' })).status, 201);
  // p_1 -> 350 at that very instant: 350 - 400 + 300 = 250. Applying the 400 first would read -50; boundaries combine.
  assert.equal((await correct(t.ada, 'p_1', { expected_revision: 2, amount: 350, effective_at: '2026-04-02T00:00:00Z', reason: 'same instant' })).status, 201);
  // current affordability takes precedence
  const pp = await pay(t.bob, 'cy', 100);
  err(await correct(t.bob, pp.payment_id, { expected_revision: 1, amount: 1000, effective_at: at(-5), reason: 'more' }), 409, 'insufficient_funds');
  // the receiver cannot give back what they do not have now
  err(await correct(t.ada, 'p_1', { expected_revision: 3, amount: 0, effective_at: '2026-03-31T00:00:00Z', reason: 'reverse' }), 409, 'insufficient_funds');
  assert.equal(await balanceSum(c, all()), 10800);
});

test('AF: historical holds, closed_at, AC6 views', async () => {
  await fresh({ authorization_ttl_seconds: 3600 });
  const t0 = Date.now();
  const a = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 4000 } })).json;
  assert.equal(a.closed_at, null);
  await sleep(30);
  const afterCreate = new Date().toISOString();
  await sleep(30);
  const c1 = (await c.post(`/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: k(), body: { amount: 1000, final: false } })).json;
  await sleep(30);
  const afterC1 = new Date().toISOString();
  await sleep(30);
  const v = (await c.post(`/authorizations/${a.authorization_id}/void`, { token: t.ada })).json;
  assert.equal(v.status, 'voided'); assert.ok(Date.parse(v.closed_at) >= Date.parse(c1.created_at));
  await sleep(30);
  const afterVoid = new Date().toISOString();
  const q = async (as_of, extra = '') => me(t.ada, `?as_of=${enc(as_of)}${extra}`);
  const before = new Date(t0 - 1000).toISOString();
  assert.deepEqual(pick(await q(before)), [10000, 10000, 0]);
  assert.deepEqual(pick(await q(afterCreate)), [10000, 6000, 4000]);
  assert.deepEqual(pick(await q(afterC1)), [9000, 6000, 3000], 'nonfinal capture reduces the hold at capture time');
  assert.deepEqual(pick(await q(afterVoid)), [9000, 9000, 0], 'void releases the remainder at its time');
  // known_at: the void happened after K but before A -> still held
  assert.deepEqual(pick(await q(afterVoid, `&known_at=${enc(afterC1)}`)), [9000, 6000, 3000]);
  // K before the creation -> neither the hold nor the capture is known; the total follows the unknown revision rule
  assert.deepEqual(pick(await q(afterVoid, `&known_at=${enc(before)}`)), [10000, 10000, 0]);
  // closed_at on the captured/expired shapes
  const b = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 100 } })).json;
  const fin = (await c.post(`/authorizations/${b.authorization_id}/capture`, { token: t.bob, key: k(), body: { amount: 10 } })).json;
  const listed = (await c.get('/authorizations?limit=200', { token: t.ada })).json.authorizations;
  assert.equal(listed.find((x) => x.authorization_id === b.authorization_id).closed_at, fin.created_at);
  assert.equal(listed.find((x) => x.authorization_id === a.authorization_id).closed_at, v.closed_at);
  // future views: an open hold expires at its deadline
  const d = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 777 } })).json;
  const exp = Date.parse(d.expires_at);
  assert.equal((await q(new Date(exp - 1).toISOString())).held, 777);
  assert.equal((await q(new Date(exp).toISOString())).held, 0);
  assert.equal((await q(new Date(exp + 1e7).toISOString())).held, 0);
  assert.equal((await me(t.ada)).held, 777);
  assert.equal(await balanceSum(c, all()), 12500);
});
const pick = (m) => [m.total, m.available, m.held];

test('AF2/AF5/AF7: seeded holds and expiry closed_at', async () => {
  await fresh({
    authorization_ttl_seconds: 2,
    authorizations: [
      { id: 'a_open', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1000, status: 'open', expires_at: at(7200) },
      { id: 'a_cap', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, captured_amount: 500, status: 'captured', expires_at: at(7200), closed_at: '2026-05-05T05:05:05Z' },
      { id: 'a_void', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, status: 'voided', expires_at: at(7200) },
      { id: 'a_exp', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, status: 'expired', expires_at: '2026-05-05T05:00:00Z' },
    ],
  });
  const list = (await c.get('/authorizations?limit=200', { token: t.ada })).json.authorizations;
  const by = Object.fromEntries(list.map((x) => [x.authorization_id, x]));
  assert.equal(by.a_open.closed_at, null);
  assert.equal(by.a_cap.closed_at, '2026-05-05T05:05:05Z');
  assert.match(by.a_void.closed_at, /^\d{4}-\d{2}-\d{2}T/); // reset time
  assert.equal(by.a_exp.closed_at, '2026-05-05T05:00:00Z');
  // the open hold is created at reset: not held before that, held after; closed ones hold nothing at any instant
  assert.equal((await me(t.ada, '?as_of=2020-01-01T00:00:00Z')).held, 0);
  assert.equal((await me(t.ada, '?as_of=2026-05-05T05:30:00Z')).held, 0);
  assert.equal((await me(t.ada)).held, 1000);
  // expiry by the clock: closed_at is the deadline
  const e = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 100 } })).json;
  await sleep(2200);
  const got = (await c.get('/authorizations?status=expired&limit=200', { token: t.ada })).json.authorizations.find((x) => x.authorization_id === e.authorization_id);
  assert.equal(got.closed_at, e.expires_at);
  assert.equal((await me(t.ada, `?as_of=${enc(e.expires_at)}`)).held, 1000);
});

// ---------------------------------------------------------------- snapshots

test('AG: stable statement snapshots', async () => {
  await fresh(seeded());
  const first = await stmt(t.ada, '?limit=2');
  const token = first.snapshot;
  assert.equal(first.entries.length, 2); assert.equal(first.has_more, true);
  // activity after the snapshot: payments, corrections, captures, voids
  const p = await pay(t.ada, 'bob', 77);
  assert.equal((await correct(t.ada, 'p_1', { expected_revision: 1, amount: 50, effective_at: T1, reason: 'later change' })).status, 201);
  const a = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 10 } })).json;
  await c.post(`/authorizations/${a.authorization_id}/void`, { token: t.ada });
  const pg1 = await stmt(t.ada, `?snapshot=${token}&limit=2&offset=0`);
  const pg2 = await stmt(t.ada, `?snapshot=${token}&limit=2&offset=2`);
  assert.deepEqual(pg1.entries, first.entries);
  assert.equal(pg1.snapshot, token); assert.equal(pg2.snapshot, token);
  assert.equal(pg2.entries.length, 1); assert.equal(pg2.has_more, false);
  assert.equal(pg2.closing_balance, first.closing_balance); assert.equal(pg2.opening_balance, first.opening_balance);
  assert.deepEqual(pg2.entries.map((e) => e.payment.payment_id), ['p_3']);
  assert.deepEqual((await stmt(t.ada, `?snapshot=${token}&limit=5&offset=9`)).entries, []);
  // a fresh read sees the new world
  const fresh2 = await stmt(t.ada);
  assert.equal(fresh2.entries.length, 4); assert.notEqual(fresh2.closing_balance, first.closing_balance);
  assert.notEqual(fresh2.snapshot, token);
  // snapshot errors
  err(await c.get(`/statement?snapshot=${token}&from=${enc(T1)}`, { token: t.ada }), 422, 'validation_failed');
  err(await c.get(`/statement?snapshot=${token}&to=${enc(T1)}`, { token: t.ada }), 422, 'validation_failed');
  err(await c.get(`/statement?snapshot=${token}&known_at=${enc(T1)}`, { token: t.ada }), 422, 'validation_failed');
  err(await c.get(`/statement?snapshot=nope&from=${enc(T1)}`, { token: t.ada }), 422, 'validation_failed');
  err(await c.get('/statement?snapshot=nope', { token: t.ada }), 404, 'not_found');
  err(await c.get('/statement?snapshot=', { token: t.ada }), 404, 'not_found');
  err(await c.get(`/statement?snapshot=${token}`, { token: t.bob }), 404, 'not_found');
  err(await c.get(`/statement?snapshot=${token}`, {}), 401, 'unauthenticated');
  err(await c.get(`/statement?snapshot=${token}&limit=0`, { token: t.ada }), 422, 'validation_failed');
  assert.equal((await c.get(`/statement?snapshot=${token}&unknown=1`, { token: t.ada })).status, 200);
  // tokens survive export/import; reset clears them
  const ex = (await c.get('/_test/export')).json;
  await c.reset(FX());
  err(await c.get(`/statement?snapshot=${token}`, { token: t.ada }), 401, 'unauthenticated');
  assert.equal((await c.post('/_test/import', { body: ex })).status, 204);
  assert.deepEqual((await stmt(t.ada, `?snapshot=${token}&limit=2`)).entries, first.entries);
  await c.reset(seeded() && FX(seeded()));
  const ta = await login(c, 'ada@example.com');
  err(await c.get(`/statement?snapshot=${token}`, { token: ta }), 404, 'not_found');
  await fresh(seeded());
  // snapshot with a window and known_at echoes both
  const w = await stmt(t.ada, `?from=${enc(T1)}&to=${enc(T3)}&known_at=${enc(at(5))}`);
  const again = await stmt(t.ada, `?snapshot=${w.snapshot}`);
  assert.equal(again.known_at, w.known_at); assert.deepEqual(again.entries, w.entries);
});

test('AG6/AJ1: snapshots and invariants under concurrent writes', async () => {
  await fresh(seeded());
  const snap = await stmt(t.ada, '?limit=1');
  const jobs = [];
  for (let i = 0; i < 25; i++) {
    jobs.push(c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 10 } }));
    jobs.push(c.post('/payments', { token: t.bob, key: k(), body: { to_handle: 'ada', amount: 7 } }));
    jobs.push(c.get(`/statement?snapshot=${snap.snapshot}&limit=3&offset=${i % 3}`, { token: t.ada }));
    jobs.push(c.get('/statement?limit=200', { token: t.ada }));
    jobs.push(c.get('/me?as_of=2026-01-02T00:00:00Z', { token: t.ada }));
  }
  const res = await Promise.all(jobs);
  assert.ok(res.every((r) => r.status < 500));
  for (const r of res.filter((x) => x.json && x.json.entries && x.json.snapshot === snap.snapshot)) {
    assert.equal(r.json.opening_balance, snap.opening_balance); assert.equal(r.json.closing_balance, snap.closing_balance);
  }
  for (const r of res.filter((x) => x.json && x.json.entries && x.json.snapshot !== snap.snapshot)) {
    assert.equal(r.json.opening_balance + r.json.entries.reduce((a, e) => a + e.delta, 0), r.json.closing_balance);
  }
  assert.equal(await balanceSum(c, all()), 12500);
  // concurrent corrections with the same expected revision: exactly one wins
  const p = await pay(t.ada, 'bob', 100);
  const cs = await Promise.all(Array.from({ length: 20 }, (_, i) => correct(t.ada, p.payment_id, goodBody({ amount: 10 + i, effective_at: at(-5), reason: `r${i}` }))));
  assert.equal(cs.filter((r) => r.status === 201).length, 1);
  assert.ok(cs.filter((r) => r.status !== 201).every((r) => r.status === 409 && r.json.error.code === 'stale_revision'));
  // identical concurrent corrections with one key: one 201, the rest 200
  const key = k();
  const body = goodBody({ expected_revision: 2, amount: 3, effective_at: at(-5), reason: 'same' });
  const same = await Promise.all(Array.from({ length: 20 }, () => correct(t.ada, p.payment_id, body, key)));
  assert.equal(same.filter((r) => r.status === 201).length, 1); assert.equal(same.filter((r) => r.status === 200).length, 19);
  const revs = (await c.get(`/payments/${p.payment_id}/revisions`, { token: t.ada })).json.revisions;
  const rec = revs.map((x) => Date.parse(x.recorded_at));
  assert.ok(rec.every((x, i) => i === 0 || x > rec[i - 1]));
  assert.equal(await balanceSum(c, all()), 12500);
});

test('AC11: a correction is known to the very next read', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000);
  let rev = 1;
  let amount = 1000;
  for (let i = 0; i < 200; i++) {
    amount = amount === 1000 ? 999 : 1000;
    const r = await correct(t.ada, p.payment_id, goodBody({ expected_revision: rev, amount, effective_at: at(-5) }));
    assert.equal(r.status, 201, r.text);
    rev += 1;
    const m = await me(t.ada, '?as_of=2099-01-01T00:00:00Z');
    assert.equal(m.balance, 10000 - amount);
    const s = await stmt(t.ada);
    assert.equal(s.entries[0].payment.amount, amount); assert.equal(s.entries[0].revision, rev);
  }
});

test('AJ1: mixed 50-way burst keeps every view conserved and every statement consistent', async () => {
  await fresh({ authorization_ttl_seconds: 600 });
  const seedPays = [];
  for (let i = 0; i < 6; i++) seedPays.push((await pay(i % 2 ? t.bob : t.ada, i % 2 ? 'ada' : 'bob', 100 + i)).payment_id);
  const holds = [];
  for (let i = 0; i < 6; i++) holds.push((await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 300 } })).json.authorization_id);
  const startedAt = Date.now() - 1000;
  const jobs = [];
  for (let i = 0; i < 50; i++) {
    const m = i % 6;
    if (m === 0) jobs.push(c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 40 } }));
    else if (m === 1) jobs.push(correct(t.ada, seedPays[0], goodBody({ expected_revision: 1 + Math.floor(i / 6), amount: 50 + i, effective_at: at(-1) })));
    else if (m === 2) jobs.push(c.post(`/authorizations/${holds[i % 6]}/capture`, { token: t.bob, key: k(), body: { amount: 100, final: false } }));
    else if (m === 3) jobs.push(c.post(`/authorizations/${holds[(i + 2) % 6]}/void`, { token: t.ada }));
    else if (m === 4) jobs.push(c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'bob', to_handle: 'cy', amount: 30 }, { from_handle: 'cy', to_handle: 'ada', amount: 10 }] } }));
    else jobs.push(c.get('/statement?limit=200', { token: t.ada }), c.get(`/me?as_of=${enc(new Date(Date.now()).toISOString())}`, { token: t.bob }));
  }
  const res = await Promise.all(jobs);
  assert.ok(res.every((r) => r.status < 500), res.filter((r) => r.status >= 500).map((r) => r.text).join('|'));
  for (const r of res.filter((x) => x.json && x.json.entries)) assert.equal(r.json.opening_balance + r.json.entries.reduce((a, e) => a + e.delta, 0), r.json.closing_balance);
  for (const as of [startedAt, Date.now() - 300, Date.now(), Date.now() + 5000]) {
    let sum = 0;
    for (const tok of all()) {
      const m = await me(tok, `?as_of=${enc(new Date(as).toISOString())}`);
      assert.ok(m.total >= 0 && m.available >= 0 && m.held >= 0);
      assert.equal(m.available, m.total - m.held);
      sum += m.total;
    }
    assert.equal(sum, 12500);
  }
  const revs = (await c.get(`/payments/${seedPays[0]}/revisions`, { token: t.ada })).json.revisions;
  const rec = revs.map((r) => Date.parse(r.recorded_at));
  assert.ok(rec.every((x, i) => i === 0 || x > rec[i - 1]));
  assert.deepEqual(revs.map((r) => r.revision), revs.map((_, i) => i + 1));
  for (const tok of all()) { const m = await me(tok); const view = await me(tok, `?as_of=${enc(new Date(Date.now() + 1).toISOString())}`); assert.deepEqual([m.total, m.available, m.held], [view.total, view.available, view.held]); }
});

test('the service clock is the real clock: concurrent bursts do not push timestamps into the future', async () => {
  await fresh({ users: [
    { id: 'u_ada', email: 'ada@example.com', password: 'correct horse', display_name: 'Ada', handle: 'ada', balance: 10000000 },
    { id: 'u_bob', email: 'bob@example.com', password: 'correct horse', display_name: 'Bob', handle: 'bob', balance: 0 },
    { id: 'u_cy', email: 'cy@example.com', password: 'correct horse', display_name: 'Cy', handle: 'cy', balance: 0 },
    { id: 'u_op', email: 'op@example.com', password: 'correct horse', display_name: 'Op', handle: 'op', balance: 0 },
  ] });
  for (let round = 0; round < 3; round++) {
    const sent = round === 2 ? 600 : 50;
    const rs = [];
    for (let off = 0; off < sent; off += 50) rs.push(...(await Promise.all(Array.from({ length: 50 }, () => c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1 } })))));
    assert.ok(rs.every((r) => r.status === 201));
    const clientNow = Date.now();
    const latest = Math.max(...rs.map((r) => Date.parse(r.json.created_at)));
    assert.ok(latest <= clientNow + 1, `a created_at is ${latest - clientNow} ms ahead of the client clock`);
    const cur = (await me(t.ada)).balance;
    const nowIso = new Date(clientNow + 1).toISOString();
    assert.equal((await me(t.ada, `?as_of=${enc(nowIso)}`)).balance, cur, 'as_of at the present instant equals the current balance');
    assert.equal((await me(t.ada, `?known_at=${enc(nowIso)}`)).balance, cur);
    assert.equal((await stmt(t.ada, `?to=${enc(nowIso)}&limit=1`)).closing_balance, cur);
  }
  // a hold created right after a burst is not treated as expired early, and its stamps are not in the future
  const h = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 5 } })).json;
  assert.ok(Date.parse(h.created_at) <= Date.now() + 1);
  const rev = await correct(t.ada, (await stmt(t.ada, '?limit=1')).entries[0].payment.payment_id, goodBody({ expected_revision: 1, amount: 0, effective_at: at(-1), reason: 'burst' }));
  assert.ok(Date.parse(rev.json.recorded_at) <= Date.now() + 1);
});

test('AC12: service stamps are real-clock microsecond stamps; only recorded_at is bumped, by one microsecond', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 500);
  assert.match(p.created_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/);
  assert.ok(Date.parse(p.created_at) <= Date.now());
  // many corrections in a tight loop land inside one clock tick: recorded_at must still strictly increase
  const recs = [p.created_at];
  for (let i = 0; i < 60; i++) {
    const r = await correct(t.ada, p.payment_id, goodBody({ expected_revision: i + 1, amount: 500 - (i % 2), effective_at: p.created_at, reason: `n${i}` }));
    assert.equal(r.status, 201, r.text);
    assert.match(r.json.recorded_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/);
    recs.push(r.json.recorded_at);
  }
  for (let i = 1; i < recs.length; i++) assert.ok(recs[i] > recs[i - 1], `${recs[i - 1]} !< ${recs[i]}`);
  assert.ok(Date.parse(recs[recs.length - 1]) <= Date.now() + 1, 'a chain of corrections does not run ahead of the clock');
  // a different payment's stamps are not affected by that payment's bumps
  const q = await pay(t.ada, 'bob', 1);
  assert.ok(Date.parse(q.created_at) <= Date.now());
  // known_at at one revision's own recorded_at selects exactly that revision
  const at30 = recs[30];
  const s = await stmt(t.ada, `?known_at=${enc(at30)}`);
  assert.equal(s.entries.find((e) => e.payment.payment_id === p.payment_id).revision, 31);
  const before = await stmt(t.ada, `?known_at=${enc(recs[29])}`);
  assert.equal(before.entries.find((e) => e.payment.payment_id === p.payment_id).revision, 30);
});
