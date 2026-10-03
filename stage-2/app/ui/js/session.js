// Who is signed in, and how to sign out.
import { clearToken, request, setUnauthorizedHandler } from './api.js';

export function signOut() {
  clearToken();
  location.assign('/login');
}

export function redirectWhenSignedOut() {
  setUnauthorizedHandler(() => {
    clearToken();
    if (!['/login', '/signup'].includes(location.pathname)) location.replace('/login');
  });
}

export async function loadMe() {
  return request('GET', '/me');
}
