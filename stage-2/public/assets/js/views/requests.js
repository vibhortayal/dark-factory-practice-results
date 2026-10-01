// "/requests": incoming and outgoing requests with pay, decline and cancel.
import { h, select } from '../lib/dom.js';
import { call } from '../lib/api.js';
import { RetryIdentity } from '../lib/retry.js';
import { refusalText, UNCERTAIN_TEXT } from '../lib/feedback.js';

function when(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

const STATUS_LABEL = { pending: 'Pending', paid: 'Paid', declined: 'Declined', cancelled: 'Cancelled' };

export function mountRequests(main, ctx) {
  const payIdentity = new Map(); // request id -> RetryIdentity (key follows the chosen visibility)
  const identityFor = (id) => { if (!payIdentity.has(id)) payIdentity.set(id, new RetryIdentity()); return payIdentity.get(id); };

  const status = h('div', { class: 'form-status', 'aria-live': 'polite' });
  const incoming = h('div', { class: 'list-holder' });
  const outgoing = h('div', { class: 'list-holder' });
  const section = (title, holder, id) => h('section', { class: 'card', 'aria-labelledby': id }, h('h2', { id, class: 'card-title' }, title), holder);
  main.append(h('h1', { class: 'page-title' }, 'Requests'), status, section('Asking you to pay', incoming, 'incoming-title'), section('You asked for', outgoing, 'outgoing-title'));

  const show = (kind, text) => {
    status.replaceChildren(text ? h('p', { class: `alert alert-${kind}`, testid: `request-${kind}`, role: 'alert' }, text) : '');
  };

  let emptyEl = null;
  let started = 0;
  let rendered = 0;

  async function refresh() {
    const seq = ++started;
    const [inc, out] = await Promise.all([call('GET', '/requests?direction=incoming&limit=200'), call('GET', '/requests?direction=outgoing&limit=200')]);
    if (inc.kind === 'unauthenticated' || out.kind === 'unauthenticated') return ctx.signOut();
    if (inc.kind !== 'ok' || out.kind !== 'ok') {
      incoming.replaceChildren(h('p', { class: 'alert alert-warning', role: 'status' }, 'Could not load requests. ', h('button', { type: 'button', class: 'btn btn-quiet', onClick: refresh }, 'Try again')));
      return;
    }
    if (seq < rendered) return;
    rendered = seq;
    renderLists(inc.data, out.data);
  }

  function renderLists(inc, out) {
    incoming.replaceChildren(listFor('incoming-list', inc.requests, 'incoming', 'Nobody has asked you for money.'));
    outgoing.replaceChildren(listFor('outgoing-list', out.requests, 'outgoing', 'You have not asked anyone for money.'));
    if (emptyEl) emptyEl.remove();
    emptyEl = null;
    if (inc.requests.length === 0 && out.requests.length === 0) {
      emptyEl = h('div', { class: 'card empty', testid: 'empty-requests' },
        h('p', { class: 'empty-title' }, 'No requests yet'),
        h('p', { class: 'muted' }, 'Requests you send or receive will appear here. Split a bill to ask several people at once.'));
      status.after(emptyEl);
    }
  }

  function listFor(testid, requests, direction, emptyText) {
    const items = requests.map((r) => item(r, direction));
    return h('div', {},
      h('ul', { class: 'rows', testid }, items),
      requests.length === 0 ? h('p', { class: 'muted pad' }, emptyText) : null);
  }

  function item(r, direction) {
    const pending = r.status === 'pending';
    const who = direction === 'incoming' ? `@${r.requester_handle} asks you for` : `You asked @${r.payer_handle} for`;
    const actions = [];
    if (direction === 'incoming' && pending) {
      const vis = select({
        id: `request-visibility-${r.request_id}`, label: 'Who can see it', testid: `request-visibility-${r.request_id}`, value: 'public',
        options: [{ value: 'public', label: 'Public' }, { value: 'private', label: 'Private' }],
      });
      const pay = h('button', { type: 'button', class: 'btn btn-primary', testid: `request-pay-${r.request_id}` }, 'Pay');
      pay.addEventListener('click', () => payRequest(r, vis.input.value, pay));
      const decline = h('button', { type: 'button', class: 'btn btn-secondary', testid: `request-decline-${r.request_id}` }, 'Decline');
      decline.addEventListener('click', () => act(decline, `/requests/${encodeURIComponent(r.request_id)}/decline`));
      actions.push(h('div', { class: 'action-row' }, vis.wrap, pay, decline));
    }
    if (direction === 'outgoing' && pending) {
      const cancel = h('button', { type: 'button', class: 'btn btn-secondary', testid: `request-cancel-${r.request_id}` }, 'Cancel request');
      cancel.addEventListener('click', () => act(cancel, `/requests/${encodeURIComponent(r.request_id)}/cancel`));
      actions.push(h('div', { class: 'action-row' }, cancel));
    }
    return h('li', { class: `row-item status-${r.status}`, testid: `request-item-${r.request_id}`, 'data-status': r.status },
      h('div', { class: 'row-main' },
        h('p', { class: 'row-title' }, who),
        h('p', { class: 'row-note' }, r.note),
        h('p', { class: 'row-meta' }, h('span', { class: `badge badge-status-${r.status}` }, STATUS_LABEL[r.status] || r.status), h('time', { datetime: r.created_at }, when(r.created_at)))),
      h('p', { class: 'row-amount', testid: `request-amount-${r.request_id}` }, ctx.fmt(r.amount)),
      ...actions);
  }

  async function payRequest(r, visibility, button) {
    const identity = identityFor(r.request_id);
    if (identity.busy) return;
    const body = { visibility };
    const key = identity.keyFor(JSON.stringify(body));
    identity.busy = true;
    busy(button, true, 'Paying…');
    const res = await call('POST', `/requests/${encodeURIComponent(r.request_id)}/pay`, { body, key });
    identity.busy = false;
    busy(button, false);
    await settle(res);
  }

  async function act(button, path) {
    if (button.disabled) return;
    busy(button, true, 'Working…');
    const res = await call('POST', path);
    busy(button, false);
    await settle(res);
  }

  async function settle(res) {
    if (res.kind === 'ok') { show('error', ''); await refresh(); return; }
    if (res.kind === 'refused') { show('error', refusalText(res)); await refresh(); return; }
    if (res.kind === 'unauthenticated') return ctx.signOut();
    show('uncertain', UNCERTAIN_TEXT);
  }

  function busy(button, on, label) {
    if (!button.isConnected) return;
    if (on) { button.dataset.label = button.textContent; button.disabled = true; button.setAttribute('aria-busy', 'true'); if (label) button.textContent = label; }
    else { button.disabled = false; button.removeAttribute('aria-busy'); if (button.dataset.label) button.textContent = button.dataset.label; }
  }

  incoming.replaceChildren(h('p', { class: 'muted skeleton' }, 'Loading requests…'));
  refresh();
}
