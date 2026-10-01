// Property test: for random sequences of payments, corrections, holds, captures, voids and settlements, the
// service's /me?as_of&known_at (the view function) must equal a brute-force replay computed here from
// nothing but API-visible records (payment objects, the revisions endpoint, the authorization listing).
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startServer, k, login } from './helper.js';

let c;
before(async () => { c = await startServer(); });
after(() => c.stop());

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const iso = (ms) => new Date(ms).toISOString();
const NAMES = ['ada', 'bob', 'cy', 'op'];

function rng(seed) {
  let x = seed >>> 0;
  return () => { x = (Math.imul(x, 1664525) + 1013904223) >>> 0; return x / 4294967296; };
}

async function scenario(seed) {
  const R = rng(seed);
  const ri = (lo, hi) => lo + Math.floor(R() * (hi - lo + 1));
  const pickOne = (a) => a[ri(0, a.length - 1)];
  const T0 = Date.now() - 3 * 3600 * 1000;
  const users = NAMES.map((n, i) => ({ id: `u_${n}`, email: `${n}@example.com`, password: 'correct horse', display_name: n, handle: n, balance: [20000, 8000, 3000, 0][i] }));
  const seededPays = [];
  for (let i = 0; i < 4; i++) {
    const [f, to] = [pickOne(NAMES.slice(0, 3)), pickOne(NAMES.slice(0, 3))];
    if (f === to) continue;
    seededPays.push({ id: `s_${i}`, from_user_id: `u_${f}`, to_user_id: `u_${to}`, amount: ri(1, 300), created_at: iso(T0 + i * 600000 + 12345) });
  }
  assert.equal((await c.reset({ currency: 'EUR', minor_units: 2, authorization_ttl_seconds: 3600, settlement_operator_ids: ['u_op'], users, payments: seededPays })).status, 204);
  const tok = {};
  for (const n of NAMES) tok[n] = await login(c, `${n}@example.com`);
  const total = users.reduce((a, u) => a + u.balance, 0);
  const opening = Object.fromEntries(users.map((u) => [u.id, u.balance]));
  for (const p of seededPays) { opening[p.from_user_id] += p.amount; opening[p.to_user_id] -= p.amount; }
  const paymentIds = seededPays.map((p) => p.id);
  const payments = new Map(); // id -> original payment object
  const auths = [];
  const startMs = Date.now();

  for (let step = 0; step < 70; step++) {
    const op = R();
    const a = pickOne(NAMES.slice(0, 3));
    const b = pickOne(NAMES.slice(0, 3).filter((n) => n !== a));
    if (op < 0.3) {
      const r = await c.post('/payments', { token: tok[a], key: k(), body: { to_handle: b, amount: ri(1, 400), visibility: R() < 0.5 ? 'public' : 'private' } });
      if (r.status === 201) { paymentIds.push(r.json.payment_id); }
    } else if (op < 0.55 && paymentIds.length) {
      const id = pickOne(paymentIds);
      // find the original to know the sender; the sender's token corrects
      const pObj = (await c.get('/activity?limit=200', { token: tok.ada })).json.payments;
      void pObj;
      const owner = await senderOf(id);
      if (!owner) continue;
      const revs = (await c.get(`/payments/${id}/revisions`, { token: tok[owner] })).json.revisions;
      const body = { expected_revision: revs.length, amount: R() < 0.2 ? 0 : ri(0, 500), effective_at: iso(ri(T0, Date.now())), reason: `r${step}` };
      await c.post(`/payments/${id}/corrections`, { token: tok[owner], key: k(), body });
    } else if (op < 0.7) {
      const r = await c.post('/authorizations', { token: tok[a], key: k(), body: { to_handle: b, amount: ri(10, 900) } });
      if (r.status === 201) auths.push({ id: r.json.authorization_id, from: a, to: b });
    } else if (op < 0.85 && auths.length) {
      const h = pickOne(auths);
      const r = await c.post(`/authorizations/${h.id}/capture`, { token: tok[h.to], key: k(), body: R() < 0.5 ? { amount: ri(1, 400), final: R() < 0.3 } : {} });
      if (r.status === 201) paymentIds.push(r.json.payment_id);
    } else if (op < 0.92 && auths.length) {
      const h = pickOne(auths);
      await c.post(`/authorizations/${h.id}/void`, { token: tok[h.from] });
    } else {
      const r = await c.post('/settlements', { token: tok.op, key: k(), body: { transfers: [{ from_handle: a, to_handle: b, amount: ri(1, 200) }, { from_handle: b, to_handle: 'cy' === b ? 'ada' : 'cy', amount: ri(1, 100) }] } });
      if (r.status === 201) for (const p of r.json.payments) paymentIds.push(p.payment_id);
    }
    if (R() < 0.5) await sleep(ri(1, 4));
  }
  async function senderOf(id) {
    for (const n of NAMES) {
      const r = await c.get(`/payments/${id}/revisions`, { token: tok[n] });
      if (r.status === 200) {
        const act = (await c.get('/statement?limit=200', { token: tok[n] })).json.entries.find((e) => e.payment.payment_id === id);
        if (act && act.payment.from_handle === n) return n;
      }
    }
    return null;
  }
  const endMs = Date.now();

  // ---- the brute-force model from API-visible records ----
  const model = { pays: [], auths: [] };
  for (const id of paymentIds) {
    const owner = await anyParty(id);
    const rev = (await c.get(`/payments/${id}/revisions`, { token: tok[owner] })).json.revisions;
    const st = (await c.get('/statement?limit=200', { token: tok[owner] })).json.entries.find((e) => e.payment.payment_id === id).payment;
    model.pays.push({ id, from: st.from_user_id, to: st.to_user_id, created: Date.parse(st.created_at), revs: rev.map((r) => ({ amount: r.amount, eff: Date.parse(r.effective_at), rec: Date.parse(r.recorded_at) })) });
  }
  async function anyParty(id) {
    for (const n of NAMES) if ((await c.get(`/payments/${id}/revisions`, { token: tok[n] })).status === 200) return n;
    throw new Error('no party for ' + id);
  }
  const byId = new Map(model.pays.map((p) => [p.id, p]));
  for (const h of auths) {
    const a = (await c.get('/authorizations?limit=200', { token: tok[h.from] })).json.authorizations.find((x) => x.authorization_id === h.id);
    model.auths.push({
      from: `u_${h.from}`, amount: a.amount, created: Date.parse(a.created_at), exp: Date.parse(a.expires_at), status: a.status,
      captures: a.payment_ids.map((pid, i) => ({ t: byId.get(pid).created, amount: byId.get(pid).revs[0].amount, final: a.status === 'captured' && i === a.payment_ids.length - 1 })),
      voidAt: a.status === 'voided' ? Date.parse(a.closed_at) : null,
    });
  }
  const stats = { corrected: model.pays.filter((p) => p.revs.length > 1).length, pays: model.pays.length, holds: model.auths.length, voided: model.auths.filter((a) => a.voidAt !== null).length, captured: model.auths.filter((a) => a.captures.length).length };
  assert.ok(stats.corrected >= 2 && stats.holds >= 3 && stats.captured >= 1, JSON.stringify({ seed, ...stats }));
  function expected(uid, A, K) {
    let tot = opening[uid];
    for (const p of model.pays) {
      const sg = p.from === uid ? -1 : p.to === uid ? 1 : 0;
      if (!sg) continue;
      let sel = null;
      for (const r of p.revs) if (K === null || r.rec <= K) sel = r;
      if (sel && sel.eff <= A) tot += sg * sel.amount;
    }
    let held = 0;
    for (const a of model.auths) {
      if (a.from !== uid) continue;
      const known = (t) => t <= A && (K === null || t <= K);
      if (!known(a.created) || a.exp <= A) continue;
      let rem = a.amount;
      let closed = false;
      for (const cp of a.captures) {
        if (!known(cp.t)) continue;
        rem -= cp.amount;
        if (cp.final || rem <= 0) { closed = true; break; }
      }
      if (!closed && a.voidAt !== null && known(a.voidAt)) closed = true;
      if (!closed) held += rem;
    }
    return { total: tot, held, available: tot - held };
  }

  let checked = 0;
  const instants = [startMs - 7200000, T0 - 1, T0 + 12345, ...Array.from({ length: 14 }, () => ri(T0, endMs + 7200000)), endMs, endMs + 10, endMs + 4000000];
  const knowns = [null, null, ...Array.from({ length: 6 }, () => ri(startMs - 100, endMs + 100)), startMs - 1, endMs + 3600000];
  for (const A of instants) {
    for (const K of knowns.slice(0, 5)) {
      let sum = 0;
      for (const n of NAMES) {
        const q = `?as_of=${encodeURIComponent(iso(A))}` + (K === null ? '' : `&known_at=${encodeURIComponent(iso(K))}`);
        const got = (await c.get('/me' + q, { token: tok[n] })).json;
        const want = expected(`u_${n}`, A, K);
        assert.deepEqual([got.total, got.available, got.held, got.balance], [want.total, want.available, want.held, want.total], `seed ${seed} ${n} A=${iso(A)} K=${K === null ? 'now' : iso(K)}`);
        sum += got.total;
        checked++;
      }
      if (K === null || K > endMs) assert.equal(sum, total, `conservation, seed ${seed}`);
    }
  }
  // no parameters: the incrementally maintained current numbers equal the view at "now"
  for (const n of NAMES) {
    const cur = (await c.get('/me', { token: tok[n] })).json;
    const now = Date.now();
    const want = expected(`u_${n}`, now + 1, null);
    assert.deepEqual([cur.total, cur.available, cur.held], [want.total, want.available, want.held], `seed ${seed} current ${n}`);
    const asOfNow = (await c.get(`/me?as_of=${encodeURIComponent(iso(now + 1))}`, { token: tok[n] })).json;
    assert.deepEqual([asOfNow.total, asOfNow.available, asOfNow.held], [cur.total, cur.available, cur.held]);
    assert.ok(cur.available >= 0 && cur.total >= 0);
  }
  return checked;
}

for (const seed of [1, 7, 42, 20260924]) {
  test(`view == brute-force replay (seed ${seed})`, { timeout: 120000 }, async () => {
    const n = await scenario(seed);
    assert.ok(n > 200);
  });
}
