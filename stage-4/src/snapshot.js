// GET /_test/export and POST /_test/import.
// state.schema_version is this module's own version: 1 (stage 1), 2 (stage 2) and 3 (this stage)
// are all accepted on import; export writes 3.
import { emptyState, addUser, insertOrdered, sweep, STATE_SCHEMA_VERSION } from './state.js';
import { invalid } from './errors.js';
import { isObject, has } from './json.js';
import { parseStamp, parseInstant } from './time.js';
import { parseInstantNs, msToNs } from './instants.js';
import { HANDLE_RE } from './validate.js';
import { validHashFormat } from './passwords.js';

const PAYMENT_KEYS = ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'currency', 'note', 'visibility', 'request_id', 'settlement_id', 'authorization_id', 'refund_of', 'created_at'];
const AUTH_KEYS = ['authorization_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'captured_amount', 'currency', 'note', 'visibility', 'status', 'expires_at', 'payment_id', 'payment_ids', 'created_at', 'voided_at', 'closed_at'];
const REQUEST_KEYS = ['request_id', 'requester_id', 'requester_handle', 'payer_id', 'payer_handle', 'amount', 'currency', 'note', 'status', 'payment_id', 'created_at'];
const pick = (o, keys) => Object.fromEntries(keys.map((k) => [k, o[k]]));
const nsText = (n) => (n === null ? null : n.toString());

export const idemId = (userId, method, path, key) => `${userId}\0${method}\0${path}\0${key}`;

// Runs synchronously, so the result is a consistent point-in-time copy.
export function exportState(s) {
  sweep(s);
  return {
    track: 'pocketful',
    format_version: 1,
    state: {
      schema_version: STATE_SCHEMA_VERSION,
      currency: s.currency,
      minor_units: s.minorUnits,
      authorization_ttl_seconds: s.authTtl,
      users: [...s.users.values()].map((u) => pick(u, ['id', 'email', 'display_name', 'handle', 'balance', 'opening', 'password_hash'])),
      tokens: [...s.tokens].map(([token, user_id]) => ({ token, user_id })),
      payments: s.payments.map((p) => ({
        ...pick(p, PAYMENT_KEYS),
        revisions: p.revisions.map((r) => ({ ...pick(r, ['revision', 'amount', 'effective_at', 'recorded_at', 'reason', 'kseq']), correction_batch_id: r.batch === undefined ? null : r.batch })),
      })),
      requests: s.requests.map((r) => pick(r, REQUEST_KEYS)),
      splits: s.splits.map((x) => ({ ...x, shares: x.shares.map((h) => ({ ...h })), request_ids: [...x.request_ids] })),
      settlements: s.settlements.map((x) => ({ ...x, payment_ids: [...x.payment_ids] })),
      authorizations: s.authorizations.map((a) => ({
        ...pick(a, AUTH_KEYS), payment_ids: [...a.payment_ids],
        kseq: a.kseq, void_kseq: a.voidKseq, initial_captured: a.initialCaptured, seeded_closed: a.seededClosed,
      })),
      settlement_operator_ids: [...s.operators],
      idempotency: [...s.idem.values()].map((e) => ({ ...e })),
      statement_snapshots: [...s.snapshots].map(([token, x]) => ({
        token, user_id: x.user_id, from_ns: nsText(x.fromNs), to_ns: nsText(x.toNs), known_ns: nsText(x.K), kseq: x.kseq, known_at: x.knownAtText,
      })),
      kseq: s.kseq,
      counters: { ...s.counters },
    },
  };
}

const bad = (m) => invalid(`import: ${m}`);
const str = (v) => typeof v === 'string';
const id64 = (v) => str(v) && v.length >= 1 && v.length <= 64;
const int = (v) => typeof v === 'number' && Number.isSafeInteger(v);
const big = (v) => typeof v === 'number' && Number.isInteger(v) && Math.abs(v) <= 2 ** 53; // balances may sit exactly at 2^53
const arr = (st, k) => {
  if (!Array.isArray(st[k])) throw bad(`${k} must be an array`);
  return st[k];
};
const obj = (v, what) => {
  if (!isObject(v)) throw bad(`${what} must be an object`);
  return v;
};
const bigint = (v) => {
  if (!str(v) || !/^-?\d+$/.test(v)) throw bad('snapshot instant is invalid');
  return BigInt(v);
};

// Validates the whole export envelope and returns a fresh state; never touches live state.
export function importState(doc) {
  if (!isObject(doc)) throw bad('body must be a JSON object');
  if (doc.track !== 'pocketful') throw bad('track must be "pocketful"');
  if (doc.format_version !== 1) throw bad('format_version must be 1');
  const st = obj(doc.state, 'state');
  // Stage-1 exports (schema 1) have no authorizations; stage-2 (schema 2) have no revision history or opening
  // balances. History is rebuilt from what they do contain; nothing is regenerated or replayed.
  const version = st.schema_version;
  if (![1, 2, 3, 4].includes(version)) throw bad('unsupported state schema_version');
  const v3 = version >= 3; // schema 3 and later carry opening balances, revisions and snapshots
  const v4 = version >= 4; // schema 4 adds refunds and correction batches
  if (!str(st.currency) || st.currency === '') throw bad('currency is invalid');
  if (![0, 2, 3].includes(st.minor_units)) throw bad('minor_units is invalid');
  const s = emptyState();
  s.currency = st.currency;
  s.minorUnits = st.minor_units;
  if (version >= 2) {
    const ttl = st.authorization_ttl_seconds;
    if (typeof ttl !== 'number' || !Number.isInteger(ttl) || ttl < 1) throw bad('authorization_ttl_seconds is invalid');
    s.authTtl = ttl;
  }
  let latestMs = Date.now();
  const seen = (ms) => { if (ms > latestMs) latestMs = ms; };

  for (const raw of arr(st, 'users')) {
    const u = obj(raw, 'user');
    if (!id64(u.id) || !str(u.email) || !str(u.display_name) || !str(u.handle) || !HANDLE_RE.test(u.handle)) throw bad('user is invalid');
    if (!big(u.balance) || u.balance < 0) throw bad('user balance is invalid');
    if (!validHashFormat(u.password_hash)) throw bad('user password_hash is invalid');
    if (v3 && !big(u.opening)) throw bad('user opening balance is invalid');
    if (s.users.has(u.id) || s.byHandle.has(u.handle) || s.byEmail.has(u.email)) throw bad('duplicate user');
    addUser(s, { ...pick(u, ['id', 'email', 'display_name', 'handle', 'balance', 'password_hash']), opening: v3 ? u.opening : u.balance });
  }
  for (const raw of arr(st, 'tokens')) {
    const t = obj(raw, 'token');
    if (!str(t.token) || t.token === '' || !s.users.has(t.user_id)) throw bad('token is invalid');
    s.tokens.set(t.token, t.user_id);
  }
  const common = (r, user1, user2, h1, h2) => {
    const a = s.users.get(r[user1]), b = s.users.get(r[user2]);
    if (!a || !b || a.handle !== r[h1] || b.handle !== r[h2]) throw bad('record references an unknown user');
    if (!int(r.amount) || r.amount < 0) throw bad('record amount is invalid');
    if (r.currency !== s.currency || !str(r.note)) throw bad('record is invalid');
    const ms = parseStamp(r.created_at);
    if (ms === null) throw bad('record created_at is invalid');
    seen(ms);
    return ms;
  };
  for (const raw of arr(st, 'payments')) {
    const p = obj(raw, 'payment');
    common(p, 'from_user_id', 'to_user_id', 'from_handle', 'to_handle');
    const ns = parseInstantNs(p.created_at);
    if (ns === null) throw bad('payment created_at is invalid');
    if (!id64(p.payment_id) || s.paymentById.has(p.payment_id)) throw bad('payment id is invalid');
    if (p.visibility !== 'public' && p.visibility !== 'private') throw bad('payment visibility is invalid');
    if (p.request_id !== null && !id64(p.request_id)) throw bad('payment request_id is invalid');
    if (p.settlement_id !== null && !id64(p.settlement_id)) throw bad('payment settlement_id is invalid');
    if (version === 1) p.authorization_id = null;
    else if (p.authorization_id !== null && !id64(p.authorization_id)) throw bad('payment authorization_id is invalid');
    if (!v4) p.refund_of = null;
    else if (p.refund_of !== null && !id64(p.refund_of)) throw bad('payment refund_of is invalid');
    const rec = { ...pick(p, PAYMENT_KEYS), ts: ns, seq: ++s.seq, refunded: 0 };
    if (v3) {
      if (!Array.isArray(p.revisions) || p.revisions.length < 1) throw bad('payment revisions are invalid');
      let prevRec = null;
      let prevK = 0;
      rec.revisions = p.revisions.map((raw2, i) => {
        const r = obj(raw2, 'revision');
        const eff = parseInstantNs(r.effective_at), recd = parseInstantNs(r.recorded_at);
        if (r.revision !== i + 1 || !int(r.amount) || r.amount < 0 || r.amount > 1000000000 + (i === 0 ? 0 : 0) || eff === null || recd === null || !str(r.reason) || !int(r.kseq) || r.kseq <= prevK) throw bad('payment revision is invalid');
        if (prevRec !== null && recd <= prevRec) throw bad('payment revision recorded_at must strictly increase');
        prevRec = recd;
        prevK = r.kseq;
        seen(Number(recd / 1000000n));
        if (v4 && !(r.correction_batch_id === null || id64(r.correction_batch_id))) throw bad('revision correction_batch_id is invalid');
        return { revision: r.revision, amount: r.amount, effective_at: r.effective_at, eff, recorded_at: r.recorded_at, rec: recd, reason: r.reason, kseq: r.kseq, batch: v4 ? r.correction_batch_id : null };
      });
      if (rec.revisions[0].amount !== p.amount) throw bad('payment amount does not match revision 1');
    } else {
      rec.revisions = [{ revision: 1, amount: p.amount, effective_at: p.created_at, eff: ns, recorded_at: p.created_at, rec: ns, reason: '', kseq: ++s.kseq, batch: null }];
    }
    s.paymentById.set(rec.payment_id, rec);
    insertOrdered(s.payments, rec);
  }
  for (const raw of arr(st, 'requests')) {
    const r = obj(raw, 'request');
    const ms = common(r, 'requester_id', 'payer_id', 'requester_handle', 'payer_handle');
    if (!id64(r.request_id) || s.requestById.has(r.request_id)) throw bad('request id is invalid');
    if (!['pending', 'paid', 'declined', 'cancelled'].includes(r.status)) throw bad('request status is invalid');
    if (r.payment_id !== null && !s.paymentById.has(r.payment_id)) throw bad('request references an unknown payment');
    const rec = { ...pick(r, REQUEST_KEYS), ts: ms, seq: ++s.seq };
    s.requestById.set(rec.request_id, rec);
    insertOrdered(s.requests, rec);
  }
  for (const p of s.payments) {
    if (p.request_id !== null && !s.requestById.has(p.request_id)) throw bad('payment references an unknown request');
    if (p.refund_of !== null) {
      const target = s.paymentById.get(p.refund_of);
      if (!target || target.refund_of !== null || target.from_user_id !== p.to_user_id || target.to_user_id !== p.from_user_id) throw bad('refund references an invalid payment');
      target.refunded += p.revisions[0].amount;
    }
  }
  if (version >= 2) {
    for (const raw of arr(st, 'authorizations')) {
      const a = obj(raw, 'authorization');
      const from = s.users.get(a.from_user_id), to = s.users.get(a.to_user_id);
      if (!id64(a.authorization_id) || s.authById.has(a.authorization_id)) throw bad('authorization id is invalid');
      if (!from || !to || from.handle !== a.from_handle || to.handle !== a.to_handle) throw bad('authorization references an unknown user');
      if (!int(a.amount) || a.amount < 1 || !int(a.captured_amount) || a.captured_amount < 0 || a.captured_amount > a.amount) throw bad('authorization amounts are invalid');
      if (a.currency !== s.currency || !str(a.note) || (a.visibility !== 'public' && a.visibility !== 'private')) throw bad('authorization is invalid');
      if (!['open', 'captured', 'voided', 'expired'].includes(a.status)) throw bad('authorization status is invalid');
      const exp = parseInstant(a.expires_at);
      const created = parseStamp(a.created_at);
      const expNs = parseInstantNs(a.expires_at), createdNs = parseInstantNs(a.created_at);
      if (exp === null || created === null || expNs === null || createdNs === null) throw bad('authorization timestamps are invalid');
      seen(created);
      if (a.payment_id !== null && !id64(a.payment_id)) throw bad('authorization payment_id is invalid');
      if (!Array.isArray(a.payment_ids) || !a.payment_ids.every(id64)) throw bad('authorization payment_ids is invalid');
      let voidNs = null;
      if (a.voided_at !== undefined && a.voided_at !== null) {
        voidNs = parseInstantNs(a.voided_at);
        if (voidNs === null) throw bad('authorization voided_at is invalid');
      }
      const resolvable = a.payment_ids.map((id) => s.paymentById.get(id)).filter(Boolean);
      const rec = {
        ...pick(a, AUTH_KEYS), voided_at: a.voided_at ?? null, payment_ids: [...a.payment_ids], ts: created, seq: ++s.seq,
        createdNs, expNs, voidNs, closed_at: null, kseq: 0, voidKseq: null, initialCaptured: 0, seededClosed: false,
      };
      if (v3) {
        if (!int(a.kseq) || !(a.void_kseq === null || int(a.void_kseq)) || !int(a.initial_captured) || a.initial_captured < 0 || typeof a.seeded_closed !== 'boolean' || !(a.closed_at === null || str(a.closed_at))) throw bad('authorization history is invalid');
        rec.kseq = a.kseq; rec.voidKseq = a.void_kseq; rec.initialCaptured = a.initial_captured; rec.seededClosed = a.seeded_closed; rec.closed_at = a.closed_at;
      } else {
        // Rebuild the hold's life from what a stage-2 export records: creation, the capture payments, the void instant, the deadline.
        rec.kseq = ++s.kseq;
        if (voidNs !== null) rec.voidKseq = ++s.kseq;
        rec.initialCaptured = Math.max(0, a.captured_amount - resolvable.reduce((sum, p) => sum + p.revisions[0].amount, 0));
        rec.seededClosed = (a.status === 'voided' && voidNs === null) || (a.status === 'captured' && resolvable.length === 0);
        if (a.status === 'captured') rec.closed_at = resolvable.length ? resolvable[resolvable.length - 1].created_at : a.expires_at;
        else if (a.status === 'voided') rec.closed_at = a.voided_at ?? a.created_at;
        else if (a.status === 'expired') rec.closed_at = a.expires_at;
      }
      s.authById.set(rec.authorization_id, rec);
      insertOrdered(s.authorizations, rec);
      if (rec.status === 'open') s.openAuths.add(rec);
    }
    const held = new Map();
    for (const a of s.openAuths) held.set(a.from_user_id, (held.get(a.from_user_id) || 0) + a.amount - a.captured_amount);
    for (const [uid, h] of held) if (h > s.users.get(uid).balance) throw bad('open holds exceed a balance');
  }
  if (!v3) {
    // Opening balance = imported balance minus the net effect of the imported payments.
    for (const p of s.payments) {
      s.users.get(p.from_user_id).opening += p.amount;
      s.users.get(p.to_user_id).opening -= p.amount;
    }
  }
  for (const raw of arr(st, 'splits')) {
    const x = obj(raw, 'split');
    if (!id64(x.id) || !s.users.has(x.user_id) || !int(x.amount) || !str(x.note) || !str(x.created_at)) throw bad('split is invalid');
    if (!Array.isArray(x.shares) || !x.shares.every((h) => isObject(h) && str(h.handle) && int(h.amount))) throw bad('split shares are invalid');
    if (!Array.isArray(x.request_ids) || !x.request_ids.every((q) => s.requestById.has(q))) throw bad('split requests are invalid');
    s.splits.push({ id: x.id, user_id: x.user_id, amount: x.amount, note: x.note, shares: x.shares.map((h) => ({ handle: h.handle, amount: h.amount })), request_ids: [...x.request_ids], created_at: x.created_at });
  }
  for (const raw of arr(st, 'settlements')) {
    const x = obj(raw, 'settlement');
    if (!id64(x.id) || !s.users.has(x.operator_id) || !str(x.committed_at)) throw bad('settlement is invalid');
    if (!Array.isArray(x.payment_ids) || !x.payment_ids.every((q) => s.paymentById.has(q))) throw bad('settlement payments are invalid');
    s.settlements.push({ id: x.id, operator_id: x.operator_id, committed_at: x.committed_at, payment_ids: [...x.payment_ids] });
  }
  for (const o of arr(st, 'settlement_operator_ids')) {
    if (!s.users.has(o)) throw bad('operator is not a user');
    s.operators.add(o);
  }
  for (const raw of arr(st, 'idempotency')) {
    const e = obj(raw, 'idempotency record');
    if (!s.users.has(e.user_id) || !str(e.method) || !str(e.path) || !str(e.key) || !str(e.body) || !str(e.response)) throw bad('idempotency record is invalid');
    if (e.status !== 201) throw bad('idempotency record is invalid');
    try { JSON.parse(e.response); JSON.parse(e.body); } catch { throw bad('idempotency record is invalid'); }
    s.idem.set(idemId(e.user_id, e.method, e.path, e.key), { user_id: e.user_id, method: e.method, path: e.path, key: e.key, body: e.body, status: 201, response: e.response });
  }
  if (v3) {
    if (!int(st.kseq) || st.kseq < 0) throw bad('kseq is invalid');
    s.kseq = Math.max(s.kseq, st.kseq);
    for (const raw of arr(st, 'statement_snapshots')) {
      const x = obj(raw, 'statement snapshot');
      if (!str(x.token) || x.token === '' || x.token.length > 64 || !s.users.has(x.user_id) || !int(x.kseq) || !(x.known_at === null || str(x.known_at))) throw bad('statement snapshot is invalid');
      s.snapshots.set(x.token, {
        user_id: x.user_id, fromNs: x.from_ns === null ? null : bigint(x.from_ns), toNs: bigint(x.to_ns),
        K: x.known_ns === null ? null : bigint(x.known_ns), kseq: x.kseq, knownAtText: x.known_at,
      });
    }
  }
  const c = has(st, 'counters') ? obj(st.counters, 'counters') : {};
  for (const k of Object.keys(s.counters)) {
    if (has(c, k)) {
      if (!int(c[k]) || c[k] < 0) throw bad('counters are invalid');
      s.counters[k] = c[k];
    }
  }
  s.lastMs = 0; // the service clock is the real clock; nothing imported moves it
  sweep(s);
  return s;
}
