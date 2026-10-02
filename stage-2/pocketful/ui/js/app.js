// Client-side router and bootstrap. Every screen is rendered from the JSON API.
import { setUnauthorizedHandler } from './api.js';
import { replace } from './dom.js';
import { renderHeader } from './header.js';
import { renderLogin, renderSignup } from './pages/auth.js';
import { render as authorizations } from './pages/authorizations.js';
import { render as home } from './pages/home.js';
import { render as requests } from './pages/requests.js';
import { render as split } from './pages/split.js';
import { app, isSignedIn, loadMe, onChange, signOut } from './session.js';

const ROUTES = {
  '/': { render: home, private: true },
  '/requests': { render: requests, private: true },
  '/split': { render: split, private: true },
  '/authorizations': { render: authorizations, private: true },
  '/login': { render: renderLogin },
  '/signup': { render: renderSignup },
};

const main = document.getElementById('main');
const header = document.getElementById('site-header');
let cleanup = () => {};
let current = '/';

function show() {
  let path = location.pathname.replace(/\/+$/, '') || '/';
  let route = ROUTES[path];
  if (!route) { path = '/'; route = ROUTES['/']; }
  if (route.private && !isSignedIn()) {
    history.replaceState({}, '', '/login');
    path = '/login';
    route = ROUTES['/login'];
  }
  current = path;
  cleanup();
  renderHeader(header, path);
  document.title = `Pocketful — ${{ '/': 'Wallet', '/requests': 'Requests', '/split': 'Split', '/authorizations': 'Authorizations', '/login': 'Sign in', '/signup': 'Sign up' }[path]}`;
  cleanup = route.render(main, app) || (() => {});
}

app.navigate = (to, { replace: swap = false } = {}) => {
  if (swap) history.replaceState({}, '', to); else history.pushState({}, '', to);
  show();
};

document.addEventListener('click', (event) => {
  const link = event.target.closest && event.target.closest('a[data-link]');
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  app.navigate(link.getAttribute('href'));
  main.focus({ preventScroll: true });
});
window.addEventListener('popstate', show);

setUnauthorizedHandler(() => {
  if (!isSignedIn()) return;
  signOut();   // the header updates itself; only a private screen has to move
  if (ROUTES[current] && ROUTES[current].private) app.navigate('/login', { replace: true });
});

onChange(() => renderHeader(header, current));

show();
if (isSignedIn()) loadMe();
