// The page frame shared by every route: brand, navigation, signed-in user.
import { h } from './dom.js';
import { signOut } from './session.js';

const NAV = [
  ['/', 'Wallet'],
  ['/requests', 'Requests'],
  ['/split', 'Split a bill'],
  ['/authorizations', 'Holds'],
];

function nav(active) {
  return h('nav', { class: 'nav', 'aria-label': 'Main' },
    NAV.map(([href, label]) => h('a', {
      href, class: 'nav-link', 'aria-current': href === active ? 'page' : null,
    }, label)));
}

function userChip(me) {
  return h('div', { class: 'user-chip' },
    h('span', { class: 'avatar', 'aria-hidden': 'true' }, (me.display_name || '?').trim().charAt(0).toUpperCase()),
    h('span', { class: 'user-names' },
      h('span', { class: 'user-name', testid: 'current-user', text: me.display_name }),
      h('span', { class: 'user-handle' }, h('span', { 'aria-hidden': 'true' }, '@'),
        h('span', { testid: 'current-handle', text: me.handle }))),
    h('button', { type: 'button', class: 'btn btn-quiet', testid: 'logout-button', onclick: signOut }, 'Log out'));
}

function guestLinks() {
  return h('div', { class: 'guest-links' },
    h('a', { href: '/login', class: 'btn btn-quiet' }, 'Log in'),
    h('a', { href: '/signup', class: 'btn btn-primary' }, 'Sign up'));
}

// Returns the <main> element pages render into.
export function renderShell(root, { me, active, title }) {
  document.title = `${title} · Pocketful`;
  const main = h('main', { id: 'main', class: 'page', tabindex: '-1' });
  root.replaceChildren(
    h('a', { class: 'skip-link', href: '#main' }, 'Skip to content'),
    h('header', { class: 'topbar' },
      h('div', { class: 'topbar-inner' },
        h('a', { href: '/', class: 'brand', 'aria-label': 'Pocketful home' },
          h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, 'P'), 'Pocketful'),
        me ? userChip(me) : guestLinks()),
      me ? nav(active) : null),
    main);
  return main;
}
