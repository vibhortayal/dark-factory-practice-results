// Fetch wrapper: JSON in/out, bearer token, idempotency keys, and a distinct
// NetworkError for outcomes we cannot know (lost response, timeout).

const TOKEN_KEY = 'pocketful.token';
const TIMEOUT_MS = 20000;

export class NetworkError extends Error {}

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export function newKey() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function request(method, path, { body, key, auth = true } = {}) {
  const headers = { Accept: 'application/json' };
  if (auth && getToken()) headers.Authorization = `Bearer ${getToken()}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response;
  let parsed = null;
  try {
    response = await fetch(path, {
      method, headers, signal: controller.signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    try { parsed = text ? JSON.parse(text) : null; } catch { parsed = null; }
  } catch (err) {
    throw new NetworkError(String(err && err.message || err));
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 401 && auth) onUnauthorized();
  return { status: response.status, ok: response.status < 300, body: parsed };
}

const MESSAGES = {
  insufficient_funds: 'Not enough available funds for that.',
  self_payment: 'You cannot send money to yourself.',
  self_request: 'You cannot request money from yourself.',
  not_found: 'We could not find that person or item.',
  request_not_pending: 'That request is no longer pending.',
  authorization_not_open: 'That authorisation is no longer open.',
  authorization_expired: 'That authorisation has expired.',
  capture_exceeds_authorization: 'That is more than is still held.',
  forbidden: 'You are not allowed to do that.',
  email_taken: 'That email is already registered.',
  handle_taken: 'The handle for that email is already taken. Try another email address.',
  unauthenticated: 'Those details did not match an account.',
};

export function describeError(result) {
  const error = result && result.body && result.body.error;
  if (!error) return 'Something went wrong. Please try again.';
  return MESSAGES[error.code] || error.message || 'Something went wrong. Please try again.';
}

export function latestWins() {
  let epoch = 0;
  return async function run(load, apply, onError) {
    const mine = ++epoch;
    try {
      const data = await load();
      if (mine === epoch) apply(data);
    } catch (err) {
      if (mine === epoch && onError) onError(err);
    }
  };
}
