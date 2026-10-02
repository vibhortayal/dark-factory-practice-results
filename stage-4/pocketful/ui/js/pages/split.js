// `/split`: split a bill; the preview is computed here by the same rule the server uses.
import { call, describe, KeyedForm } from '../api.js';
import { errorPanel, loadingPanel, money } from '../components.js';
import { field, h, replace, tid } from '../dom.js';
import { equalShares, parseDecimal } from '../money.js';
import { app, loadMe } from '../session.js';

const handlesOf = (text) => text.split(',').map((s) => s.trim().replace(/^@/, '')).filter(Boolean);

export function render(root) {
  let alive = true;

  async function start() {
    replace(root, loadingPanel('Loading…'));
    const result = await loadMe();
    if (!alive) return;
    if (result.kind !== 'ok') {
      if (result.kind !== 'refused') replace(root, errorPanel('This page could not be loaded.', start));
      return;
    }
    const me = app.me;
    const amount = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', ...tid('split-amount') });
    const handles = h('input', { type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', ...tid('split-handles') });
    const note = h('input', { type: 'text', autocomplete: 'off', maxlength: '200', ...tid('split-note') });
    const submit = h('button', { type: 'submit', class: 'btn btn-primary', ...tid('split-submit') }, 'Split the bill');
    const previewSlot = h('div', { class: 'preview-slot' });
    const messages = h('div', { class: 'messages', 'aria-live': 'polite' });
    const form = h('form', { class: 'card form', novalidate: true, 'aria-labelledby': 'split-title' },
      h('h2', { id: 'split-title' }, 'Split a bill'),
      h('p', { class: 'intro' }, 'You already paid. Ask everyone else for their equal share.'),
      field(`Total amount (${me.currency})`, amount),
      field('Who is in (handles, comma separated, in order)', handles, 'Include yourself to keep a share. The first people get any extra cent.'),
      field('Note (optional)', note),
      previewSlot,
      h('div', { class: 'actions' }, submit),
      messages);
    const keyed = new KeyedForm(form);
    let busy = false;

    const say = (kind, id, text) => replace(messages, h('p', { class: `msg msg-${kind}`, role: kind === 'ok' ? 'status' : 'alert', ...tid(id) }, text));

    function paintPreview() {
      const parsed = parseDecimal(amount.value, me.minor_units);
      const list = handlesOf(handles.value);
      if (!parsed.ok || parsed.minor < 1 || list.length === 0) {
        replace(previewSlot, h('p', { class: 'hint', ...tid('split-preview-hint') }, 'Enter an amount and at least one handle to preview the shares.'));
        return;
      }
      const shares = equalShares(parsed.minor, list.length);
      replace(previewSlot, h('div', { class: 'preview', ...tid('split-preview') },
        h('h3', {}, 'Each share'),
        h('ul', {}, list.map((handle, i) => h('li', {}, h('span', { class: 'who' }, handle),
          h('span', { class: 'amount', ...tid(`split-share-${handle}`) }, money(me, shares[i])))))));
    }
    form.addEventListener('input', paintPreview);
    paintPreview();

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (busy) return;
      const parsed = parseDecimal(amount.value, me.minor_units);
      if (!parsed.ok) { say('error', 'split-error', parsed.error); return; }
      const body = { amount: parsed.minor, participant_handles: handlesOf(handles.value) };
      if (note.value !== '') body.note = note.value;
      busy = true;
      submit.disabled = true;
      replace(messages, h('p', { class: 'msg msg-pending', role: 'status' }, 'Working on it…'));
      const result = await call('POST', '/splits', { body, key: keyed.current() });
      busy = false;
      submit.disabled = false;
      if (result.kind === 'ok') {
        const count = result.data.requests.length;
        replace(messages, h('p', { class: 'msg msg-ok', role: 'status', ...tid('split-success') },
          `Split created: ${count} request${count === 1 ? '' : 's'} sent. `,
          h('a', { href: '/requests', 'data-link': '' }, 'See requests')));
      } else if (result.kind === 'refused') {
        say('error', 'split-error', describe(result));
      } else {
        say('uncertain', 'split-uncertain', 'We could not confirm whether the split was created. Press the button again to retry safely.');
      }
    });
    replace(root, h('h1', {}, 'Split a bill'), h('div', { class: 'narrow' }, form));
  }

  start();
  return () => { alive = false; };
}
