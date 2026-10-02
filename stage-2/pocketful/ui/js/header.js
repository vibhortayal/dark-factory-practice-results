// The site header: brand, navigation, who is signed in, sign out.
import { h, replace, tid } from './dom.js';
import { app, isSignedIn, signOut, storedUser } from './session.js';

const LINKS = [['/', 'Wallet'], ['/requests', 'Requests'], ['/split', 'Split'], ['/authorizations', 'Authorizations']];

export function renderHeader(el, path) {
  const user = app.me || storedUser();
  const link = (href, text) => h('a', { href, 'data-link': '', 'aria-current': href === path ? 'page' : null }, text);
  replace(el, h('div', { class: 'header-inner' },
    h('a', { href: '/', 'data-link': '', class: 'brand' }, h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, 'P'), 'Pocketful'),
    h('nav', { 'aria-label': 'Main' }, isSignedIn()
      ? LINKS.map(([href, text]) => link(href, text))
      : [link('/login', 'Sign in'), link('/signup', 'Sign up')]),
    isSignedIn() && user ? h('div', { class: 'who-am-i' },
      h('span', { class: 'user-name', ...tid('current-user') }, user.display_name),
      user.handle ? h('span', { class: 'user-handle' }, '@', h('span', { ...tid('current-handle') }, user.handle)) : null,
      h('button', { type: 'button', class: 'btn btn-quiet', ...tid('logout-button'), onclick: () => { signOut(); app.navigate('/login'); } }, 'Sign out')) : null));
}
