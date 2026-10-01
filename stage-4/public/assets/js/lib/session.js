// The bearer token lives in localStorage so the session survives navigation and reloads.
const KEY = 'pocketful.session';

export function getToken() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || 'null')?.token || null;
  } catch {
    return null;
  }
}
export const setSession = (token) => localStorage.setItem(KEY, JSON.stringify({ token }));
export const clearSession = () => localStorage.removeItem(KEY);
