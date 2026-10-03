// /login and /signup.
import { describeError, request, setToken } from '../api.js';
import { h } from '../dom.js';

function authForm({ prefix, title, intro, fields, submitLabel, path, toBody, footer }) {
  const error = h('div', { class: 'msg msg-error', role: 'alert', hidden: true });
  const inputs = fields.map((f) => h('input', {
    id: `${prefix}-${f.name}`, testid: `${prefix}-${f.name}`, type: f.type, autocomplete: f.autocomplete,
    autocapitalize: 'none', spellcheck: 'false',
  }));
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', testid: `${prefix}-submit` }, submitLabel);

  function setError(text) {
    error.hidden = !text;
    if (text) { error.setAttribute('data-testid', 'auth-error'); error.textContent = text; }
    else { error.removeAttribute('data-testid'); error.textContent = ''; }
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError('');
    submit.disabled = true;
    try {
      const values = Object.fromEntries(fields.map((f, i) => [f.name, inputs[i].value]));
      const result = await request('POST', path, { body: toBody(values), auth: false });
      if (result.ok) {
        setToken(result.body.token);
        location.assign('/');
        return;
      }
      setError(result.status === 422 ? validationText(result) : describeError(result));
    } catch {
      setError('We could not reach Pocketful. Check your connection and try again.');
    } finally {
      submit.disabled = false;
    }
  }

  return h('section', { class: 'card auth-card' },
    h('h1', { class: 'card-title' }, title),
    h('p', { class: 'card-intro' }, intro),
    h('form', { class: 'form', novalidate: true, onsubmit: onSubmit },
      fields.map((f, i) => h('div', { class: 'field' }, h('label', { for: inputs[i].id }, f.label), inputs[i],
        f.hint ? h('p', { class: 'hint' }, f.hint) : null)),
      h('div', { class: 'form-actions' }, submit), error),
    footer);
}

function validationText(result) {
  const message = result.body && result.body.error && result.body.error.message;
  return message ? message.charAt(0).toUpperCase() + message.slice(1) + '.' : 'Please check your details.';
}

export function mountLogin(main) {
  main.append(authForm({
    prefix: 'login', title: 'Welcome back', intro: 'Log in to see your wallet.',
    fields: [
      { name: 'email', label: 'Email', type: 'email', autocomplete: 'username' },
      { name: 'password', label: 'Password', type: 'password', autocomplete: 'current-password' },
    ],
    submitLabel: 'Log in', path: '/auth/login', toBody: (v) => v,
    footer: h('p', { class: 'hint center' }, 'New here? ', h('a', { href: '/signup' }, 'Create an account')),
  }));
}

export function mountSignup(main) {
  main.append(authForm({
    prefix: 'signup', title: 'Create your account', intro: 'Start sending, requesting and splitting money.',
    fields: [
      { name: 'display-name', label: 'Your name', type: 'text', autocomplete: 'name' },
      { name: 'email', label: 'Email', type: 'email', autocomplete: 'email',
        hint: 'Your handle comes from the part before the @.' },
      { name: 'password', label: 'Password', type: 'password', autocomplete: 'new-password',
        hint: 'At least 8 characters.' },
    ],
    submitLabel: 'Sign up', path: '/auth/signup',
    toBody: (v) => ({ email: v.email, password: v.password, display_name: v['display-name'] }),
    footer: h('p', { class: 'hint center' }, 'Already have an account? ', h('a', { href: '/login' }, 'Log in')),
  }));
}
