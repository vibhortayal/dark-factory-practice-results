// The outcome slots of a form: refused (`-error`), unknown (`-uncertain`) and `-success`.
// At most one is shown at a time and each exists in the DOM only while it has something to say.
import { h } from './dom.js';

export function feedback(container, prefix) {
  const slots = {};
  const show = (kind, message, role) => {
    for (const [k, el] of Object.entries(slots)) {
      if (k !== kind) { el.remove(); delete slots[k]; }
    }
    let el = slots[kind];
    if (!el) {
      el = h('p', { class: `alert alert-${kind}`, testid: `${prefix}-${kind}`, role });
      slots[kind] = el;
      container.append(el);
    }
    el.textContent = message;
  };
  return {
    clear() { show(null, '', 'alert'); },
    error: (message) => show('error', message, 'alert'),
    uncertain: (message) => show('uncertain', message, 'alert'),
    success: (message) => show('success', message, 'status'),
  };
}

const FRIENDLY = {
  insufficient_funds: 'There is not enough available money for that.',
  self_payment: 'You cannot send money to yourself.',
  self_request: 'You cannot request money from yourself.',
  request_not_pending: 'That request has already been settled.',
  authorization_not_open: 'That hold is no longer open.',
  authorization_expired: 'That hold has expired.',
  capture_exceeds_authorization: 'That is more than the hold has left.',
  email_taken: 'That email address is already registered.',
  handle_taken: 'The handle that email would get is already taken. Try another email address.',
  unauthenticated: 'Those details did not match an account.',
};

export function refusalText(res) {
  if (FRIENDLY[res.code]) return FRIENDLY[res.code];
  if (res.code === 'not_found') return res.message && /handle/i.test(res.message) ? 'No one has that handle.' : 'That could not be found.';
  const m = res.message || 'The request was refused.';
  return m.charAt(0).toUpperCase() + m.slice(1) + (/[.!?]$/.test(m) ? '' : '.');
}

export const UNCERTAIN_TEXT = 'We could not confirm whether this went through. Try again with the same details: it will only be applied once.';
