'use strict';

/**
 * Randomised check of the historical views against an independent model written here from the
 * specification: seeded payments at known past times, random corrections (accepted ones are
 * recorded with the service's recorded_at), then /me and /statement are compared with a
 * brute-force computation at random as_of / known_at / window instants.
 */

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const h = require('./helpers');
const { call } = h;

before(h.start);
after(h.stop);

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const BASE = Date.UTC(2026, 8, 1, 0, 0, 0);
const at = (hours) => new Date(BASE + hours * 3600000).toISOString().replace('Z', '+00:00');
const ms = (iso) => Date.parse(iso);

function expectedBalance(model, uid, asOfMs, knownMs) {
  let total = model.opening[uid];
  for (const p of model.payments) {
    const rev = [...p.revs].reverse().find((r) => knownMs === null || r.recorded <= knownMs);
    if (!rev || rev.effective > asOfMs) continue;
    if (p.from === uid) total -= rev.amount;
    if (p.to === uid) total += rev.amount;
  }
  return total;
}

function expectedStatement(model, uid, fromMs, toMs, knownMs) {
  let opening = model.opening[uid];
  const inWindow = [];
  for (const p of model.payments) {
    const rev = [...p.revs].reverse().find((r) => knownMs === null || r.recorded <= knownMs);
    if (!rev || (p.from !== uid && p.to !== uid)) continue;
    const delta = p.from === uid ? -rev.amount : rev.amount;
    if (fromMs !== null && rev.effective < fromMs) opening += delta;
    else if (rev.effective < toMs) inWindow.push({ id: p.id, rev, delta });
  }
  inWindow.sort((a, b) => a.rev.effective - b.rev.effective || (a.id < b.id ? -1 : 1));
  let running = opening;
  return {
    opening,
    entries: inWindow.map((e) => ({ id: e.id, revision: e.rev.n, amount: e.rev.amount, delta: e.delta, after: (running += e.delta) })),
    closing: running,
  };
}

for (const seed of [1, 2, 3, 4, 5, 6]) {
  test(`random histories agree with the model (seed ${seed})`, async () => {
    const r = rng(seed);
    const pick = (n) => Math.floor(r() * n);
    const handles = ['ada', 'bob', 'cy'];
    const uids = handles.map((x) => `u_${x}`);
    const model = { opening: Object.fromEntries(uids.map((u) => [u, 1000000])), payments: [] };
    const seeded = [];
    const count = 6 + pick(8);
    for (let i = 0; i < count; i++) {
      const from = pick(3);
      const to = (from + 1 + pick(2)) % 3;
      const t = pick(40) * 1.5 + (pick(2) ? 0.25 : 0); // hours, with deliberate ties
      const amount = 1 + pick(5000);
      const id = `m${i}`;
      seeded.push({ id, from_user_id: uids[from], to_user_id: uids[to], amount, note: id, visibility: 'public', created_at: at(t) });
      model.payments.push({ id, from: uids[from], to: uids[to], revs: [{ n: 1, amount, effective: ms(at(t)), recorded: ms(at(t)) }] });
    }
    const balances = { ...model.opening };
    for (const p of model.payments) { balances[p.from] -= p.revs[0].amount; balances[p.to] += p.revs[0].amount; }
    await h.reset({
      currency: 'EUR', minor_units: 2,
      users: handles.map((x, i) => ({ id: uids[i], email: `${x}@example.com`, password: 'correct horse', display_name: x, handle: x, balance: balances[uids[i]] })),
      payments: seeded,
    });
    const tokens = await h.tokens();
    const tok = (uid) => tokens[uid.slice(2)];
    const recordedTimes = [];
    for (let i = 0; i < 14; i++) {
      const p = model.payments[pick(model.payments.length)];
      const latest = p.revs[p.revs.length - 1];
      const body = { expected_revision: latest.n + (pick(8) === 0 ? 1 : 0), amount: pick(6000), effective_at: at(pick(60) * 1.25), reason: `r${i}` };
      const res = await call('POST', `/payments/${p.id}/corrections`, { token: tok(p.from), key: `k${seed}-${i}`, body });
      if (res.status === 201) {
        const rev = { n: res.body.revision, amount: res.body.amount, effective: ms(res.body.effective_at), recorded: ms(res.body.recorded_at) };
        assert.ok(rev.recorded > latest.recorded);
        p.revs.push(rev);
        recordedTimes.push(rev.recorded);
        await new Promise((x) => setTimeout(x, 3));
      } else {
        assert.ok([409, 422].includes(res.status), res.text);
      }
    }
    const knowns = [null, 0, ...recordedTimes, ...recordedTimes.map((x) => x - 1), Date.now() + 100000];
    for (let q = 0; q < 40; q++) {
      const uid = uids[pick(3)];
      const asOf = pick(4) === 0 ? ms(at(pick(80) * 1.25)) : BASE + pick(150 * 3600000);
      const known = knowns[pick(knowns.length)];
      const url = `?as_of=${encodeURIComponent(new Date(asOf).toISOString())}${known === null ? '' : `&known_at=${encodeURIComponent(new Date(known).toISOString())}`}`;
      const got = (await call('GET', `/me${url}`, { token: tok(uid) })).body;
      assert.equal(got.balance, expectedBalance(model, uid, asOf, known), `${uid} ${url}`);
      assert.equal(got.available, got.total);
    }
    for (let q = 0; q < 25; q++) {
      const uid = uids[pick(3)];
      const known = knowns[pick(knowns.length)];
      const from = pick(3) === 0 ? null : BASE + pick(100 * 3600000);
      const to = BASE + pick(130 * 3600000);
      if (from !== null && from > to) continue;
      const params = [];
      if (from !== null) params.push(`from=${encodeURIComponent(new Date(from).toISOString())}`);
      params.push(`to=${encodeURIComponent(new Date(to).toISOString())}`);
      if (known !== null) params.push(`known_at=${encodeURIComponent(new Date(known).toISOString())}`);
      const want = expectedStatement(model, uid, from, to, known);
      const first = (await call('GET', `/statement?${params.join('&')}&limit=4`, { token: tok(uid) })).body;
      const entries = [...first.entries];
      for (let offset = 4; first.has_more || offset === 4; offset += 4) {
        const page = (await call('GET', `/statement?snapshot=${first.snapshot}&limit=4&offset=${offset}`, { token: tok(uid) })).body;
        assert.equal(page.opening_balance, want.opening);
        entries.push(...page.entries);
        if (!page.has_more) break;
      }
      assert.equal(first.opening_balance, want.opening);
      assert.equal(first.closing_balance, want.closing);
      assert.deepEqual(entries.map((e) => [e.payment.payment_id, e.revision, e.payment.amount, e.delta, e.balance_after]),
        want.entries.map((e) => [e.id, e.revision, e.amount, e.delta, e.after]), params.join('&'));
    }
  });
}
