// `/requests`: incoming and outgoing requests with pay, decline and cancel.

import { h, selectField, createFeedback } from '../dom.js';
import { createModel } from '../model.js';
import { normalizeMe, ApiError } from '../api.js';
import { RetryIdentity } from '../retry.js';
import { refusalText } from '../text.js';
import { statusBadge, timeTag, money, empty, loading, loadFailure } from '../components/parts.js';

export function mountRequests({ api, me, main }) {
  const model = createModel({
    api,
    initial: { me, incoming: null, outgoing: null },
    sources: {
      me: (a) => a.get('/me').then(normalizeMe),
      incoming: (a) => a.get('/requests?direction=incoming&limit=200'),
      outgoing: (a) => a.get('/requests?direction=outgoing&limit=200'),
    },
  });

  const retries = new Map(); // request id -> RetryIdentity for paying it
  const problem = h('div', { class: 'problem' });
  const messages = h('div', { class: 'messages' });
  const feedback = createFeedback(messages, { error: 'request-error', uncertain: 'request-uncertain', success: 'request-success' });
  const privacy = selectField({
    label: 'When you pay a request, who can see the payment',
    testid: 'request-pay-visibility',
    options: [['public', 'Public: shown in the activity feed'], ['private', 'Private: only you and the other person']],
    value: 'public',
  });
  const incomingHost = h('div', { class: 'list-host' }, loading('Loading requests…'));
  const outgoingHost = h('div', { class: 'list-host' }, loading('Loading requests…'));
  const bothEmpty = h('div', { class: 'empty-host' });

  const refresh = () =>
    model.refresh().then(
      () => problem.replaceChildren(),
      () => problem.replaceChildren(loadFailure('We could not load your requests.', refresh)),
    );

  /** Run a write; refusals show `request-error` and refresh so stale buttons disappear. */
  async function act(fn, doneText) {
    feedback.clear();
    try {
      await fn();
      feedback.show('success', doneText);
    } catch (err) {
      if (err instanceof ApiError) feedback.show('error', refusalText(err));
      else feedback.show('uncertain', 'We could not confirm whether that went through. Try again to be sure; it will only be applied once.');
    }
    await refresh();
  }

  function pay(r) {
    const body = { visibility: privacy.input.value };
    if (!retries.has(r.request_id)) retries.set(r.request_id, new RetryIdentity());
    const key = retries.get(r.request_id).keyFor(JSON.stringify(body));
    return act(() => api.post(`/requests/${encodeURIComponent(r.request_id)}/pay`, body, key), 'Request paid.');
  }

  function item(r, incoming) {
    const who = incoming ? `From ${r.requester_handle}` : `To ${r.payer_handle}`;
    const buttons = [];
    if (incoming && r.status === 'pending') {
      buttons.push(h('button', { type: 'button', class: 'btn btn-primary', testid: `request-pay-${r.request_id}`, onclick: () => pay(r) }, 'Pay'));
      buttons.push(h('button', { type: 'button', class: 'btn btn-secondary', testid: `request-decline-${r.request_id}`, onclick: () => act(() => api.post(`/requests/${encodeURIComponent(r.request_id)}/decline`), 'Request declined.') }, 'Decline'));
    }
    if (!incoming && r.status === 'pending') {
      buttons.push(h('button', { type: 'button', class: 'btn btn-secondary', testid: `request-cancel-${r.request_id}`, onclick: () => act(() => api.post(`/requests/${encodeURIComponent(r.request_id)}/cancel`), 'Request cancelled.') }, 'Cancel request'));
    }
    return h('li', { class: `row-item status-${r.status}`, testid: `request-item-${r.request_id}`, 'data-status': r.status },
      h('div', { class: 'row-main' },
        h('p', { class: 'row-title' }, who, ' ', statusBadge(r.status)),
        r.note !== '' && h('p', { class: 'row-note' }, r.note),
        h('p', { class: 'row-meta' }, timeTag(r.created_at))),
      h('div', { class: 'row-side' },
        h('span', { class: 'row-amount', testid: `request-amount-${r.request_id}` }, money(model.state.me, r.amount)),
        buttons.length > 0 && h('div', { class: 'row-actions' }, buttons)));
  }

  function renderList(host, data, incoming, testid, emptyText) {
    if (!data) return;
    host.replaceChildren(
      h('ul', { class: 'rows', testid }, data.requests.map((r) => item(r, incoming))),
      data.requests.length === 0 && h('p', { class: 'muted' }, emptyText),
    );
  }

  model.subscribe((state) => {
    renderList(incomingHost, state.incoming, true, 'incoming-list', 'Nobody has asked you for money.');
    renderList(outgoingHost, state.outgoing, false, 'outgoing-list', 'You have not asked anyone for money.');
    const none = state.incoming && state.outgoing && state.incoming.requests.length === 0 && state.outgoing.requests.length === 0;
    bothEmpty.replaceChildren(none ? empty('empty-requests', 'No requests yet', 'Ask someone for money from the wallet, or split a bill.') : '');
  });

  main.replaceChildren(
    h('h1', { class: 'page-title' }, 'Requests'),
    problem, messages, bothEmpty,
    h('div', { class: 'grid two' },
      h('section', { class: 'card', 'aria-labelledby': 'in-title' }, h('h2', { class: 'card-title', id: 'in-title' }, 'Asking you'), privacy.wrap, incomingHost),
      h('section', { class: 'card', 'aria-labelledby': 'out-title' }, h('h2', { class: 'card-title', id: 'out-title' }, 'You asked'), outgoingHost)),
  );
  refresh();
}
