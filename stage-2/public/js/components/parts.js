// Small presentational parts: status badges, privacy marks, balance card, empty and loading states.

import { h, setChildren } from '../dom.js';
import { formatAmount } from '../money.js';
import { formatWhen } from '../text.js';

const STATUS = {
  pending: ['◔', 'Pending'],
  paid: ['✓', 'Paid'],
  declined: ['✕', 'Declined'],
  cancelled: ['⊘', 'Cancelled'],
  open: ['●', 'Open'],
  captured: ['✓', 'Captured'],
  voided: ['⊘', 'Voided'],
  expired: ['◷', 'Expired'],
};

export function statusBadge(status) {
  const [glyph, label] = STATUS[status] || ['•', status];
  return h('span', { class: `badge badge-${status}` }, h('span', { 'aria-hidden': 'true' }, glyph), ' ', label);
}

export function privacyMark(visibility) {
  return visibility === 'private'
    ? h('span', { class: 'mark mark-private' }, h('span', { 'aria-hidden': 'true' }, '🔒'), ' Private')
    : h('span', { class: 'mark' }, h('span', { 'aria-hidden': 'true' }, '◎'), ' Public');
}

export function timeTag(iso) {
  return h('time', { datetime: iso, class: 'when' }, formatWhen(iso));
}

export const money = (me, minor) => formatAmount(minor, me.minor_units, me.currency);

/** Available funds first; total and held are secondary. */
export function renderBalance(host, me, { onRefresh } = {}) {
  setChildren(host, 
    h('p', { class: 'eyebrow' }, 'Available to spend'),
    h('p', { class: 'headline', testid: 'wallet-available', 'data-amount': me.available }, money(me, me.available)),
    h('dl', { class: 'subtotals' },
      h('div', {}, h('dt', {}, 'Total balance'), h('dd', { testid: 'wallet-balance', 'data-amount': me.total }, money(me, me.total))),
      me.held > 0 && h('div', { class: 'held' }, h('dt', {}, 'On hold'), h('dd', { testid: 'wallet-held', 'data-amount': me.held }, money(me, me.held)))),
    onRefresh && h('button', { type: 'button', class: 'btn btn-secondary', testid: 'wallet-refresh', onclick: onRefresh }, 'Refresh'),
  );
}

export const empty = (testid, title, text) =>
  h('div', { class: 'empty', testid }, h('p', { class: 'empty-title' }, title), h('p', { class: 'muted' }, text));

export const loading = (text) =>
  h('div', { class: 'loading-block', role: 'status', 'aria-live': 'polite' },
    h('p', { class: 'loading' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), text),
    h('div', { class: 'skeleton', 'aria-hidden': 'true' }, h('span', { class: 'skeleton-line' }), h('span', { class: 'skeleton-line' }), h('span', { class: 'skeleton-line' })));

export function loadFailure(text, onRetry) {
  return h('div', { class: 'notice notice-error', role: 'alert', testid: 'load-error' },
    h('span', { class: 'notice-icon', 'aria-hidden': 'true' }, '!'),
    h('span', { class: 'notice-text' }, text),
    h('button', { type: 'button', class: 'btn btn-secondary', onclick: onRetry }, 'Try again'));
}
