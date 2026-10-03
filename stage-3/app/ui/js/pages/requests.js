// `/requests`: incoming and outgoing money requests with pay, decline and cancel.
import { NetworkError, describeError, latestWins, newKey, request } from '../api.js';
import { clear, h, icon } from '../dom.js';
import { statusBadge, when } from '../components/badges.js';
import { createWalletSummary } from '../components/wallet.js';

export function mountRequests(main, ctx) {
  const summary = createWalletSummary(ctx);
  const incomingBox = h('ul', { class: 'cards', testid: 'incoming-list' });
  const outgoingBox = h('ul', { class: 'cards', testid: 'outgoing-list' });
  const emptyBox = h('div', { class: 'empty', testid: 'empty-requests', hidden: true },
    icon('clock'), h('p', { class: 'empty-title' }, 'No requests yet'),
    h('p', { class: 'hint' }, 'When someone asks you for money, or you ask them, it appears here.'));
  const notice = h('div', { class: 'msg', hidden: true });
  const payKeys = new Map(); // request id -> idempotency key of an unconfirmed pay attempt
  const latest = latestWins();
  let loading = true;
  let lastSignature = '';

  function say(kind, testid, text) {
    notice.hidden = !text;
    notice.className = `msg msg-${kind}`;
    notice.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    if (text) {
      notice.setAttribute('data-testid', testid);
      notice.replaceChildren(icon(kind === 'error' ? 'alert' : 'clock'), h('span', {}, text));
    } else {
      notice.removeAttribute('data-testid');
      notice.replaceChildren();
    }
  }

  function refresh() {
    return latest(async () => {
      const [me, incoming, outgoing] = await Promise.all([
        request('GET', '/me'),
        request('GET', '/requests?direction=incoming&limit=200'),
        request('GET', '/requests?direction=outgoing&limit=200'),
      ]);
      if (!me.ok || !incoming.ok || !outgoing.ok) throw new Error('refresh failed');
      return { me: me.body, incoming: incoming.body.requests, outgoing: outgoing.body.requests };
    }, ({ me, incoming, outgoing }) => {
      loading = false;
      summary.update(me);
      const signature = JSON.stringify([incoming, outgoing]);
      if (signature !== lastSignature) {
        lastSignature = signature;
        clear(incomingBox).append(...incoming.map((r) => card(r, 'incoming')));
        clear(outgoingBox).append(...outgoing.map((r) => card(r, 'outgoing')));
      }
      incomingSection.hidden = false;
      outgoingSection.hidden = false;
      incomingEmpty.hidden = incoming.length > 0;
      outgoingEmpty.hidden = outgoing.length > 0;
      emptyBox.hidden = incoming.length + outgoing.length > 0;
    }, () => say('error', 'requests-load-error', 'We could not load your requests. Try again.'));
  }

  async function act(label, work) {
    say('error', 'request-error', '');
    try {
      const result = await work();
      if (!result.ok) say('error', 'request-error', describeError(result));
    } catch (err) {
      if (!(err instanceof NetworkError)) throw err;
      say('uncertain', 'request-uncertain', 'We could not confirm that went through. Press the same button again to retry safely.');
    }
    await refresh();
  }

  async function pay(req) {
    if (!payKeys.has(req.request_id)) payKeys.set(req.request_id, newKey());
    await act('pay', async () => {
      const result = await request('POST', `/requests/${encodeURIComponent(req.request_id)}/pay`,
        { body: {}, key: payKeys.get(req.request_id) });
      payKeys.delete(req.request_id);
      return result;
    });
  }

  const post = (req, verb) => act(verb, () => request('POST', `/requests/${encodeURIComponent(req.request_id)}/${verb}`));

  function card(req, direction) {
    const id = req.request_id;
    const incoming = direction === 'incoming';
    const pending = req.status === 'pending';
    return h('li', { class: `card request request-${req.status}`, testid: `request-item-${id}`, 'data-status': req.status },
      h('div', { class: 'request-head' },
        h('p', { class: 'request-who' }, incoming ? 'From ' : 'To ', h('strong', {}, `@${incoming ? req.requester_handle : req.payer_handle}`)),
        statusBadge(req.status)),
      h('p', { class: 'request-amount', testid: `request-amount-${id}`, text: ctx.format(req.amount) }),
      req.note ? h('p', { class: 'request-note', text: req.note }) : null,
      h('p', { class: 'meta' }, h('time', { datetime: req.created_at }, when(req.created_at))),
      pending ? h('div', { class: 'form-actions' },
        incoming ? [
          h('button', { type: 'button', class: 'btn btn-primary', testid: `request-pay-${id}`, onclick: () => pay(req) }, 'Pay'),
          h('button', { type: 'button', class: 'btn btn-secondary', testid: `request-decline-${id}`, onclick: () => post(req, 'decline') }, 'Decline'),
        ] : h('button', { type: 'button', class: 'btn btn-secondary', testid: `request-cancel-${id}`, onclick: () => post(req, 'cancel') }, 'Cancel request')) : null);
  }

  const incomingEmpty = h('p', { class: 'hint', hidden: true }, 'Nobody has asked you for money.');
  const outgoingEmpty = h('p', { class: 'hint', hidden: true }, 'You have not asked anyone for money.');
  const incomingSection = h('section', { 'aria-labelledby': 'incoming-title', hidden: true },
    h('h2', { id: 'incoming-title', class: 'section-title' }, 'Asked of you'), incomingBox, incomingEmpty);
  const outgoingSection = h('section', { 'aria-labelledby': 'outgoing-title', hidden: true },
    h('h2', { id: 'outgoing-title', class: 'section-title' }, 'You asked for'), outgoingBox, outgoingEmpty);

  main.append(
    h('h1', { class: 'page-title' }, 'Requests'),
    h('div', { class: 'grid requests-grid' },
      h('div', { class: 'area-summary' }, summary.el),
      h('div', { class: 'area-main' }, notice,
        loading ? h('div', { class: 'skeleton', id: 'requests-loading' }, h('span', {}), h('span', {})) : null,
        emptyBox, incomingSection, outgoingSection)));
  refresh().then(() => document.getElementById('requests-loading')?.remove());
}
