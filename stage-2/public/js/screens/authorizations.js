// `/authorizations`: wallet numbers, the hold form and the list of holds with capture / void.

import { h, textField, createFeedback } from '../dom.js';
import { createModel } from '../model.js';
import { normalizeMe, ApiError } from '../api.js';
import { RetryIdentity } from '../retry.js';
import { refusalText } from '../text.js';
import { parseDecimal, toTypedDecimal } from '../money.js';
import { authorizeForm } from '../components/forms.js';
import { renderBalance, statusBadge, privacyMark, timeTag, money, empty, loading, loadFailure } from '../components/parts.js';

export function mountAuthorizations({ api, me, main }) {
  const model = createModel({
    api,
    initial: { me, auths: null },
    sources: {
      me: (a) => a.get('/me').then(normalizeMe),
      auths: (a) => a.get('/authorizations?limit=200'),
    },
  });
  const retries = new Map();
  const balanceHost = h('section', { class: 'card balance', 'aria-label': 'Balance' });
  const listHost = h('div', { class: 'list-host' }, loading('Loading holds…'));
  const problem = h('div', { class: 'problem' });
  const messages = h('div', { class: 'messages' });
  const feedback = createFeedback(messages, { error: 'authorization-error', uncertain: 'authorization-uncertain', success: 'authorization-success' });

  const refresh = () =>
    model.refresh().then(
      () => problem.replaceChildren(),
      () => problem.replaceChildren(loadFailure('We could not load your holds.', refresh)),
    );

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

  function item(a) {
    const meNow = model.state.me;
    const outgoing = a.from_user_id === meNow.user_id;
    const incoming = a.to_user_id === meNow.user_id;
    const open = a.status === 'open';
    const id = encodeURIComponent(a.authorization_id);
    let capture = null;
    if (incoming && open) {
      const input = textField({ label: 'Capture amount', testid: `authorization-capture-amount-${a.authorization_id}`, inputmode: 'decimal', value: toTypedDecimal(a.remaining_amount, meNow.minor_units), autocomplete: 'off' });
      const keepOpen = h('input', { type: 'checkbox', id: `keep-${a.authorization_id}`, testid: `authorization-keep-open-${a.authorization_id}` });
      const submit = () => {
        const parsed = parseDecimal(input.input.value, meNow.minor_units);
        if (!parsed.ok) {
          feedback.show('error', parsed.reason);
          return;
        }
        const body = keepOpen.checked ? { amount: parsed.minor, final: false } : { amount: parsed.minor };
        if (!retries.has(a.authorization_id)) retries.set(a.authorization_id, new RetryIdentity());
        const key = retries.get(a.authorization_id).keyFor(JSON.stringify(body));
        return act(() => api.post(`/authorizations/${id}/capture`, body, key), 'Captured.');
      };
      capture = h('div', { class: 'capture' },
        input.wrap,
        h('div', { class: 'check' }, keepOpen, h('label', { for: `keep-${a.authorization_id}` }, 'Keep the rest on hold')),
        h('button', { type: 'button', class: 'btn btn-primary', testid: `authorization-capture-${a.authorization_id}`, onclick: submit }, 'Capture'));
    }
    const voidButton = outgoing && open
      ? h('button', { type: 'button', class: 'btn btn-secondary', testid: `authorization-void-${a.authorization_id}`, onclick: () => act(() => api.post(`/authorizations/${id}/void`), 'Hold released.') }, 'Release hold')
      : null;
    return h('li', { class: `row-item status-${a.status}`, testid: `authorization-item-${a.authorization_id}`, 'data-status': a.status },
      h('div', { class: 'row-main' },
        h('p', { class: 'row-title' }, outgoing ? `Hold for ${a.to_handle}` : `Hold from ${a.from_handle}`, ' ', statusBadge(a.status)),
        h('p', { class: 'row-note' }, a.note),
        h('p', { class: 'row-meta' }, 'Placed ', timeTag(a.created_at), ' ', privacyMark(a.visibility)),
        h('p', { class: 'row-meta' }, 'Expires ', h('span', { class: 'mono', testid: `authorization-expires-${a.authorization_id}` }, a.expires_at)),
        a.status === 'captured' && h('p', { class: 'row-meta' }, 'Captured ', h('strong', { testid: `authorization-captured-${a.authorization_id}` }, money(meNow, a.captured_amount))),
        open && a.captured_amount > 0 && h('p', { class: 'row-meta' }, `${money(meNow, a.captured_amount)} captured so far, ${money(meNow, a.remaining_amount)} still held`)),
      h('div', { class: 'row-side' },
        h('span', { class: 'row-amount', testid: `authorization-amount-${a.authorization_id}` }, money(meNow, a.amount)),
        capture, voidButton && h('div', { class: 'row-actions' }, voidButton)));
  }

  model.subscribe((state) => {
    renderBalance(balanceHost, state.me, { onRefresh: refresh });
    if (!state.auths) return;
    listHost.replaceChildren(
      h('ul', { class: 'rows', testid: 'authorization-list' }, state.auths.authorizations.map(item)),
      state.auths.authorizations.length === 0 && empty('empty-authorizations', 'No holds yet', 'A hold reserves money for someone to collect later.'),
    );
  });

  main.replaceChildren(
    h('h1', { class: 'page-title' }, 'Holds'),
    problem, balanceHost,
    h('div', { class: 'grid two' },
      authorizeForm({ api, model }),
      h('section', { class: 'card', 'aria-labelledby': 'holds-title' }, h('h2', { class: 'card-title', id: 'holds-title' }, 'Your holds'), messages, listHost)),
  );
  refresh();
}
