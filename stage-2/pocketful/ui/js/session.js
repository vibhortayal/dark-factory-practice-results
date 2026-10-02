// Who is signed in and the wallet numbers last read for them.
import { call, getToken, setToken } from './api.js';

const USER_KEY = 'pocketful.user';
const listeners = new Set();

export const app = {
  me: null,          // normalised /me
  navigate: () => {},
};

export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function notify() { listeners.forEach((fn) => fn()); }

// Accept both the stage-2 shape and a stage-1 shape (no total/available/held).
export function normaliseMe(me) {
  const total = me.total ?? me.balance;
  return { ...me, total, available: me.available ?? me.balance, held: me.held ?? 0 };
}

export function storedUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; }
}

export function signIn(session) {
  setToken(session.token);
  const user = { user_id: session.user_id, display_name: session.display_name };
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  app.me = null;
  notify();
}

export function signOut() {
  setToken(null);
  localStorage.removeItem(USER_KEY);
  app.me = null;
  notify();
}

export function isSignedIn() { return Boolean(getToken()); }

export function setMe(me) {
  app.me = normaliseMe(me);
  localStorage.setItem(USER_KEY, JSON.stringify({
    user_id: me.user_id, display_name: me.display_name, handle: me.handle }));
  notify();
}

// Read /me once per page load (or when forced). Returns the result of the call.
export async function loadMe() {
  const result = await call('GET', '/me');
  if (result.kind === 'ok') setMe(result.data);
  return result;
}
