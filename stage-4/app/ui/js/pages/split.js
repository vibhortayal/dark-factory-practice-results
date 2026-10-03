// `/split`: split a bill; the preview is computed with the same rule the server uses.
import { NetworkError, describeError, newKey, request } from '../api.js';
import { clear, h, icon } from '../dom.js';
import { equalSplit, parseAmount } from '../money.js';

function readHandles(text) {
  return text.split(',').map((t) => t.trim().replace(/^@/, '').toLowerCase()).filter(Boolean);
}

export function mountSplit(main, ctx) {
  const amount = h('input', { id: 'split-amount', testid: 'split-amount', type: 'text', inputmode: 'decimal', autocomplete: 'off',
    placeholder: ctx.me.minor_units === 0 ? '3000' : `30.${'0'.repeat(ctx.me.minor_units)}` });
  const handles = h('input', { id: 'split-handles', testid: 'split-handles', type: 'text', autocomplete: 'off',
    autocapitalize: 'none', spellcheck: 'false', placeholder: 'ada, bob, cy' });
  const note = h('input', { id: 'split-note', testid: 'split-note', type: 'text', maxlength: '200', autocomplete: 'off',
    placeholder: 'What was it for? (optional)' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', testid: 'split-submit' }, 'Split and request');
  const previewBox = h('div', { class: 'preview-box', 'aria-live': 'polite' });
  const error = h('div', { class: 'msg msg-error', role: 'alert', hidden: true });
  const uncertain = h('div', { class: 'msg msg-uncertain', role: 'status', hidden: true });
  const success = h('div', { class: 'msg msg-success', role: 'status', hidden: true });
  let attempt = null;
  let busy = false;

  function currentShares() {
    const parsed = parseAmount(amount.value, ctx.me.minor_units);
    const people = readHandles(handles.value);
    if (!parsed.ok || !people.length || new Set(people).size !== people.length) return null;
    const shares = equalSplit(parsed.minor, people.length);
    return { total: parsed.minor, people, shares };
  }

  function renderPreview() {
    const data = currentShares();
    clear(previewBox);
    if (!data) {
      previewBox.append(h('p', { class: 'hint' }, 'Enter an amount and the people to split between to see each share.'));
      return;
    }
    previewBox.append(h('div', { class: 'preview', testid: 'split-preview' },
      h('h3', { class: 'section-title' }, 'Each person pays'),
      h('ul', { class: 'shares' }, data.people.map((who, i) => h('li', { class: 'share' },
        h('span', { class: 'share-who' }, `@${who}`),
        h('span', { class: 'share-amount', testid: `split-share-${who}`, text: ctx.format(data.shares[i]) })))),
      h('p', { class: 'hint' }, 'Everyone except you gets a request for their share. If it does not divide evenly, the first people in the list pay one unit more.')));
  }

  function say(box, testid, text, glyph) {
    for (const other of [error, uncertain, success]) { other.hidden = true; other.removeAttribute('data-testid'); other.replaceChildren(); }
    if (!box) return;
    box.hidden = false;
    box.setAttribute('data-testid', testid);
    box.replaceChildren(icon(glyph), h('span', {}, text));
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (busy) return;
    const parsed = parseAmount(amount.value, ctx.me.minor_units);
    const people = readHandles(handles.value);
    if (!parsed.ok) { say(error, 'split-error', parsed.message, 'alert'); return; }
    if (!people.length) { say(error, 'split-error', 'Enter at least one handle, separated by commas.', 'alert'); return; }
    const body = { amount: parsed.minor, participant_handles: people, note: note.value };
    const bodyKey = JSON.stringify(body);
    if (attempt && attempt.bodyKey === bodyKey && attempt.status === 'success') {
      say(success, 'split-success', 'This split was already created. Change a field to create another.', 'check');
      return;
    }
    if (!attempt || attempt.bodyKey !== bodyKey || attempt.status === 'refused') attempt = { bodyKey, key: newKey(), status: 'new' };
    const mine = attempt;
    busy = true;
    submit.disabled = true;
    say(null);
    try {
      const result = await request('POST', '/splits', { body, key: mine.key });
      if (result.ok) {
        mine.status = 'success';
        const count = result.body.requests.length;
        say(success, 'split-success', `Split created. ${count} request${count === 1 ? '' : 's'} sent.`, 'check');
      } else if (result.status >= 500) {
        mine.status = 'uncertain';
        say(uncertain, 'split-uncertain', 'We could not confirm the split. Press the button again to retry safely.', 'clock');
      } else {
        mine.status = 'refused';
        say(error, 'split-error', describeError(result), 'alert');
      }
    } catch (err) {
      if (!(err instanceof NetworkError)) throw err;
      mine.status = 'uncertain';
      say(uncertain, 'split-uncertain', 'We could not confirm the split. Press the button again to retry safely.', 'clock');
    } finally {
      busy = false;
      submit.disabled = false;
    }
  }

  const field = (label, input, hint) => h('div', { class: 'field' },
    h('label', { for: input.id }, label), input, hint ? h('p', { class: 'hint' }, hint) : null);
  const form = h('form', { class: 'card form', novalidate: true, onsubmit: onSubmit },
    h('h2', { class: 'card-title' }, 'Split a bill'),
    h('p', { class: 'card-intro' }, 'You already paid. Ask everyone else for their equal share.'),
    field('Total amount', amount, `In ${ctx.me.currency}`),
    field('Split between (handles)', handles, 'Separate handles with commas. Include yourself if you share the cost.'),
    field('Note', note),
    h('div', { class: 'form-actions' }, submit), error, uncertain, success);
  for (const input of [amount, handles]) input.addEventListener('input', renderPreview);
  for (const input of [amount, handles, note]) input.addEventListener('input', () => { success.hidden = true; success.removeAttribute('data-testid'); });

  main.append(
    h('h1', { class: 'page-title' }, 'Split a bill'),
    h('div', { class: 'grid split-grid' }, form, h('section', { class: 'card', 'aria-label': 'Preview' }, previewBox)));
  renderPreview();
}
