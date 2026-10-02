// `/login` and `/signup`.
import { call, describe, setToken } from '../api.js';
import { field, h, replace, tid } from '../dom.js';
import { app, loadMe, signIn } from '../session.js';

function authForm({ prefix, title, intro, fields, button, alt, run }) {
  const messages = h('div', { class: 'messages', 'aria-live': 'polite' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', ...tid(`${prefix}-submit`) }, button);
  const inputs = fields.map((f) => h('input', { type: f.type, autocomplete: f.autocomplete, ...tid(`${prefix}-${f.id}`) }));
  const form = h('form', { class: 'card form', novalidate: true, 'aria-labelledby': `${prefix}-title` },
    h('h1', { id: `${prefix}-title` }, title),
    h('p', { class: 'intro' }, intro),
    fields.map((f, i) => field(f.label, inputs[i])),
    h('div', { class: 'actions' }, submit),
    messages,
    h('p', { class: 'alt' }, alt));
  let busy = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    submit.disabled = true;
    replace(messages);
    const error = await run(Object.fromEntries(fields.map((f, i) => [f.id, inputs[i].value])));
    busy = false;
    submit.disabled = false;
    if (error) replace(messages, h('p', { class: 'msg msg-error', role: 'alert', ...tid('auth-error') }, error));
  });
  return h('div', { class: 'narrow' }, form);
}

async function finishSignIn(result, wrong) {
  if (result.kind === 'ok') {
    signIn(result.data);
    await loadMe();
    app.navigate('/', { replace: true });
    return null;
  }
  if (result.kind === 'refused') return result.code === 'unauthenticated' ? wrong : describe(result);
  return 'We could not reach the service. Please try again.';
}

export function renderLogin(root) {
  replace(root, authForm({
    prefix: 'login', title: 'Welcome back', intro: 'Sign in to your wallet.', button: 'Sign in',
    fields: [{ id: 'email', type: 'email', label: 'Email', autocomplete: 'username' },
      { id: 'password', type: 'password', label: 'Password', autocomplete: 'current-password' }],
    alt: [ 'New here? ', h('a', { href: '/signup', 'data-link': '' }, 'Create an account') ],
    run: async (v) => finishSignIn(await call('POST', '/auth/login', { body: { email: v.email, password: v.password }, auth: false }),
      'Email or password is incorrect.'),
  }));
  return () => {};
}

export function renderSignup(root) {
  replace(root, authForm({
    prefix: 'signup', title: 'Create your account', intro: 'Your handle is taken from the part of your email before the @.', button: 'Create account',
    fields: [{ id: 'email', type: 'email', label: 'Email', autocomplete: 'email' },
      { id: 'password', type: 'password', label: 'Password (at least 8 characters)', autocomplete: 'new-password' },
      { id: 'display-name', type: 'text', label: 'Display name', autocomplete: 'name' }],
    alt: [ 'Already have an account? ', h('a', { href: '/login', 'data-link': '' }, 'Sign in') ],
    run: async (v) => finishSignIn(await call('POST', '/auth/signup',
      { body: { email: v.email, password: v.password, display_name: v.displayName ?? v['display-name'] }, auth: false }), ''),
  }));
  return () => {};
}
