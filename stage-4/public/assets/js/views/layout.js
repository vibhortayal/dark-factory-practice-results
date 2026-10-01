// The page frame: brand, navigation, and (when signed in) who you are and how to leave.
import { h } from '../lib/dom.js';

const NAV = [
  { href: '/', label: 'Wallet' },
  { href: '/requests', label: 'Requests' },
  { href: '/split', label: 'Split' },
  { href: '/authorizations', label: 'Holds' },
];

export function renderFrame(root, { route, me, onLogout }) {
  const nav = h('nav', { class: 'nav', 'aria-label': 'Main' },
    me
      ? NAV.map((n) => h('a', { class: 'nav-link', href: n.href, 'aria-current': n.href === route ? 'page' : null }, n.label))
      : [h('a', { class: 'nav-link', href: '/login', 'aria-current': route === '/login' ? 'page' : null }, 'Log in'),
         h('a', { class: 'nav-link', href: '/signup', 'aria-current': route === '/signup' ? 'page' : null }, 'Sign up')]);
  const who = me
    ? h('div', { class: 'who' },
      h('p', { class: 'who-name' }, h('span', { testid: 'current-user' }, me.display_name)),
      h('p', { class: 'who-handle' }, '@', h('span', { testid: 'current-handle' }, me.handle)),
      h('button', { type: 'button', class: 'btn btn-quiet', testid: 'logout-button', onClick: onLogout }, 'Log out'))
    : null;
  const main = h('main', { class: 'main', id: 'main' });
  root.replaceChildren(
    h('a', { class: 'skip', href: '#main' }, 'Skip to content'),
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-inner' }, h('a', { class: 'brand', href: '/' }, h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, 'P'), 'Pocketful'), who, nav)),
    main);
  return main;
}
