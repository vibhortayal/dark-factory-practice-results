// Page chrome shared by every screen: brand, navigation, signed-in identity.

import { h } from '../dom.js';

const NAV = [
  ['/', 'Wallet'],
  ['/requests', 'Requests'],
  ['/split', 'Split'],
  ['/authorizations', 'Holds'],
];

export function renderShell({ path, me, onLogout }) {
  const nav = h('nav', { class: 'nav', 'aria-label': 'Main' },
    me
      ? NAV.map(([href, label]) => h('a', { href, class: 'nav-link', 'aria-current': href === path ? 'page' : null }, label))
      : [
          h('a', { href: '/login', class: 'nav-link', 'aria-current': path === '/login' ? 'page' : null }, 'Log in'),
          h('a', { href: '/signup', class: 'nav-link', 'aria-current': path === '/signup' ? 'page' : null }, 'Sign up'),
        ]);

  const identity = me
    ? h('div', { class: 'identity' },
        h('span', { class: 'avatar', 'aria-hidden': 'true' }, Array.from(me.display_name)[0] || '?'),
        h('span', { class: 'who' },
          h('span', { class: 'who-name', testid: 'current-user' }, me.display_name),
          h('span', { class: 'who-handle', testid: 'current-handle' }, me.handle)),
        h('button', { type: 'button', class: 'btn btn-quiet', testid: 'logout-button', onclick: onLogout }, 'Log out'))
    : null;

  const main = h('main', { id: 'main', class: 'main', tabindex: '-1' });
  const root = h('div', { class: 'page' },
    h('a', { class: 'skip', href: '#main' }, 'Skip to content'),
    h('header', { class: 'header' },
      h('div', { class: 'header-inner' },
        h('a', { class: 'brand', href: me ? '/' : '/login' }, h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, 'P'), h('span', {}, 'Pocketful')),
        nav, identity)),
    main);
  return { root, main };
}
