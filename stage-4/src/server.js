// Routing and the request pipeline. Handlers are synchronous after the body is read.
import http from 'node:http';
import { randomBytes } from 'node:crypto';
import { ApiError, malformed, missingKey, unauthenticated, forbidden, invalid, notFound, conflict } from './errors.js';
import { readBody, send, sendJson, sendError } from './http.js';
import { parseJson, isObject, canon, has } from './json.js';
import { store, addUser, newId, publicPayment, publicRequest, publicAuthorization, sweep, heldOf } from './state.js';
import { UI_PAGES, SHARED_PAGES, wantsHtml, sendShell, sendAsset } from './ui.js';
import { hashPassword, verifyPassword } from './passwords.js';
import { buildState } from './fixture.js';
import { exportState, importState, idemId } from './snapshot.js';
import { paging, oneOf, page } from './validate.js';
import * as ledger from './ledger.js';
import * as queries from './queries.js';
import * as corrections from './corrections.js';

const EMAIL_RE = /^[^@\s]+@[^@\s]+$/;

export function deriveHandle(email) {
  const local = email.slice(0, email.indexOf('@'));
  return [...local.toLowerCase()].map((c) => (/[a-z0-9_]/.test(c) ? c : '_')).slice(0, 20).join('');
}

function authenticate(req) {
  const h = req.headers.authorization;
  const m = typeof h === 'string' ? /^Bearer +(\S+)$/i.exec(h.trim()) : null;
  if (!m) throw unauthenticated();
  const id = store.s.tokens.get(m[1]);
  const user = id && store.s.users.get(id);
  if (!user) throw unauthenticated();
  return user;
}

const newToken = () => randomBytes(24).toString('base64url');

function body(buf) {
  const b = parseJson(buf);
  if (!isObject(b)) throw malformed('body must be a JSON object');
  return b;
}

// Credentials: wrong type is 400, missing is 422.
function credentials(b, fields) {
  for (const f of fields) if (has(b, f) && typeof b[f] !== 'string') throw malformed(`${f} must be a string`);
  for (const f of fields) if (!has(b, f)) throw invalid(`${f} is required`);
}

async function signup(buf) {
  const b = body(buf);
  credentials(b, ['email', 'password', 'display_name']);
  if (!EMAIL_RE.test(b.email)) throw invalid('email must look like local@domain');
  if ([...b.password].length < 8) throw invalid('password must be at least 8 characters');
  const handle = deriveHandle(b.email);
  const check = () => {
    const s = store.s;
    if (s.byEmail.has(b.email)) throw conflict('email_taken', 'email is already registered');
    if (s.byHandle.has(handle)) throw conflict('handle_taken', 'derived handle is already taken');
  };
  check();
  const password_hash = await hashPassword(b.password);
  check(); // another signup or a reset may have won while hashing
  const s = store.s;
  const user = { id: newId(s, 'u', 'u', (x) => s.users.has(x)), email: b.email, display_name: b.display_name, handle, balance: 0, opening: 0, password_hash };
  addUser(s, user);
  const token = newToken();
  s.tokens.set(token, user.id);
  return { user_id: user.id, display_name: user.display_name, token };
}

async function login(buf) {
  const b = body(buf);
  credentials(b, ['email', 'password']);
  const user = store.s.byEmail.get(b.email);
  if (!user || !(await verifyPassword(b.password, user.password_hash)) || store.s.users.get(user.id) !== user) {
    throw unauthenticated('wrong email or password');
  }
  const token = newToken();
  store.s.tokens.set(token, user.id);
  return { user_id: user.id, display_name: user.display_name, token };
}

