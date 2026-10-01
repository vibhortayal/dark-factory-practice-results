// Entry point. Every URL serves the same shell; this picks the screen from the path.
import { h } from './lib/dom.js';
import { call } from './lib/api.js';
import { getToken, clearSession } from './lib/session.js';
import { formatAmount } from './money.js';
import { renderFrame } from './views/layout.js';
import { mountHome } from './views/home.js';
import { mountRequests } from './views/requests.js';
import { mountSplit } from './views/split.js';
import { mountAuthorizations } from './views/authorizations.js';
import { mountLogin, mountSignup } from './views/auth.js';

const PROTECTED = { '/': mountHome, '/requests': mountRequests, '/split': mountSplit, '/authorizations': mountAuthorizations };
const PUBLIC = { '/login': mountLogin, '/signup': mountSignup };

const route = location.pathname.replace(/\/+$/, '') || '/';
const root = document.getElementById('app');

function signOut() {
  clearSession();
  location.assign('/login');
}

async function boot() {
  const protectedView = PROTECTED[route];
  const view = protectedView || PUBLIC[route];
  if (!view) { location.replace('/'); return; }

  let me = null;
  let unreachable = false;
  if (getToken()) {
    const res = await call('GET', '/me');
    if (res.kind === 'ok') me = res.data;
    else if (res.kind === 'unauthenticated') clearSession();
    else unreachable = true;
  }
  if (protectedView && !me && !unreachable) { location.replace('/login'); return; }

  const main = renderFrame(root, { route, me, onLogout: signOut });
  if (protectedView && !me) {
    main.append(h('div', { class: 'card empty' },
      h('p', { class: 'empty-title' }, 'We could not reach Pocketful'),
      h('p', { class: 'muted' }, 'Check your connection, then try again.'),
      h('button', { type: 'button', class: 'btn btn-primary', onClick: () => location.reload() }, 'Try again')));
    return;
  }
  const ctx = {
    me,
    cfg: me ? { currency: me.currency, minor_units: me.minor_units } : null,
    fmt(minor) { return formatAmount(minor, this.cfg.minor_units, this.cfg.currency); },
    setMe(next) { this.me = next; this.cfg = { currency: next.currency, minor_units: next.minor_units }; },
    signOut,
  };
  view(main, ctx);
}

boot();
