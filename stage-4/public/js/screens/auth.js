// `/login` and `/signup`.

import { h, textField, createFeedback, spinnerLabel, setChildren } from '../dom.js';
import { ApiError, session } from '../api.js';
import { refusalText } from '../text.js';

function authScreen({ api, main, title, intro, fields, submitLabel, testid, path, body, switchTo }) {
  const messages = h('div', { class: 'messages' });
  const feedback = createFeedback(messages, { error: 'auth-error', uncertain: 'auth-uncertain' });
  const button = h('button', { type: 'submit', class: 'btn btn-primary', testid }, submitLabel);
  let busy = false;
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    busy = true;
    button.disabled = true;
    button.replaceChildren(spinnerLabel('One moment…'));
    try {
      const result = await api.postPublic(path, body());
      session.set(result.token);
      location.assign('/');
      return;
    } catch (err) {
      feedback.show(err instanceof ApiError ? 'error' : 'uncertain', err instanceof ApiError ? refusalText(err) : 'We could not reach the service. Try again.');
    }
    busy = false;
    button.disabled = false;
    button.replaceChildren(submitLabel);
  }
  setChildren(main, 
    h('div', { class: 'auth' },
      h('h1', { class: 'page-title' }, title),
      h('form', { class: 'card form-card', novalidate: true, onsubmit: submit },
        h('p', { class: 'muted' }, intro), fields.map((f) => f.wrap), messages, h('div', { class: 'actions' }, button)),
      h('p', { class: 'muted center' }, switchTo)));
}

export function mountLogin({ api, main }) {
  const email = textField({ label: 'Email', testid: 'login-email', type: 'email', autocomplete: 'username' });
  const password = textField({ label: 'Password', testid: 'login-password', type: 'password', autocomplete: 'current-password' });
  authScreen({
    api, main, title: 'Welcome back', intro: 'Log in to see your wallet.', fields: [email, password],
    submitLabel: 'Log in', testid: 'login-submit', path: '/auth/login',
    body: () => ({ email: email.input.value, password: password.input.value }),
    switchTo: h('span', {}, 'New here? ', h('a', { href: '/signup' }, 'Create an account')),
  });
}

export function mountSignup({ api, main }) {
  const email = textField({ label: 'Email', testid: 'signup-email', type: 'email', autocomplete: 'email' });
  const name = textField({ label: 'Display name', testid: 'signup-display-name', autocomplete: 'name' });
  const password = textField({ label: 'Password', testid: 'signup-password', type: 'password', autocomplete: 'new-password', hint: 'At least 8 characters.' });
  authScreen({
    api, main, title: 'Create your account', intro: 'Your handle comes from your email, so friends can find you.',
    fields: [email, name, password], submitLabel: 'Create account', testid: 'signup-submit', path: '/auth/signup',
    body: () => ({ email: email.input.value, password: password.input.value, display_name: name.input.value }),
    switchTo: h('span', {}, 'Already have an account? ', h('a', { href: '/login' }, 'Log in')),
  });
}
