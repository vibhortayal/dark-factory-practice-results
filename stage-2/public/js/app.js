// Entry point: pick the screen for the URL, sign the browser in from its stored token, mount.

import { createApi, session, normalizeMe, UncertainError } from './api.js';
import { renderShell } from './components/shell.js';
import { loadFailure } from './components/parts.js';
import { mountWallet } from './screens/wallet.js';
import { mountRequests } from './screens/requests.js';
import { mountSplit } from './screens/split.js';
import { mountAuthorizations } from './screens/authorizations.js';
import { mountLogin, mountSignup } from './screens/auth.js';

const SCREENS = {
  '/': { title: 'Wallet', protected: true, mount: mountWallet },
  '/requests': { title: 'Requests', protected: true, mount: mountRequests },
  '/split': { title: 'Split a bill', protected: true, mount: mountSplit },
  '/authorizations': { title: 'Holds', protected: true, mount: mountAuthorizations },
  '/login': { title: 'Log in', protected: false, mount: mountLogin },
  '/signup': { title: 'Sign up', protected: false, mount: mountSignup },
};

async function start() {
  const path = location.pathname.replace(/\/+$/, '') || '/';
  const screen = SCREENS[path] || SCREENS['/'];
  document.title = `${screen.title} · Pocketful`;
  const app = document.getElementById('app');

  const api = createApi({
    onUnauthenticated: () => {
      session.clear();
      if (screen.protected) location.replace('/login');
    },
  });

  let me = null;
  if (session.token) {
    try {
      me = normalizeMe(await api.get('/me'));
    } catch (err) {
      if (!(err instanceof UncertainError)) me = null; // 401: the token is gone, the browser is signed out
      else {
        const { root, main } = renderShell({ path, me: null, onLogout() {} });
        main.append(loadFailure('We could not reach the service.', () => location.reload()));
        app.replaceChildren(root);
        app.removeAttribute('aria-busy');
        return;
      }
    }
  }
  if (screen.protected && !me) {
    location.replace('/login');
    return;
  }

  const shell = renderShell({
    path, me,
    onLogout() {
      session.clear();
      location.assign('/login');
    },
  });
  app.replaceChildren(shell.root);
  app.removeAttribute('aria-busy');
  screen.mount({ api, me, main: shell.main });
}

start();
