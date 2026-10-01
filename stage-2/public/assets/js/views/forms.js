// A money form (pay / request / authorize) with the shared behaviour of the product:
//  - decimal input parsed exactly, rejected locally (no request) when invalid;
//  - one idempotency key per form *content* (see lib/retry.js);
//  - a second click while a submission is in flight is ignored;
//  - a refusal (4xx envelope) and an unknown outcome (network/5xx/unparseable) look different.
import { h, field, select } from '../lib/dom.js';
import { call } from '../lib/api.js';
import { RetryIdentity } from '../lib/retry.js';
import { feedback, refusalText, UNCERTAIN_TEXT } from '../lib/feedback.js';
import { parseAmount } from '../money.js';

export const cleanHandle = (s) => String(s).trim().replace(/^@/, '');

export function transferForm(ctx, cfg) {
  const p = cfg.prefix;
  const retry = new RetryIdentity();
  const handle = field({ id: `${p}-handle`, label: cfg.handleLabel, testid: `${p}-handle`, autocomplete: 'off', placeholder: 'handle' });
  const amount = field({ id: `${p}-amount`, label: 'Amount', testid: `${p}-amount`, inputmode: 'decimal', autocomplete: 'off', placeholder: ctx.cfg.minor_units === 0 ? '1200' : '15.00', hint: `In ${ctx.cfg.currency}` });
  const note = field({ id: `${p}-note`, label: 'Note (optional)', testid: `${p}-note`, autocomplete: 'off', maxlength: 400 });
  const visibility = cfg.withVisibility
    ? select({
        id: `${p}-visibility`, label: 'Who can see it', testid: `${p}-visibility`, value: 'public',
        options: [{ value: 'public', label: 'Public (in the feed)' }, { value: 'private', label: 'Private (just the two of you)' }],
      })
    : null;
  const status = h('div', { class: 'form-status' });
  const fb = feedback(status, p);
  const button = h('button', { type: 'submit', class: 'btn btn-primary', testid: `${p}-submit` }, cfg.submitLabel);
  const form = h('form', { class: 'card form-card', novalidate: true, 'aria-labelledby': `${p}-title` },
    h('h2', { id: `${p}-title`, class: 'card-title' }, cfg.title),
    h('p', { class: 'card-lede' }, cfg.lede),
    handle.wrap, amount.wrap, note.wrap, visibility && visibility.wrap, status, button);

  function build() {
    const to = cleanHandle(handle.input.value);
    if (to === '') return { error: 'Enter a handle.' };
    const parsed = parseAmount(amount.input.value, ctx.cfg.minor_units);
    if (!parsed.ok) return { error: parsed.error };
    const body = { [cfg.handleField]: to, amount: parsed.minor, note: note.input.value };
    if (visibility) body.visibility = visibility.input.value;
    return { body };
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (retry.busy) return;
    const built = build();
    if (built.error) { fb.error(built.error); return; }
    const key = retry.keyFor(JSON.stringify(built.body));
    retry.busy = true;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = cfg.busyLabel;
    const res = await call('POST', cfg.path, { body: built.body, key });
    retry.busy = false;
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.textContent = cfg.submitLabel;
    if (res.kind === 'ok') {
      fb.success(cfg.successText(res, built.body, ctx));
      await cfg.afterSuccess(res.data);
    } else if (res.kind === 'refused') {
      fb.error(refusalText(res));
      await cfg.afterRefusal();
    } else if (res.kind === 'unauthenticated') {
      ctx.signOut();
    } else {
      fb.uncertain(UNCERTAIN_TEXT);
    }
  });
  return form;
}

export function payFormConfig(ctx, refresh) {
  return {
    prefix: 'pay', handleField: 'to_handle', path: '/payments', withVisibility: true,
    title: 'Send money', lede: 'Pay someone by their handle, straight away.', handleLabel: 'Recipient handle',
    submitLabel: 'Send money', busyLabel: 'Sending…',
    successText: (res, body) => (res.status === 200
      ? `This payment to @${body.to_handle} was already sent. Nothing was charged twice.`
      : `Sent ${ctx.fmt(body.amount)} to @${body.to_handle}.`),
    afterSuccess: refresh, afterRefusal: refresh,
  };
}

export function requestFormConfig(ctx, refresh) {
  return {
    prefix: 'request', handleField: 'payer_handle', path: '/requests', withVisibility: false,
    title: 'Request money', lede: 'Ask someone to pay you. They choose whether to pay.', handleLabel: 'Who should pay?',
    submitLabel: 'Request money', busyLabel: 'Requesting…',
    successText: (res, body) => (res.status === 200
      ? `This request to @${body.payer_handle} was already sent.`
      : `Requested ${ctx.fmt(body.amount)} from @${body.payer_handle}.`),
    afterSuccess: refresh, afterRefusal: async () => {},
  };
}

export function authorizeFormConfig(ctx, refresh) {
  return {
    prefix: 'authorize', handleField: 'to_handle', path: '/authorizations', withVisibility: true,
    title: 'Hold money for someone', lede: 'Reserve funds they can collect later. Nothing moves until they capture.', handleLabel: 'Recipient handle',
    submitLabel: 'Place hold', busyLabel: 'Placing hold…',
    successText: (res, body) => (res.status === 200
      ? `This hold for @${body.to_handle} was already placed.`
      : `Holding ${ctx.fmt(body.amount)} for @${body.to_handle}.`),
    afterSuccess: refresh, afterRefusal: refresh,
  };
}
