// The activity feed (payments only), newest first.
import { h, lockIcon } from '../lib/dom.js';

function when(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function feedItem(ctx, p) {
  const mine = ctx.me.user_id;
  const dir = p.from_user_id === mine ? 'sent' : p.to_user_id === mine ? 'received' : 'other';
  const label = { sent: 'Sent', received: 'Received', other: 'Payment' }[dir];
  const tag = p.refund_of ? 'Refund' : p.settlement_id ? 'Settlement' : p.authorization_id ? 'Held funds' : p.request_id ? 'Request' : null;
  return h('li', { class: `feed-item dir-${dir}`, testid: `activity-item-${p.payment_id}`, 'data-visibility': p.visibility },
    h('div', { class: 'feed-main' },
      h('p', { class: 'feed-title' },
        h('span', { class: 'badge badge-dir' }, label),
        h('span', { class: 'feed-parties', testid: `activity-parties-${p.payment_id}` }, `@${p.from_handle} → @${p.to_handle}`)),
      h('p', { class: 'feed-note', testid: `activity-note-${p.payment_id}` }, p.note),
      h('p', { class: 'feed-meta' },
        h('time', { datetime: p.created_at }, when(p.created_at)),
        p.visibility === 'private'
          ? h('span', { class: 'badge badge-private' }, lockIcon(), ' Private')
          : h('span', { class: 'badge badge-public' }, 'Public'),
        tag ? h('span', { class: 'badge' }, tag) : null)),
    h('p', { class: 'feed-amount', testid: `activity-amount-${p.payment_id}` }, ctx.fmt(p.amount)));
}

export function feedSection(ctx) {
  const holder = h('div', { class: 'feed-holder', 'aria-busy': 'true' }, h('p', { class: 'muted skeleton' }, 'Loading activity…'));
  const el = h('section', { class: 'card', 'aria-labelledby': 'activity-title' }, h('h2', { id: 'activity-title', class: 'card-title' }, 'Activity'), holder);
  function render(payments, hasMore, onMore) {
    holder.removeAttribute('aria-busy');
    if (payments.length === 0) {
      holder.replaceChildren(h('div', { class: 'empty', testid: 'empty-activity' },
        h('p', { class: 'empty-title' }, 'No activity yet'),
        h('p', { class: 'muted' }, 'Payments you send or receive, and public payments from others, will show up here.')));
      return;
    }
    const more = hasMore ? h('button', { type: 'button', class: 'btn btn-quiet', testid: 'activity-more', onClick: onMore }, 'Load more') : null;
    holder.replaceChildren(...[h('ul', { class: 'feed', testid: 'activity-list' }, payments.map((p) => feedItem(ctx, p))), more].filter(Boolean));
  }
  return { el, render };
}
