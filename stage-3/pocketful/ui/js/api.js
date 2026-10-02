// The only way the UI talks to the service: the documented JSON API with a bearer token.
const TOKEN_KEY = 'pocketful.token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (token) => (token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY));

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

// Result kinds: 'ok' | 'refused' (a confirmed 4xx with the error body) | 'uncertain'
// (network failure, timeout, 5xx or unreadable response: the outcome is unknown).
export async function call(method, path, { body, key, auth = true } = {}) {
  const headers = { Accept: 'application/json' };
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  let response;
  let data = null;
  try {
    response = await fetch(path, {
      method, headers, cache: 'no-store',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    try { data = text ? JSON.parse(text) : null; } catch { data = undefined; }
  } catch {
    return { kind: 'uncertain', status: 0 };
  }
  if (response.ok) {
    return data === undefined ? { kind: 'uncertain', status: response.status } : { kind: 'ok', status: response.status, data };
  }
  const error = data && data.error;
  if (response.status >= 400 && response.status < 500 && error && typeof error.code === 'string') {
    if (response.status === 401 && auth) onUnauthorized();
    return { kind: 'refused', status: response.status, code: error.code, message: error.message || error.code };
  }
  return { kind: 'uncertain', status: response.status };
}

export function newKey() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

// One idempotency key for as long as the form's content is unchanged, so a double
// click or a retry after a lost response replays instead of acting twice.
export class KeyedForm {
  constructor(form) {
    this.key = null;
    const renew = () => { this.key = null; };
    form.addEventListener('input', renew);
    form.addEventListener('change', renew);
  }

  current() {
    if (!this.key) this.key = newKey();
    return this.key;
  }
}

const FRIENDLY = {
  insufficient_funds: 'Not enough available funds for that.',
  not_found: 'We could not find that person or item.',
  self_payment: 'You cannot send money to yourself.',
  self_request: 'You cannot request money from yourself.',
  request_not_pending: 'That request is no longer pending.',
  forbidden: 'You are not allowed to do that.',
  authorization_not_open: 'That authorization is no longer open.',
  authorization_expired: 'That authorization has expired.',
  capture_exceeds_authorization: 'That is more than what is still on hold.',
  idempotency_key_reuse: 'That request was already sent with different details. Change a field and try again.',
  email_taken: 'That email is already registered.',
  handle_taken: 'The handle derived from that email is already taken.',
  unauthenticated: 'Your sign-in is not valid. Please sign in again.',
};

export function describe(result) {
  if (result.kind === 'uncertain') return 'We could not reach the service.';
  return FRIENDLY[result.code] || result.message || 'Something went wrong.';
}
