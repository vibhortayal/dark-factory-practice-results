// The activity feed: payments newest first, readable without raw API data.
import { badge, emptyPanel, money } from './components.js';
import { formatWhen, h, tid } from './dom.js';

function direction(payment, me) {
  if (payment.from_handle === me.handle) return ['Sent', 'sent'];
  if (payment.to_handle === me.handle) return ['Received', 'received'];
  return ['Public', 'other'];
}

function origin(payment) {
  if (payment.settlement_id) return badge('Settlement', 'neutral');
  if (payment.authorization_id) return badge('Authorization capture', 'neutral');
  if (payment.request_id) return badge('Paid request', 'neutral');
  return null;
}

export function feedItem(payment, me) {
  const id = payment.payment_id;
  const [label, kind] = direction(payment, me);
  return h('li', { class: `feed-item feed-${kind}`, ...tid(`activity-item-${id}`), 'data-visibility': payment.visibility },
    h('div', { class: 'feed-row' },
      h('div', { class: 'feed-people' },
        badge(label, kind),
        h('span', { class: 'parties', ...tid(`activity-parties-${id}`) },
          h('span', { class: 'sr-only' }, 'from '), payment.from_handle,
          h('span', { 'aria-hidden': 'true' }, ' → '), h('span', { class: 'sr-only' }, ' to '), payment.to_handle)),
      h('span', { class: 'amount', ...tid(`activity-amount-${id}`) }, money(me, payment.amount))),
    h('p', { class: 'note', ...tid(`activity-note-${id}`) }, payment.note),
    h('div', { class: 'feed-meta' },
      badge(payment.visibility === 'private' ? 'Private' : 'Public', payment.visibility === 'private' ? 'private' : 'public'),
      origin(payment),
      h('time', { datetime: payment.created_at }, formatWhen(payment.created_at))));
}

export function feedView(payments, me, hasMore) {
  if (payments.length === 0) {
    return emptyPanel('empty-activity', 'Nothing here yet', 'Payments you send or receive, and public ones, show up here.');
  }
  return h('div', {},
    h('ul', { class: 'feed', ...tid('activity-list') }, payments.map((p) => feedItem(p, me))),
    hasMore ? h('p', { class: 'hint' }, 'Showing the most recent payments.') : null);
}
