// "/split": split a bill equally; the preview uses the very module the server uses.
import { h, field } from '../lib/dom.js';
import { call } from '../lib/api.js';
import { RetryIdentity } from '../lib/retry.js';
import { feedback, refusalText, UNCERTAIN_TEXT } from '../lib/feedback.js';
import { parseAmount } from '../money.js';
import { equalShares } from '../split.js';
import { cleanHandle } from './forms.js';

export function mountSplit(main, ctx) {
  const retry = new RetryIdentity();
  const amount = field({ id: 'split-amount', label: 'Total amount', testid: 'split-amount', inputmode: 'decimal', autocomplete: 'off', placeholder: ctx.cfg.minor_units === 0 ? '3000' : '30.00', hint: `In ${ctx.cfg.currency}` });
  const handles = field({ id: 'split-handles', label: 'Participants', testid: 'split-handles', autocomplete: 'off', placeholder: 'ada, bob, cy', hint: 'Handles separated by commas. The first people get any odd unit.' });
  const note = field({ id: 'split-note', label: 'Note (optional)', testid: 'split-note', autocomplete: 'off', maxlength: 400 });
  const preview = h('div', { class: 'preview', testid: 'split-preview', 'aria-live': 'polite' });
  const status = h('div', { class: 'form-status' });
  const fb = feedback(status, 'split');
  const button = h('button', { type: 'submit', class: 'btn btn-primary', testid: 'split-submit' }, 'Split the bill');

  const parseHandles = () => handles.input.value.split(',').map(cleanHandle).filter((x) => x !== '');

  function inspect() {
    const list = parseHandles();
    const parsed = parseAmount(amount.input.value, ctx.cfg.minor_units);
    if (!parsed.ok) return { error: parsed.error };
    if (list.length === 0) return { error: 'Add at least one participant.' };
    if (new Set(list).size !== list.length) return { error: 'Each participant can only be listed once.' };
    return { minor: parsed.minor, list };
  }

  function renderPreview() {
    const s = inspect();
    if (s.error) {
      preview.replaceChildren(h('p', { class: 'muted' }, amount.input.value.trim() === '' && handles.input.value.trim() === '' ? 'Enter an amount and who is splitting it to see each share.' : s.error));
      return;
    }
    const shares = equalShares(s.minor, s.list.length);
    preview.replaceChildren(
      h('p', { class: 'preview-title' }, 'Each share'),
      h('ul', { class: 'rows compact' }, s.list.map((handle, i) => h('li', { class: 'row-item' },
        h('span', { class: 'row-title' }, `@${handle}`),
        h('span', { class: 'row-amount', testid: `split-share-${handle}` }, ctx.fmt(shares[i]))))));
  }

  const form = h('form', { class: 'card form-card', novalidate: true, 'aria-labelledby': 'split-title' },
    h('h2', { id: 'split-title', class: 'card-title' }, 'Split a bill'),
    h('p', { class: 'card-lede' }, 'You already paid. Ask everyone else for their share.'),
    amount.wrap, handles.wrap, note.wrap, preview, status, button);
  for (const el of [amount.input, handles.input]) el.addEventListener('input', renderPreview);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (retry.busy) return;
    const s = inspect();
    if (s.error) { fb.error(s.error); return; }
    const body = { amount: s.minor, participant_handles: s.list, note: note.input.value };
    const key = retry.keyFor(JSON.stringify([amount.input.value, handles.input.value, note.input.value]));
    retry.busy = true;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = 'Splitting…';
    const res = await call('POST', '/splits', { body, key });
    retry.busy = false;
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.textContent = 'Split the bill';
    if (res.kind === 'ok') {
      const n = res.data.requests.length;
      fb.success(`Split ${ctx.fmt(res.data.amount)} ${n === 0 ? 'with nobody else.' : `and asked ${n} ${n === 1 ? 'person' : 'people'} for their share.`}${res.status === 200 ? ' (This split had already been created.)' : ''}`);
      status.append(h('a', { class: 'link', href: '/requests' }, 'View your requests'));
    } else if (res.kind === 'refused') {
      fb.error(refusalText(res));
    } else if (res.kind === 'unauthenticated') {
      ctx.signOut();
    } else {
      fb.uncertain(UNCERTAIN_TEXT);
    }
  });

  main.append(h('h1', { class: 'page-title' }, 'Split'), form);
  renderPreview();
}
