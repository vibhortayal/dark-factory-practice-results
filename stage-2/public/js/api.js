// The only module that talks to the service. It uses the documented JSON API with a bearer
// token kept in localStorage. Outcomes are one of: data, ApiError (a refusal the service
// stated), or UncertainError (the result is unknown: network failure, 5xx, unreadable body).

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export class UncertainError extends Error {}

const TOKEN_KEY = 'pocketful.token';
const TIMEOUT_MS = 20000;

export const session = {
  get token() {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch (_) {
      return null;
    }
  },
  set(token) {
    localStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch (_) {
      /* storage unavailable: nothing to clear */
    }
  },
};

export function createApi({ onUnauthenticated = () => {}, fetchImpl = (...a) => fetch(...a) } = {}) {
  async function request(method, path, { body, key, authed = true } = {}) {
    const headers = { Accept: 'application/json' };
    if (authed && session.token) headers.Authorization = `Bearer ${session.token}`;
    if (key) headers['Idempotency-Key'] = key;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let response;
    let text;
    try {
      response = await fetchImpl(path, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      });
      text = await response.text();
    } catch (_) {
      throw new UncertainError('The connection was lost before we heard back.');
    } finally {
      clearTimeout(timer);
    }
    let data;
    try {
      data = text ? JSON.parse(text) : undefined;
    } catch (_) {
      data = undefined;
    }
    if (response.ok) {
      if (data === undefined) throw new UncertainError('The response could not be read.');
      return data;
    }
    const stated = data && data.error && typeof data.error.code === 'string';
    if (response.status >= 400 && response.status < 500 && stated) {
      if (response.status === 401 && authed) onUnauthenticated();
      throw new ApiError(response.status, data.error.code, data.error.message || data.error.code);
    }
    throw new UncertainError(`The service answered unexpectedly (${response.status}).`);
  }

  return {
    get: (path) => request('GET', path),
    post: (path, body, key) => request('POST', path, { body, key }),
    postPublic: (path, body) => request('POST', path, { body, authed: false }),
  };
}

/** Reads from a stage-1 era service lack available/held/total; fill them in. */
export function normalizeMe(me) {
  return {
    ...me,
    total: me.total ?? me.balance,
    available: me.available ?? me.balance,
    held: me.held ?? 0,
  };
}
