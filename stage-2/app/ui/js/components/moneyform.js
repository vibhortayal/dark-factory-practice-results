// A form that sends money-moving writes safely.
//
// Retry identity: the idempotency key belongs to the *attempt*, not the click. An attempt is
// the exact request body. Submitting the same body again reuses the key (so a retry after a lost
// response moves money once); after a confirmed success an unchanged form sends nothing at all;
// changing any value starts a new attempt with a new key.
import { NetworkError, describeError, newKey, request } from '../api.js';
import { h, icon } from '../dom.js';
import { parseAmount } from '../money.js';

const UNCERTAIN_TEXT = 'We could not confirm whether this went through. Nothing is lost: press the button again to retry safely. It will only be applied once.';

function normaliseHandle(text) {
  return text.trim().replace(/^@/, '').toLowerCase();
}

export function createMoneyForm(ctx, opts) {
  const p = opts.prefix;
  let attempt = null; // {bodyKey, key, status: 'new' | 'success' | 'uncertain' | 'refused', result}
  let busy = false;

  const handle = h('input', { id: `${p}-handle`, testid: `${p}-handle`, type: 'text', autocomplete: 'off',
    autocapitalize: 'none', spellcheck: 'false', placeholder: 'e.g. bob' });
  const amount = h('input', { id: `${p}-amount`, testid: `${p}-amount`, type: 'text', inputmode: 'decimal',
    autocomplete: 'off', placeholder: ctx.me.minor_units === 0 ? '1500' : `15.${'0'.repeat(ctx.me.minor_units)}` });
  const note = h('input', { id: `${p}-note`, testid: `${p}-note`, type: 'text', maxlength: '200',
    autocomplete: 'off', placeholder: 'What is it for? (optional)' });
  const visibility = opts.withVisibility ? h('select', { id: `${p}-visibility`, testid: `${p}-visibility` },
    h('option', { value: 'public' }, 'Public: shown in the activity feed'),
    h('option', { value: 'private' }, 'Private: only you and the recipient')) : null;
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', testid: `${p}-submit` }, opts.submitLabel);
  const error = h('div', { class: 'msg msg-error', role: 'alert', hidden: true });
  const uncertain = h('div', { class: 'msg msg-uncertain', role: 'status', hidden: true });
  const success = h('div', { class: 'msg msg-success', role: 'status', hidden: true });

  function show(box, testid, text, glyph) {
    for (const other of [error, uncertain, success]) {
      other.hidden = true;
      other.removeAttribute('data-testid');
      other.replaceChildren();
    }
    if (!box) return;
    box.hidden = false;
    box.setAttribute('data-testid', testid);
    box.replaceChildren(icon(glyph), h('span', {}, text));
  }
  const showError = (text) => show(error, `${p}-error`, text, 'alert');
  const showUncertain = (text) => show(uncertain, `${p}-uncertain`, text, 'clock');
  const showSuccess = (text) => show(success, `${p}-success`, text, 'check');
  const hideAll = () => show(null);

  function readBody() {
    const who = normaliseHandle(handle.value);
    if (!who) return { error: opts.handleMissing };
    const parsed = parseAmount(amount.value, ctx.me.minor_units);
    if (!parsed.ok) return { error: parsed.message };
    const body = { [opts.handleField]: who, amount: parsed.minor, note: note.value };
    if (visibility) body.visibility = visibility.value;
    return { body };
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (busy) return;
    const { body, error: problem } = readBody();
    if (problem) { showError(problem); return; }
    const bodyKey = JSON.stringify(body);
    if (attempt && attempt.bodyKey === bodyKey) {
      if (attempt.status === 'success') {
        showSuccess(opts.successText(attempt.result, ctx) + ' Change a field to send another.');
        return;
      }
      if (attempt.status === 'refused') attempt = null;
    } else {
      attempt = null;
    }
    attempt = attempt || { bodyKey, key: newKey(), status: 'new' };
    const mine = attempt;
    busy = true;
    submit.disabled = true;
    submit.classList.add('is-loading');
    hideAll();
    try {
      const result = await request('POST', opts.endpoint, { body, key: mine.key });
      if (result.ok) {
        mine.status = 'success';
        mine.result = result.body;
        showSuccess(opts.successText(result.body, ctx));
        await opts.onChange();
      } else if (result.status >= 500 || result.status === 408) {
        mine.status = 'uncertain';
        showUncertain(UNCERTAIN_TEXT);
      } else {
        mine.status = 'refused';
        showError(describeError(result));
        await opts.onChange();
      }
    } catch (err) {
      if (!(err instanceof NetworkError)) throw err;
      mine.status = 'uncertain';
      showUncertain(UNCERTAIN_TEXT);
    } finally {
      busy = false;
      submit.disabled = false;
      submit.classList.remove('is-loading');
    }
  }

  const field = (label, input, hint) => h('div', { class: 'field' },
    h('label', { for: input.id }, label), input, hint ? h('p', { class: 'hint' }, hint) : null);

  const form = h('form', { class: 'card form', novalidate: true, onsubmit: onSubmit, 'aria-labelledby': `${p}-title` },
    h('h2', { id: `${p}-title`, class: 'card-title' }, opts.title),
    opts.intro ? h('p', { class: 'card-intro' }, opts.intro) : null,
    field(opts.handleLabel, handle),
    field('Amount', amount, `In ${ctx.me.currency}${ctx.me.minor_units ? `, up to ${ctx.me.minor_units} decimal places` : ', whole units'}`),
    field('Note', note),
    visibility ? field('Who can see it', visibility) : null,
    h('div', { class: 'form-actions' }, submit),
    error, uncertain, success);
  form.addEventListener('input', () => { success.hidden = true; success.removeAttribute('data-testid'); });
  return { el: form };
}
