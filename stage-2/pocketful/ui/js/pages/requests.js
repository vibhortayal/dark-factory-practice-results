// `/requests`: incoming and outgoing requests with pay, decline and cancel.
import { call, describe, newKey } from '../api.js';
import { badge, emptyPanel, errorPanel, loadingPanel, money } from '../components.js';
import { formatWhen, h, replace, tid } from '../dom.js';
import { app, loadMe } from '../session.js';

const STATUS_LABEL = { pending: 'Pending', paid: 'Paid', declined: 'Declined', cancelled: 'Cancelled' };
const payKeys = new Map();   // request id -> idempotency key, kept so a retry replays

export function render(root) {
  let alive = true;
  let latest = 0;
  const messages = h('div', { class: 'messages', 'aria-live': 'polite' });
  const incoming = h('ul', { class: 'request-list', ...tid('incoming-list'), 'aria-label': 'Incoming requests' });
  const outgoing = h('ul', { class: 'request-list', ...tid('outgoing-list'), 'aria-label': 'Outgoing requests' });
  const emptySlot = h('div');
  const body = h('div', { class: 'layout layout-even' },
    h('section', { class: 'card', 'aria-labelledby': 'in-title' },
      h('h2', { id: 'in-title' }, 'Incoming'), h('p', { class: 'intro' }, 'People asking you for money.'), incoming),
    h('section', { class: 'card', 'aria-labelledby': 'out-title' },
      h('h2', { id: 'out-title' }, 'Outgoing'), h('p', { class: 'intro' }, 'Money you asked others for.'), outgoing));

  const say = (kind, id, text) => replace(messages, h('p', { class: `msg msg-${kind}`, role: kind === 'ok' ? 'status' : 'alert', ...tid(id) }, text));

  function item(request, mine) {
    const id = request.request_id;
    const isIncoming = request.payer_handle === mine.handle;
    const pending = request.status === 'pending';
    const other = isIncoming ? request.requester_handle : request.payer_handle;
    return h('li', { class: `request-item status-${request.status}`, ...tid(`request-item-${id}`), 'data-status': request.status },
      h('div', { class: 'feed-row' },
        h('div', { class: 'feed-people' },
          badge(STATUS_LABEL[request.status] || request.status, request.status),
          h('span', { class: 'parties' }, isIncoming ? `${other} asks you` : `You ask ${other}`)),
        h('span', { class: 'amount', ...tid(`request-amount-${id}`) }, money(mine, request.amount))),
      request.note ? h('p', { class: 'note' }, request.note) : null,
      h('div', { class: 'feed-meta' }, h('time', { datetime: request.created_at }, formatWhen(request.created_at))),
      pending ? h('div', { class: 'actions' },
        isIncoming ? [
          h('button', { type: 'button', class: 'btn btn-primary', ...tid(`request-pay-${id}`), onclick: () => act('pay', request) }, 'Pay'),
          h('button', { type: 'button', class: 'btn btn-secondary', ...tid(`request-decline-${id}`), onclick: () => act('decline', request) }, 'Decline'),
        ] : h('button', { type: 'button', class: 'btn btn-secondary', ...tid(`request-cancel-${id}`), onclick: () => act('cancel', request) }, 'Cancel request')) : null);
  }

  async function act(action, request) {
    const id = request.request_id;
    const path = `/requests/${encodeURIComponent(id)}/${action}`;
    let key;
    if (action === 'pay') {
      if (!payKeys.has(id)) payKeys.set(id, newKey());
      key = payKeys.get(id);
    }
    say('pending', 'request-pending', 'Working on it…');
    const result = await call('POST', path, { body: action === 'pay' ? {} : undefined, key });
    if (!alive) return;
    if (result.kind === 'ok') {
      const verb = { pay: 'Paid', decline: 'Declined', cancel: 'Cancelled' }[action];
      say('ok', 'request-success', `${verb} the request.`);
    } else if (result.kind === 'refused') {
      say('error', 'request-error', describe(result));
    } else {
      say('uncertain', 'request-uncertain', 'We could not confirm what happened. Press the button again to retry safely, or refresh.');
    }
    if (result.kind !== 'uncertain') { await loadMe(); await refresh(); }
  }

  async function refresh() {
    const seq = ++latest;
    const [list, me] = await Promise.all([call('GET', '/requests?limit=200'), app.me ? { kind: 'ok' } : loadMe()]);
    if (!alive || seq !== latest) return;
    if (list.kind !== 'ok' || me.kind !== 'ok') {
      if (list.kind !== 'refused') replace(root, errorPanel('Requests could not be loaded.', start));
      return;
    }
    const mine = app.me;
    const all = list.data.requests;
    replace(incoming, all.filter((r) => r.payer_handle === mine.handle).map((r) => item(r, mine)));
    replace(outgoing, all.filter((r) => r.requester_handle === mine.handle).map((r) => item(r, mine)));
    replace(emptySlot, all.length === 0
      ? emptyPanel('empty-requests', 'No requests yet', 'When someone asks you for money, or you ask them, it appears here.') : null);
  }

  async function start() {
    replace(root, loadingPanel('Loading requests…'));
    const me = await loadMe();
    if (!alive) return;
    if (me.kind !== 'ok') {
      if (me.kind !== 'refused') replace(root, errorPanel('Requests could not be loaded.', start));
      return;
    }
    replace(root, h('h1', {}, 'Requests'), messages, emptySlot, body);
    refresh();
  }

  start();
  return () => { alive = false; };
}
