// Entry point: work out the screen from the URL, load who is signed in, render.
import { getToken, clearToken, NetworkError } from './api.js';
import { h } from './dom.js';
import { formatMinor } from './money.js';
import { renderShell } from './layout.js';
import { loadMe, redirectWhenSignedOut } from './session.js';
import { mountLogin, mountSignup } from './pages/auth.js';
import { mountAuthorizations } from './pages/authorizations.js';
import { mountRequests } from './pages/requests.js';
import { mountSplit } from './pages/split.js';
import { mountWallet } from './pages/wallet.js';

const PAGES = {
  '/': { title: 'Wallet', mount: mountWallet, auth: true },
  '/requests': { title: 'Requests', mount: mountRequests, auth: true },
  '/split': { title: 'Split a bill', mount: mountSplit, auth: true },
  '/authorizations': { title: 'Holds', mount: mountAuthorizations, auth: true },
  '/login': { title: 'Log in', mount: mountLogin, auth: false },
  '/signup': { title: 'Sign up', mount: mountSignup, auth: false },
};

async function start() {
  const root = document.getElementById('app');
  const path = location.pathname.replace(/\/+$/, '') || '/';
  const page = PAGES[path] || PAGES['/'];
  redirectWhenSignedOut();

  let me = null;
  if (getToken()) {
    try {
      const result = await loadMe();
      if (result.ok) me = result.body;
      else if (result.status === 401) clearToken();
    } catch (err) {
      if (!(err instanceof NetworkError)) throw err;
      renderShell(root, { me: null, active: path, title: page.title }).append(
        h('div', { class: 'msg msg-error', role: 'alert' }, 'We could not reach Pocketful. ',
          h('button', { class: 'btn btn-secondary', onclick: () => location.reload() }, 'Try again')));
      return;
    }
  }
  if (page.auth && !me) {
    location.replace('/login');
    return;
  }
  const main = renderShell(root, { me, active: path, title: page.title });
  const ctx = { me };
  ctx.format = (minor) => formatMinor(minor, ctx.me.minor_units, ctx.me.currency);
  page.mount(main, ctx);
}

start();
