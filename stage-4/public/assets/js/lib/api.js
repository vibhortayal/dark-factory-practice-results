// All API traffic. Every call is classified so the UI never confuses a refusal with an
// unknown outcome:
//   ok              2xx with a parseable body
//   refused         4xx with an error envelope (the server definitely rejected it)
//   unauthenticated 401
//   uncertain       network failure, abort, timeout, 5xx or an unparseable response
import { getToken } from './session.js';

export const TIMEOUT_MS = 10000;

export async function call(method, path, { body, key, timeout = TIMEOUT_MS } = {}) {
  const headers = { Accept: 'application/json' };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  let res;
  let text;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal });
    text = await res.text();
  } catch {
    return { kind: 'uncertain', reason: 'network' };
  } finally {
    clearTimeout(timer);
  }
  let data;
  try {
    data = text === '' ? null : JSON.parse(text);
  } catch {
    return { kind: 'uncertain', reason: 'unparseable', status: res.status };
  }
  if (res.status >= 500) return { kind: 'uncertain', reason: 'server', status: res.status };
  if (res.ok) return { kind: 'ok', status: res.status, data };
  if (res.status === 401) return { kind: 'unauthenticated', status: 401 };
  const code = data && data.error && data.error.code;
  if (typeof code === 'string') return { kind: 'refused', status: res.status, code, message: String(data.error.message || '') };
  return { kind: 'uncertain', reason: 'unparseable', status: res.status };
}
