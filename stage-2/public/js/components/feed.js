// The activity feed: payments only, newest first, understandable without raw API data.

import { h } from '../dom.js';
import { empty, money, privacyMark, timeTag } from './parts.js';

function direction(me, p) {
  if (p.from_user_id === me.user_id) return ['sent', '↑', 'Sent'];
  if (p.to_user_id === me.user_id) return ['received', '↓', 'Received'];
  return ['other', '↔', 'Between others'];
}

function item(me, p) {
  const [kind, glyph, label] = direction(me, p);
  return h('li', { class: `feed-item feed-${kind}`, testid: `activity-item-${p.payment_id}`, 'data-visibility': p.visibility },
    h('span', { class: 'feed-icon', 'aria-hidden': 'true' }, glyph),
    h('div', { class: 'feed-main' },
      h('p', { class: 'feed-title' }, h('span', { class: 'feed-label' }, label), ' ',
        h('span', { class: 'feed-parties', testid: `activity-parties-${p.payment_id}` }, `${p.from_handle} → ${p.to_handle}`)),
      h('p', { class: 'feed-note', testid: `activity-note-${p.payment_id}` }, p.note),
      h('p', { class: 'feed-meta' }, timeTag(p.created_at), ' ', privacyMark(p.visibility))),
    h('span', { class: 'feed-amount', testid: `activity-amount-${p.payment_id}` }, money(me, p.amount)));
}

export function renderFeed(host, me, feed) {
  if (!feed) return host.replaceChildren();
  if (feed.payments.length === 0) {
    host.replaceChildren(empty('empty-activity', 'No payments to show yet', 'Public payments and the ones you send or receive will appear here.'));
    return;
  }
  host.replaceChildren(
    h('ul', { class: 'feed', testid: 'activity-list' }, feed.payments.map((p) => item(me, p))),
    feed.has_more && h('p', { class: 'muted small' }, 'Showing the most recent payments.'),
  );
}
