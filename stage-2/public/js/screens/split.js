// `/split`: split a bill; the preview shows exactly the shares the server will compute.

import { h, createFeedback, spinnerLabel } from '../dom.js';
import { createModel } from '../model.js';
import { normalizeMe, ApiError } from '../api.js';
import { RetryIdentity } from '../retry.js';
import { refusalText } from '../text.js';
import { parseDecimal, splitShares, parseHandles, formatAmount } from '../money.js';
import { textField } from '../dom.js';
import { moneyField } from '../components/forms.js';

export function mountSplit({ api, me, main }) {
  const model = createModel({ api, initial: { me }, sources: { me: (a) => a.get('/me').then(normalizeMe) } });
  const retry = new RetryIdentity();
  const amount = moneyField('Total amount', 'split-amount');
  const handles = textField({ label: 'Who shares it (handles, separated by commas, in order)', testid: 'split-handles', autocomplete: 'off', placeholder: 'ada, bob, cy' });
  const note = textField({ label: 'Note (optional)', testid: 'split-note', autocomplete: 'off', placeholder: 'What is it for?' });
  const preview = h('div', { class: 'preview', testid: 'split-preview', 'aria-live': 'polite' });
  const messages = h('div', { class: 'messages' });
  const feedback = createFeedback(messages, { error: 'split-error', uncertain: 'split-uncertain', success: 'split-success' });
  const button = h('button', { type: 'submit', class: 'btn btn-primary', testid: 'split-submit' }, 'Split the bill');
  let busy = false;

  const current = () => {
    const meNow = model.state.me;
    const parsed = parseDecimal(amount.input.value, meNow.minor_units);
    return { meNow, parsed, list: parseHandles(handles.input.value) };
  };

  function renderPreview() {
    const { meNow, parsed, list } = current();
    if (!parsed.ok || list.length === 0) {
      preview.replaceChildren(h('p', { class: 'muted' }, 'Enter an amount and at least one handle to see each share.'));
      return;
    }
    const shares = splitShares(parsed.minor, list.length);
    const seen = new Set();
    preview.replaceChildren(
      h('p', { class: 'eyebrow' }, 'Each share'),
      h('ul', { class: 'shares' }, list.map((handle, i) => {
        if (seen.has(handle)) return h('li', { class: 'share share-dup' }, `${handle} is listed twice`);
        seen.add(handle);
        return h('li', { class: 'share' }, h('span', { class: 'share-who' }, handle), h('span', { class: 'share-amount', testid: `split-share-${handle}` }, formatAmount(shares[i], meNow.minor_units, meNow.currency)));
      })));
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const { parsed, list } = current();
    if (!parsed.ok) return feedback.show('error', parsed.reason);
    if (list.length === 0) return feedback.show('error', 'Enter at least one handle.');
    const body = { amount: parsed.minor, participant_handles: list, note: note.input.value };
    const key = retry.keyFor(JSON.stringify([amount.input.value, handles.input.value, note.input.value]));
    busy = true;
    button.disabled = true;
    button.replaceChildren(spinnerLabel('Splitting…'));
    try {
      const result = await api.post('/splits', body, key);
      const count = result.requests.length;
      feedback.show('success', count === 0 ? 'Split recorded. Nobody else was asked.' : `Split recorded. ${count} ${count === 1 ? 'request was' : 'requests were'} sent.`);
    } catch (err) {
      if (err instanceof ApiError) feedback.show('error', refusalText(err));
      else feedback.show('uncertain', 'We could not confirm whether the split went through. Submit the same form again; it will only be applied once.');
    } finally {
      busy = false;
      button.disabled = false;
      button.replaceChildren('Split the bill');
    }
  }

  for (const f of [amount, handles]) f.input.addEventListener('input', renderPreview);
  model.subscribe(renderPreview);

  main.replaceChildren(
    h('h1', { class: 'page-title' }, 'Split a bill'),
    h('form', { class: 'card form-card', novalidate: true, onsubmit: submit },
      h('p', { class: 'muted' }, 'You have already paid the bill. Everyone else on the list is asked for their share; you are not asked, whether or not you list yourself.'),
      amount.wrap, handles.wrap, note.wrap, preview, messages, h('div', { class: 'actions' }, button)),
  );
}
