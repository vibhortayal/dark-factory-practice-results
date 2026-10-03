// The payment activity feed.
import { h, icon } from '../dom.js';
import { privacyBadge, when } from './badges.js';

function direction(payment, meId) {
  if (payment.from_user_id === meId) return { cls: 'out', label: 'You sent', sign: '−' };
  if (payment.to_user_id === meId) return { cls: 'in', label: 'You received', sign: '+' };
  return { cls: 'other', label: 'Payment', sign: '' };
}

function item(ctx, payment) {
  const dir = direction(payment, ctx.me.user_id);
  const id = payment.payment_id;
  return h('li', { class: `feed-item feed-${dir.cls}`, testid: `activity-item-${id}`,
    'data-visibility': payment.visibility },
  h('div', { class: 'feed-main' },
    h('p', { class: 'feed-title' },
      h('span', { class: 'feed-dir' }, dir.label),
      h('span', { class: 'feed-parties', testid: `activity-parties-${id}` },
        `@${payment.from_handle} → @${payment.to_handle}`)),
    h('p', { class: 'feed-note', testid: `activity-note-${id}`, text: payment.note }),
    h('p', { class: 'feed-meta' }, h('time', { datetime: payment.created_at }, when(payment.created_at)),
      privacyBadge(payment.visibility),
      payment.request_id ? h('span', { class: 'badge badge-link' }, 'Request payment') : null,
      payment.authorization_id ? h('span', { class: 'badge badge-link' }, 'Held, then captured') : null,
      payment.settlement_id ? h('span', { class: 'badge badge-link' }, 'Settlement') : null)),
  h('p', { class: 'feed-amount' },
    dir.sign ? h('span', { class: 'sign', 'aria-hidden': 'true' }, dir.sign) : null,
    h('span', { testid: `activity-amount-${id}`, text: ctx.format(payment.amount) })));
}

export function renderFeed(ctx, payments) {
  if (!payments.length) {
    return h('div', { class: 'empty', testid: 'empty-activity' },
      icon('clock'), h('p', { class: 'empty-title' }, 'No activity yet'),
      h('p', { class: 'hint' }, 'Payments you send or receive, and public payments from others, will show up here.'));
  }
  return h('ul', { class: 'feed', testid: 'activity-list' }, payments.map((p) => item(ctx, p)));
}
