// Read endpoints over time: GET /me with as_of/known_at, and GET /statement with snapshots.
import { randomBytes } from 'node:crypto';
import { store, clockMs, availableOf, heldOf } from './state.js';
import { invalid, notFound } from './errors.js';
import { parseInstantNs, rawQuery, msToNs } from './instants.js';
import { viewOf, statementOf, FOREVER } from './history.js';
import { paging } from './validate.js';

// An instant query parameter: absent -> null; present but not an RFC 3339 instant with an offset -> 422.
function instantParam(raw, name) {
  if (!raw.has(name)) return null;
  const text = raw.get(name);
  const ns = parseInstantNs(text);
  if (ns === null) throw invalid(`${name} must be an RFC 3339 instant with an offset`);
  return { text, ns };
}

export function me(user, search) {
  const s = store.s;
  const raw = rawQuery(search);
  const asOf = instantParam(raw, 'as_of');
  const knownAt = instantParam(raw, 'known_at');
  const base = { user_id: user.id, display_name: user.display_name, handle: user.handle };
  if (!asOf && !knownAt) {
    const held = heldOf(s, user.id);
    return { ...base, balance: user.balance, total: user.balance, available: user.balance - held, held, currency: s.currency, minor_units: s.minorUnits };
  }
  // Without as_of the instant is the one the request began: movements count up to the end of the current clock tick
  // (the clock reads whole milliseconds, clients send microseconds); holds expire at the plain reading.
  const A = asOf ? asOf.ns : msToNs(clockMs(s));
  const moveA = asOf ? asOf.ns : A + 999999n;
  const v = viewOf(s, user, A, knownAt ? knownAt.ns : null, FOREVER, moveA);
  const out = { ...base, balance: v.total, total: v.total, available: v.available, held: v.held, currency: s.currency, minor_units: s.minorUnits };
  if (asOf) out.as_of = asOf.text;
  if (knownAt) out.known_at = knownAt.text;
  return out;
}

const page = (stmt, pg, snapshot, knownAtText) => {
  const out = {
    opening_balance: stmt.opening_balance,
    entries: stmt.entries.slice(pg.offset, pg.offset + pg.limit),
    closing_balance: stmt.closing_balance,
    has_more: pg.offset + pg.limit < stmt.entries.length,
    snapshot,
  };
  if (knownAtText !== null) out.known_at = knownAtText;
  return out;
};

export function statement(user, search) {
  const s = store.s;
  const raw = rawQuery(search);
  const pg = paging(new URLSearchParams(search));
  if (raw.has('snapshot')) {
    // Only limit and offset may accompany a snapshot; this is checked before the token is looked up.
    if (raw.has('from') || raw.has('to') || raw.has('known_at')) throw invalid('from, to and known_at cannot be combined with snapshot');
    const token = raw.get('snapshot');
    const snap = s.snapshots.get(token);
    if (!snap || snap.user_id !== user.id) throw notFound('unknown statement snapshot');
    return page(statementOf(s, user, snap.fromNs, snap.toNs, snap.K, snap.kseq), pg, token, snap.knownAtText);
  }
  const from = instantParam(raw, 'from');
  const to = instantParam(raw, 'to');
  const knownAt = instantParam(raw, 'known_at');
  if (from && to && from.ns > to.ns) throw invalid('from must not be later than to');
  // An omitted `to` includes everything effective up to and including the instant the read began.
  const toNs = to ? to.ns : msToNs(clockMs(s)) + 1000000n; // the end of the current clock tick, exclusive
  const snap = {
    user_id: user.id,
    fromNs: from ? from.ns : null,
    toNs,
    K: knownAt ? knownAt.ns : null,
    kseq: s.kseq, // knowledge position at this read
    knownAtText: knownAt ? knownAt.text : null,
  };
  const token = `sn_${randomBytes(24).toString('base64url')}`;
  s.snapshots.set(token, snap);
  return page(statementOf(s, user, snap.fromNs, snap.toNs, snap.K, snap.kseq), pg, token, snap.knownAtText);
}
