import { spawn } from 'node:child_process';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer().listen(0, () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

// Starts the service (or targets TEST_BASE_URL) and returns a tiny client.
export async function startServer(env = {}) {
  if (process.env.TEST_BASE_URL) return client(process.env.TEST_BASE_URL, null);
  const port = await freePort();
  const child = spawn(process.execPath, ['src/index.js'], { cwd: root, env: { ...process.env, PORT: String(port), ...env }, stdio: 'ignore' });
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(base + '/health')).ok) break; } catch { /* retry */ }
    await new Promise((r) => setTimeout(r, 50));
  }
  return client(base, child);
}

export function client(base, child) {
  const call = async (method, p, { token, key, body, raw, headers = {} } = {}) => {
    const h = { ...headers };
    if (token) h.authorization = `Bearer ${token}`;
    if (key !== undefined) h['idempotency-key'] = key;
    let payload;
    if (method === 'GET') { /* no body */ }
    else if (raw !== undefined) { payload = raw; h['content-type'] = 'application/json'; }
    else if (body !== undefined) { payload = JSON.stringify(body); h['content-type'] = 'application/json'; }
    const r = await fetch(base + p, { method, headers: h, body: payload });
    const text = await r.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { /* not json */ }
    return { status: r.status, json, text, headers: r.headers };
  };
  return {
    base,
    call,
    get: (p, o) => call('GET', p, o),
    post: (p, o) => call('POST', p, o),
    reset: (fx) => call('POST', '/_test/reset', { body: fx }),
    stop: () => child && child.kill(),
  };
}

export const FX = (extra = {}) => ({
  currency: 'EUR',
  minor_units: 2,
  users: [
    { id: 'u_ada', email: 'ada@example.com', password: 'correct horse', display_name: 'Ada', handle: 'ada', balance: 10000 },
    { id: 'u_bob', email: 'bob@example.com', password: 'correct horse', display_name: 'Bob', handle: 'bob', balance: 2500 },
    { id: 'u_cy', email: 'cy@example.com', password: 'correct horse', display_name: 'Cy', handle: 'cy', balance: 0 },
    { id: 'u_op', email: 'op@example.com', password: 'correct horse', display_name: 'Op', handle: 'op', balance: 0 },
  ],
  settlement_operator_ids: ['u_op'],
  ...extra,
});

export async function login(c, email) {
  const r = await c.post('/auth/login', { body: { email, password: 'correct horse' } });
  if (r.status !== 200) throw new Error('login failed ' + r.text);
  return r.json.token;
}

export async function setup(extra) {
  const c = await startServer();
  const res = await c.reset(FX(extra));
  if (res.status !== 204) throw new Error('reset failed ' + res.text);
  const t = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) t[n] = await login(c, `${n}@example.com`);
  return { c, t };
}

export const balanceSum = async (c, tokens) => {
  let sum = 0;
  for (const t of tokens) sum += (await c.get('/me', { token: t })).json.balance;
  return sum;
};

let n = 0;
export const k = () => `key-${process.pid}-${++n}-${Math.random().toString(36).slice(2)}`;