// Idempotent write: key checks, claimed-key resolution, then the handler (spec section 7).
function idempotent(req, res, user, method, path, buf, run, { emptyBodyOk = false } = {}) {
  const key = req.headers['idempotency-key'];
  if (key === undefined || key === '') throw missingKey();
  if (key.length > 255) throw invalid('Idempotency-Key must be 1 to 255 characters');
  let b;
  if (emptyBodyOk && buf.toString('utf8').trim() === '') b = {};
  else b = body(buf);
  const s = store.s;
  const id = idemId(user.id, method, path, key);
  const canonical = canon(b);
  const rec = s.idem.get(id);
  if (rec) {
    if (rec.body !== canonical) throw conflict('idempotency_key_reuse', 'Idempotency-Key was used with a different request');
    return send(res, 200, rec.response);
  }
  const text = JSON.stringify(run(b));
  s.idem.set(id, { user_id: user.id, method, path, key, body: canonical, status: 201, response: text });
  send(res, 201, text);
}

const visibleTo = (user) => (p) => p.visibility === 'public' || p.from_user_id === user.id || p.to_user_id === user.id;

export async function handle(req, res) {
  const url = new URL(req.url, 'http://localhost');
  const path = url.pathname;
  const method = req.method;
  const buf = await readBody(req);
  const q = url.searchParams;
  let m;
  sweep(store.s);

  if (method === 'GET') {
    if (UI_PAGES.has(path) || (SHARED_PAGES.has(path) && wantsHtml(req))) return sendShell(res);
    if (path.startsWith('/assets/') && sendAsset(res, path)) return;
  }

  if (path === '/health' && method === 'GET') return sendJson(res, 200, { status: 'ok' });

  if (path === '/_test/reset' && method === 'POST') {
    const fx = parseJson(buf);
    const next = await buildState(fx);
    store.s = next;
    return send(res, 204);
  }
  if (path === '/_test/export' && method === 'GET') return sendJson(res, 200, exportState(store.s));
  if (path === '/_test/import' && method === 'POST') {
    store.s = importState(parseJson(buf));
    return send(res, 204);
  }
  if (path === '/auth/signup' && method === 'POST') return sendJson(res, 201, await signup(buf));
  if (path === '/auth/login' && method === 'POST') return sendJson(res, 200, await login(buf));

  if (path === '/me' && method === 'GET') {
    const u = authenticate(req);
    return sendJson(res, 200, queries.me(u, url.search));
  }
  if (path === '/statement' && method === 'GET') {
    const u = authenticate(req);
    return sendJson(res, 200, queries.statement(u, url.search));
  }
  if ((m = /^\/payments\/([^/]+)\/(corrections|revisions|refunds)$/.exec(path)) && (method === 'POST') === (m[2] !== 'revisions')) {
    let id;
    try { id = decodeURIComponent(m[1]); } catch { throw notFound(); }
    const u = authenticate(req);
    if (m[2] === 'revisions') return sendJson(res, 200, corrections.listRevisions(u, id));
    if (m[2] === 'refunds') return idempotent(req, res, u, method, path, buf, (b) => ledger.refundPayment(u, id, b));
    return idempotent(req, res, u, method, path, buf, (b) => corrections.correctPayment(u, id, b));
  }
  if (path === '/correction-batches' && method === 'POST') {
    const u = authenticate(req);
    if (!store.s.operators.has(u.id)) throw forbidden('correction batches require an operator');
    return idempotent(req, res, u, method, path, buf, (b) => corrections.correctBatch(u, b));
  }
  if (path === '/payments' && method === 'POST') {
    const u = authenticate(req);
    return idempotent(req, res, u, method, path, buf, (b) => ledger.sendPayment(u, b));
  }
  if (path === '/requests' && method === 'POST') {
    const u = authenticate(req);
    return idempotent(req, res, u, method, path, buf, (b) => ledger.openRequest(u, b));
  }
  if (path === '/authorizations' && method === 'POST') {
    const u = authenticate(req);
    return idempotent(req, res, u, method, path, buf, (b) => ledger.createAuthorization(u, b));
  }
  if (path === '/authorizations' && method === 'GET') {
    const u = authenticate(req);
    const pg = paging(q);
    const direction = oneOf(q, 'direction', ['incoming', 'outgoing']);
    const status = oneOf(q, 'status', ['open', 'captured', 'voided', 'expired']);
    const r = page(store.s.authorizations, (x) => {
      // "outgoing": the caller is the payer; "incoming": the caller is the receiver.
      if (direction === 'incoming' ? x.to_user_id !== u.id : direction === 'outgoing' ? x.from_user_id !== u.id : x.to_user_id !== u.id && x.from_user_id !== u.id) return false;
      return status === null || x.status === status;
    }, pg);
    return sendJson(res, 200, { authorizations: r.items.map(publicAuthorization), has_more: r.has_more });
  }
  if ((m = /^\/authorizations\/([^/]+)\/(capture|void)$/.exec(path)) && method === 'POST') {
    let id;
    try { id = decodeURIComponent(m[1]); } catch { throw notFound(); }
    const u = authenticate(req);
    if (m[2] === 'capture') return idempotent(req, res, u, method, path, buf, (b) => ledger.captureAuthorization(u, id, b), { emptyBodyOk: true });
    return sendJson(res, 200, ledger.voidAuthorization(u, id));
  }
  if (path === '/splits' && method === 'POST') {
    const u = authenticate(req);
    return idempotent(req, res, u, method, path, buf, (b) => ledger.createSplit(u, b));
  }
  if (path === '/settlements' && method === 'POST') {
    const u = authenticate(req);
    if (!store.s.operators.has(u.id)) throw forbidden('settlements require an operator');
    return idempotent(req, res, u, method, path, buf, (b) => ledger.createSettlement(u, b));
  }
  if (path === '/requests' && method === 'GET') {
    const u = authenticate(req);
    const pg = paging(q);
    const direction = oneOf(q, 'direction', ['incoming', 'outgoing']);
    const status = oneOf(q, 'status', ['pending', 'paid', 'declined', 'cancelled']);
    const r = page(store.s.requests, (x) => {
      if (direction === 'incoming' ? x.payer_id !== u.id : direction === 'outgoing' ? x.requester_id !== u.id : x.payer_id !== u.id && x.requester_id !== u.id) return false;
      return status === null || x.status === status;
    }, pg);
    return sendJson(res, 200, { requests: r.items.map(publicRequest), has_more: r.has_more });
  }
  if (path === '/activity' && method === 'GET') {
    const u = authenticate(req);
    const r = page(store.s.payments, visibleTo(u), paging(q));
    return sendJson(res, 200, { payments: r.items.map(publicPayment), has_more: r.has_more });
  }
  if ((m = /^\/requests\/([^/]+)\/(pay|decline|cancel)$/.exec(path)) && method === 'POST') {
    let id;
    try { id = decodeURIComponent(m[1]); } catch { throw notFound(); }
    const u = authenticate(req);
    if (m[2] === 'pay') return idempotent(req, res, u, method, path, buf, (b) => ledger.payRequest(u, id, b), { emptyBodyOk: true });
    return sendJson(res, 200, m[2] === 'decline' ? ledger.declineRequest(u, id) : ledger.cancelRequest(u, id));
  }
  throw notFound('no such route');
}

export function createServer() {
  const server = http.createServer({ maxHeaderSize: 256 * 1024, keepAliveTimeout: 65000 }, (req, res) => {
    handle(req, res).catch((e) => {
      if (e instanceof ApiError) return sendError(res, e.status, e.code, e.message);
      console.error('unexpected error', e);
      return sendError(res, 500, 'internal_error', 'internal error');
    });
  });
  server.headersTimeout = 70000;
  server.on('clientError', (err, socket) => {
    if (socket.writable) {
      const code = err.code === 'HPE_HEADER_OVERFLOW' ? 431 : 400;
      const text = JSON.stringify({ error: { code: 'malformed_request', message: 'bad request' } });
      socket.end(`HTTP/1.1 ${code} Bad Request\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: ${Buffer.byteLength(text)}\r\nConnection: close\r\n\r\n${text}`);
    } else socket.destroy();
  });
  return server;
}
