'use strict';

// Unit tests of the pure historical ledger (src/history.js) on a hand-built state.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { emptyState } = require('../src/state');
const { appendPayment } = require('../src/ledger');
const { addAuthorization } = require('../src/holds');
const history = require('../src/history');
const I = require('../src/instant');

const at = (n) => `2026-01-01T00:00:0${n}.000+00:00`;
const inst = (n) => I.parse(at(n));

function build() {
  const state = emptyState();
  for (const [id, opening] of [['a', 100], ['b', 0]]) {
    state.users.set(id, { id, balance: opening, held: 0, opening_balance: opening });
  }
  const pay = (id, from, to, amount, n) => {
    const p = appendPayment(state, { id, from, to, amount, note: '', visibility: 'public', createdAt: at(n) });
    state.users.get(from).balance -= amount;
    state.users.get(to).balance += amount;
    return p;
  };
  return { state, pay };
}

const correction = (p, amount, effective, recorded, n) => ({
  revision: p.revisions.length + 1, amount, effective_at: at(effective), recorded_at: at(recorded), reason: 'r', seq: n,
});

test('view: movements at or before the instant, by selected revision', () => {
  const { state, pay } = build();
  const p = pay('p1', 'a', 'b', 40, 1);
  p.revisions.push(correction(p, 10, 3, 5, 99));
  const a = state.users.get('a');
  assert.equal(history.view(state, a, inst(0), null).total, 100);
  assert.equal(history.view(state, a, inst(1), null).total, 100); // revision 2 (10 at :03) is the latest known
  assert.equal(history.view(state, a, inst(3), null).total, 90);
  assert.equal(history.view(state, a, inst(1), inst(2)).total, 60); // known at :02: still revision 1
  assert.equal(history.view(state, a, inst(1), inst(1)).total, 60); // known at :01: only revision 1
  assert.equal(history.view(state, a, inst(9), inst(4)).total, 60);
  assert.equal(history.view(state, a, inst(9), inst(5)).total, 90);
  assert.equal(history.view(state, a, inst(9), inst(0)).total, 100); // nothing recorded yet
});

test('statement: window, order, balances; snapshot sequence limit hides later revisions', () => {
  const { state, pay } = build();
  const p = pay('p1', 'a', 'b', 40, 1);
  pay('p2', 'b', 'a', 5, 2);
  const a = state.users.get('a');
  const full = history.statement(state, a, { from: null, to: inst(9), known: null, seq: null });
  assert.deepEqual([full.opening, full.closing, full.entries.map((e) => [e.payment.id, e.delta, e.balanceAfter])], [100, 65, [['p1', -40, 60], ['p2', 5, 65]]]);
  const win = history.statement(state, a, { from: inst(2), to: inst(9), known: null, seq: null });
  assert.deepEqual([win.opening, win.closing, win.entries.length], [60, 65, 1]);
  const frozen = p.revisions[0].seq;
  p.revisions.push(correction(p, 0, 1, 7, state.counters.revisionSeq + 5));
  const later = history.statement(state, a, { from: null, to: inst(9), known: null, seq: null });
  assert.equal(later.closing, 105);
  const same = history.statement(state, a, { from: null, to: inst(9), known: null, seq: state.counters.revisionSeq });
  assert.equal(same.closing, 65);
  assert.ok(frozen >= 1);
});

test('overdraft walk: refuses a lower negative boundary, accepts one that is not made worse', () => {
  const { state, pay } = build();
  const p = pay('p1', 'b', 'a', 30, 1); // a receives 30 at :01 ... but b has 0: seeded history is inconsistent
  state.users.get('a').opening_balance = 100;
  state.users.get('b').opening_balance = 0;
  state.users.get('b').balance = -30; // b already negative at :01
  const now = { ms: I.parse(at(9)).ms, rest: '' };
  const worse = correction(p, 50, 1, 8, 90);
  assert.equal(history.causesHistoricalOverdraft(state, new Map([[p.id, worse]]), now), true);
  const same = correction(p, 30, 2, 8, 91); // moves the negative boundary but does not deepen it
  assert.equal(history.causesHistoricalOverdraft(state, new Map([[p.id, same]]), now), false);
  const better = correction(p, 10, 1, 8, 92);
  assert.equal(history.causesHistoricalOverdraft(state, new Map([[p.id, better]]), now), false);
});

test('holds: standing amount over time and knowledge', () => {
  const { state, pay } = build();
  const cap = pay('c1', 'a', 'b', 20, 3);
  cap.authorization_id = 'h1';
  const auth = addAuthorization(state, {
    id: 'h1', from: 'a', to: 'b', amount: 50, captured_amount: 20, status: 'captured', created_at: at(2), expires_at: at(8),
    expires_ms: inst(8).ms, payment_ids: ['c1'], payment_id: 'c1', closed_at: at(3),
  });
  assert.equal(auth.no_history, false);
  const held = (t, k) => history.view(state, state.users.get('a'), inst(t), k === undefined ? null : inst(k)).held;
  assert.deepEqual([held(1), held(2), held(3)], [0, 50, 0]);
  assert.equal(held(5, 2), 50 - 0); // close unknown at :02, hold stands until its deadline
  assert.equal(held(8, 2), 0);
});
