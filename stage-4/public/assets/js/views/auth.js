// "/login" and "/signup". Both always render their form, also when already signed in.
import { h, field } from '../lib/dom.js';
import { call } from '../lib/api.js';
import { setSession } from '../lib/session.js';
import { refusalText } from '../lib/feedback.js';

function authForm({ kind, title, lede, fields, submitLabel, busyLabel, path, alt }) {
  const inputs = fields.map((f) => ({ ...f, ...field({ id: f.testid, label: f.label, testid: f.testid, type: f.type || 'text', autocomplete: f.autocomplete, hint: f.hint }) }));
  const status = h('div', { class: 'form-status' });
  const button = h('button', { type: 'submit', class: 'btn btn-primary', testid: `${kind}-submit` }, submitLabel);
  const form = h('form', { class: 'card form-card auth-card', novalidate: true, 'aria-labelledby': `${kind}-title` },
    h('h1', { id: `${kind}-title`, class: 'card-title' }, title), h('p', { class: 'card-lede' }, lede),
    inputs.map((i) => i.wrap), status, button, h('p', { class: 'alt' }, alt));
  let busy = false;
  const showError = (text) => status.replaceChildren(text ? h('p', { class: 'alert alert-error', testid: 'auth-error', role: 'alert' }, text) : '');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy) return;
    showError('');
    const body = Object.fromEntries(inputs.map((i) => [i.name, i.input.value]));
    busy = true;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = busyLabel;
    const res = await call('POST', path, { body });
    busy = false;
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.textContent = submitLabel;
    if (res.kind === 'ok') {
      setSession(res.data.token);
      location.assign('/');
    } else if (res.kind === 'refused' || res.kind === 'unauthenticated') {
      showError(res.kind === 'refused' ? refusalText(res) : 'Those details did not match an account.');
    } else {
      showError('We could not reach the service. Check your connection and try again.');
    }
  });
  return form;
}

export function mountLogin(main) {
  main.append(authForm({
    kind: 'login', title: 'Log in', lede: 'Welcome back to Pocketful.', submitLabel: 'Log in', busyLabel: 'Logging in…', path: '/auth/login',
    fields: [
      { name: 'email', label: 'Email', testid: 'login-email', type: 'email', autocomplete: 'username' },
      { name: 'password', label: 'Password', testid: 'login-password', type: 'password', autocomplete: 'current-password' },
    ],
    alt: [h('span', {}, 'New here? '), h('a', { class: 'link', href: '/signup' }, 'Create an account')],
  }));
}

export function mountSignup(main) {
  main.append(authForm({
    kind: 'signup', title: 'Create your account', lede: 'Send, request and split money by handle.', submitLabel: 'Create account', busyLabel: 'Creating account…', path: '/auth/signup',
    fields: [
      { name: 'display_name', label: 'Your name', testid: 'signup-display-name', autocomplete: 'name' },
      { name: 'email', label: 'Email', testid: 'signup-email', type: 'email', autocomplete: 'username', hint: 'Your handle comes from the part before the @.' },
      { name: 'password', label: 'Password', testid: 'signup-password', type: 'password', autocomplete: 'new-password', hint: 'At least 8 characters.' },
    ],
    alt: [h('span', {}, 'Already have an account? '), h('a', { class: 'link', href: '/login' }, 'Log in')],
  }));
}
