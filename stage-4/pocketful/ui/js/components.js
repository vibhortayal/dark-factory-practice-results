// Shared pieces: wallet card, send-style forms, status badges, state panels.
import { call, describe, KeyedForm } from './api.js';
import { field, h, replace, tid } from './dom.js';
import { formatAmount, parseDecimal } from './money.js';

export const money = (me, minor) => formatAmount(minor, me.minor_units, me.currency);

export function loadingPanel(text = 'Loading…') {
  return h('div', { class: 'state state-loading', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), text);
}

export function errorPanel(text, onRetry, id) {
  return h('div', { class: 'state state-error', role: 'alert', ...tid(id || 'load-error') },
    h('p', {}, text), h('button', { type: 'button', class: 'btn btn-secondary', onclick: onRetry }, 'Try again'));
}

export function emptyPanel(id, title, text) {
  return h('div', { class: 'state state-empty', ...tid(id) }, h('p', { class: 'state-title' }, title), text ? h('p', {}, text) : null);
}

export function badge(text, kind) {
  return h('span', { class: `badge badge-${kind}` }, text);
}

// The wallet: available is the headline; total and held are secondary.
export function walletCard(me, { onRefresh, refreshing }) {
  return h('section', { class: 'card wallet', 'aria-labelledby': 'wallet-title' },
    h('div', { class: 'wallet-top' },
      h('h2', { id: 'wallet-title', class: 'eyebrow' }, 'Available to spend'),
      onRefresh ? h('button', { type: 'button', class: 'btn btn-quiet', ...tid('wallet-refresh'),
        'aria-busy': refreshing ? 'true' : null, onclick: onRefresh }, refreshing ? 'Refreshing…' : 'Refresh') : null),
    h('p', { class: 'wallet-available', ...tid('wallet-available'), 'data-amount': me.available }, money(me, me.available)),
    h('dl', { class: 'wallet-secondary' },
      h('div', {}, h('dt', {}, 'Total balance'),
        h('dd', { ...tid('wallet-balance'), 'data-amount': me.total }, money(me, me.total))),
      me.held > 0 ? h('div', { class: 'held' }, h('dt', {}, 'On hold'),
        h('dd', { ...tid('wallet-held'), 'data-amount': me.held }, money(me, me.held))) : null));
}

// A form that sends money-shaped data through an idempotent POST.
//   prefix: test-id prefix; handleKey: body key for the handle; path: endpoint
export function sendForm(opts, me, onDone) {
  const { prefix, title, intro, handleLabel, handleKey, path, button, withVisibility, uncertainText, successText } = opts;
  const handle = h('input', { type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', ...tid(`${prefix}-handle`) });
  const amount = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: me.minor_units ? `0.${'0'.repeat(me.minor_units)}` : '0', ...tid(`${prefix}-amount`) });
  const note = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', ...tid(`${prefix}-note`) });
  const visibility = withVisibility ? h('select', { ...tid(`${prefix}-visibility`) },
    h('option', { value: 'public' }, 'Public — shown in the activity feed'),
    h('option', { value: 'private' }, 'Private — only you and the recipient')) : null;
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', ...tid(`${prefix}-submit`) }, button);
  const messages = h('div', { class: 'messages', 'aria-live': 'polite' });
  const form = h('form', { class: 'card form', novalidate: true, 'aria-labelledby': `${prefix}-title` },
    h('h2', { id: `${prefix}-title` }, title),
    intro ? h('p', { class: 'intro' }, intro) : null,
    field(handleLabel, handle),
    field(`Amount (${me.currency})`, amount),
    field('Note (optional)', note),
    visibility ? field('Who can see it', visibility) : null,
    h('div', { class: 'actions' }, submit),
    messages);
  const keyed = new KeyedForm(form);
  let busy = false;

  const say = (kind, id, text) => replace(messages, h('p', { class: `msg msg-${kind}`, role: kind === 'ok' ? 'status' : 'alert', ...tid(id) }, text));

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy) return;
    const parsed = parseDecimal(amount.value, me.minor_units);
    if (!parsed.ok) { say('error', `${prefix}-error`, parsed.error); return; }
    const body = { [handleKey]: handle.value.trim().replace(/^@/, ''), amount: parsed.minor };
    if (note.value !== '') body.note = note.value;
    if (visibility) body.visibility = visibility.value;
    busy = true;
    submit.disabled = true;
    submit.setAttribute('aria-busy', 'true');
    replace(messages, h('p', { class: 'msg msg-pending', role: 'status' }, 'Working on it…'));
    const result = await call('POST', path, { body, key: keyed.current() });
    busy = false;
    submit.disabled = false;
    submit.removeAttribute('aria-busy');
    if (result.kind === 'ok') {
      say('ok', `${prefix}-success`, successText(result.data, body));
    } else if (result.kind === 'refused') {
      say('error', `${prefix}-error`, describe(result));
    } else {
      say('uncertain', `${prefix}-uncertain`, uncertainText);
    }
    if (result.kind !== 'uncertain') onDone(result);
  });
  return form;
}
