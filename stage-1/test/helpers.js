'use strict';

const { createServer } = require('../src/server');

const FIXTURE = {
  currency: 'EUR',
  minor_units: 2,
  users: [
    { id: 'u_ada', email: 'ada@example.com', password: 'correct horse', display_name: 'Ada', handle: 'ada', balance: 10000 },
    { id: 'u_bob', email: 'bob@example.com', password: 'correct horse', display_name: 'Bob', handle: 'bob', balance: 2500 },
    { id: 'u_cy', email: 'cy@example.com', password: 'correct horse', display_name: 'Cy', handle: 'cy', balance: 0 },
  ],
  payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, note: 'coffee', visibility: 'public' }],
  requests: [{ id: 'rq_1', requester_id: 'u_bob', payer_id: 'u_ada', amount: 1200, note: 'taxi', status: 'pending' }],
  settlement_operator_ids: ['u_cy'],
};

let server;
let base;

async function start() {
  server = createServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${server.address().port}`;
}

const stop = () => new Promise((r) => { server.closeAllConnections(); server.close(r); });

/** Raw request helper: body may be an object (JSON-encoded) or a string/Buffer sent verbatim. */
async function call(method, path, { token, key, body, headers = {} } = {}) {
  const h = { ...headers };
  if (token) h.Authorization = `Bearer ${token}`;
  if (key !== undefined) h['Idempotency-Key'] = key;
  let payload;
  if (body !== undefined) {
    payload = typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body);
    h['Content-Type'] = 'application/json';
  }
  const res = await fetch(base + path, { method, headers: h, body: payload });
  const text = await res.text();
  let json;
  try { json = text ? JSON.parse(text) : undefined; } catch (_) { json = undefined; }
  return { status: res.status, body: json, text, headers: res.headers };
}

async function reset(fixture = FIXTURE) {
  const r = await call('POST', '/_test/reset', { body: fixture });
  if (r.status !== 204) throw new Error(`reset failed: ${r.status} ${r.text}`);
}

async function login(email) {
  const r = await call('POST', '/auth/login', { body: { email, password: 'correct horse' } });
  return r.body.token;
}

async function tokens() {
  return { ada: await login('ada@example.com'), bob: await login('bob@example.com'), cy: await login('cy@example.com') };
}

async function balances(t) {
  const out = {};
  for (const [name, token] of Object.entries(t)) out[name] = (await call('GET', '/me', { token })).body.balance;
  return out;
}

module.exports = { FIXTURE, start, stop, call, reset, login, tokens, balances };
