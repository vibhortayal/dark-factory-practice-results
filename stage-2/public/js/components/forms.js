// The write forms. Each keeps its values after success, re-sends the same idempotency key for
// unchanged content, and tells a refusal (4xx with an error body) from an unknown outcome.

import { h, textField, selectField, createFeedback, spinnerLabel } from '../dom.js';
import { parseDecimal } from '../money.js';
import { RetryIdentity } from '../retry.js';
import { ApiError } from '../api.js';
import { refusalText } from '../text.js';

/**
 * Generic idempotent form.
 *   read()  -> {error} | {fingerprint, body}      (no request is sent for {error})
 *   send(body, key) -> Promise of the response
 */
function writeForm({ title, intro, fields, submitLabel, busyLabel, testids, ids, read, send, onSuccess, onRefusal, className }) {
  const retry = new RetryIdentity();
  const messages = h('div', { class: 'messages' });
  const feedback = createFeedback(messages, ids);
  const button = h('button', { type: 'submit', class: 'btn btn-primary', testid: testids.submit }, submitLabel);
  let busy = false;

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const input = read();
    if (input.error) {
      feedback.show('error', input.error);
      return;
    }
    const key = retry.keyFor(input.fingerprint);
    busy = true;
    button.disabled = true;
    button.replaceChildren(spinnerLabel(busyLabel));
    try {
      const result = await send(input.body, key);
      feedback.show('success', onSuccess.message(result));
      busy = false;
      button.disabled = false;
      button.replaceChildren(submitLabel);
      await onSuccess.refresh(result).catch(() => {});
    } catch (err) {
      busy = false;
      button.disabled = false;
      button.replaceChildren(submitLabel);
      if (err instanceof ApiError) {
        feedback.show('error', refusalText(err));
        await (onRefusal ? onRefusal(err) : Promise.resolve()).catch(() => {});
      } else {
        feedback.show('uncertain', 'We could not confirm whether this went through. Nothing is lost: send the same form again and it will be applied only once.');
      }
    }
  }

  const form = h('form', { class: `card form-card ${className || ''}`, novalidate: true, onsubmit: submit },
    h('h2', { class: 'card-title' }, title), intro && h('p', { class: 'muted' }, intro), fields, messages, h('div', { class: 'actions' }, button));
  return form;
}

const moneyField = (label, testid) =>
  textField({ label, testid, inputmode: 'decimal', autocomplete: 'off', placeholder: '0.00' });

const VISIBILITY = [['public', 'Public (in the feed)'], ['private', 'Private (just you two)']];

/** Shared reading of handle + amount + note (+ visibility) fields. */
function readPaymentFields(model, f) {
  const me = model.state.me;
  const handle = f.handle.input.value.trim();
  const note = f.note.input.value;
  const visibility = f.visibility.input.value;
  if (handle === '') return { error: 'Enter the handle of the person.' };
  const amount = parseDecimal(f.amount.input.value, me.minor_units);
  if (!amount.ok) return { error: amount.reason };
  return {
    fingerprint: JSON.stringify([handle, f.amount.input.value, note, visibility]),
    body: { to_handle: handle, amount: amount.minor, note, visibility },
  };
}

function paymentFields(prefix, notePlaceholder) {
  return {
    handle: textField({ label: 'Pay to (handle)', testid: `${prefix}-handle`, autocomplete: 'off', placeholder: 'e.g. bob' }),
    amount: moneyField('Amount', `${prefix}-amount`),
    note: textField({ label: 'Note (optional)', testid: `${prefix}-note`, placeholder: notePlaceholder, autocomplete: 'off' }),
    visibility: selectField({ label: 'Who can see it', testid: `${prefix}-visibility`, options: VISIBILITY, value: 'public' }),
  };
}

export function payForm({ api, model }) {
  const f = paymentFields('pay', 'What is it for?');
  return writeForm({
    title: 'Send money',
    intro: 'Moves money from your available funds right away.',
    fields: [f.handle.wrap, f.amount.wrap, f.note.wrap, f.visibility.wrap],
    submitLabel: 'Send payment', busyLabel: 'Sending…',
    testids: { submit: 'pay-submit' },
    ids: { error: 'pay-error', uncertain: 'pay-uncertain', success: 'pay-success' },
    read: () => readPaymentFields(model, f),
    send: (body, key) => api.post('/payments', body, key),
    onSuccess: { message: (p) => `Sent ${p.to_handle ? `to ${p.to_handle}` : 'the payment'}.`, refresh: () => model.refresh() },
    onRefusal: () => model.refresh(),
  });
}

export function authorizeForm({ api, model }) {
  const f = paymentFields('authorize', 'What is the hold for?');
  f.handle.wrap.querySelector('label').textContent = 'Hold for (handle)';
  return writeForm({
    title: 'Place a hold',
    intro: 'Reserve money for someone to collect later. It stays yours until they capture it.',
    fields: [f.handle.wrap, f.amount.wrap, f.note.wrap, f.visibility.wrap],
    submitLabel: 'Authorise', busyLabel: 'Placing hold…',
    testids: { submit: 'authorize-submit' },
    ids: { error: 'authorize-error', uncertain: 'authorize-uncertain', success: 'authorize-success' },
    read: () => readPaymentFields(model, f),
    send: (body, key) => api.post('/authorizations', body, key),
    onSuccess: { message: (a) => `Holding ${a.to_handle ? `for ${a.to_handle}` : 'the money'}.`, refresh: () => model.refresh() },
    onRefusal: () => model.refresh(),
  });
}

export function requestForm({ api, model }) {
  const handle = textField({ label: 'Ask (handle)', testid: 'request-handle', autocomplete: 'off', placeholder: 'e.g. ada' });
  const amount = moneyField('Amount', 'request-amount');
  const note = textField({ label: 'Note (optional)', testid: 'request-note', autocomplete: 'off', placeholder: 'What is it for?' });
  return writeForm({
    title: 'Request money',
    intro: 'Ask someone to pay you. Nothing moves until they agree.',
    fields: [handle.wrap, amount.wrap, note.wrap],
    submitLabel: 'Send request', busyLabel: 'Sending…',
    testids: { submit: 'request-submit' },
    ids: { error: 'request-error', uncertain: 'request-uncertain', success: 'request-success' },
    read: () => {
      const who = handle.input.value.trim();
      if (who === '') return { error: 'Enter the handle of the person.' };
      const parsed = parseDecimal(amount.input.value, model.state.me.minor_units);
      if (!parsed.ok) return { error: parsed.reason };
      return {
        fingerprint: JSON.stringify([who, amount.input.value, note.input.value]),
        body: { payer_handle: who, amount: parsed.minor, note: note.input.value },
      };
    },
    send: (body, key) => api.post('/requests', body, key),
    onSuccess: { message: (r) => `Request sent to ${r.payer_handle}.`, refresh: () => model.refresh() },
  });
}

export { writeForm, moneyField };
