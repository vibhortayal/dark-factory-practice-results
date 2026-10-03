// Small status and privacy indicators. Colour is never the only signal: each has text and an icon.
import { h, icon } from '../dom.js';

const STATUS = {
  pending: ['clock', 'Pending'],
  paid: ['check', 'Paid'],
  declined: ['alert', 'Declined'],
  cancelled: ['alert', 'Cancelled'],
  open: ['clock', 'Open'],
  captured: ['check', 'Captured'],
  voided: ['alert', 'Released'],
  expired: ['alert', 'Expired'],
};

export function statusBadge(status) {
  const [glyph, label] = STATUS[status] || ['alert', status];
  return h('span', { class: `badge badge-${status}` }, icon(glyph), label);
}

export function privacyBadge(visibility) {
  const isPrivate = visibility === 'private';
  return h('span', { class: `badge ${isPrivate ? 'badge-private' : 'badge-public'}`,
    title: isPrivate ? 'Only the two people involved can see this' : 'Visible in the activity feed' },
  icon(isPrivate ? 'lock' : 'globe'), isPrivate ? 'Private' : 'Public');
}

export function when(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
