// `/authorizations`: hold funds for a recipient now, capture or release them later.
import { NetworkError, describeError, latestWins, newKey, request } from '../api.js';
import { clear, h, icon } from '../dom.js';
import { privacyBadge, statusBadge, when } from '../components/badges.js';
import { createMoneyForm } from '../components/moneyform.js';
import { minorToInput, parseAmount } from '../money.js';
import { createWalletSummary } from '../components/wallet.js';

// Shared with `/`, where the same form is offered.
export function authorizeFormOptions(ctx, onChange) {
  return {
    prefix: 'authorize', title: 'Hold funds', intro: 'Reserve money for someone to collect later. Nothing moves until they capture it.',
    handleLabel: 'Reserve for (handle)', handleField: 'to_handle', handleMissing: 'Enter the handle of the person you are reserving for.',
    endpoint: '/authorizations', withVisibility: true, submitLabel: 'Place hold', onChange,
    successText: (auth, c) => `Holding ${c.format(auth.amount)} for @${auth.to_handle}.`,
  };
}

export function mountAuthorizations(main, ctx) {
  const summary = createWalletSummary(ctx);
  const list = h('ul', { class: 'cards', testid: 'authorization-list' });
  const empty = h('div', { class: 'empty', testid: 'empty-authorizations', hidden: true },
    icon('clock'), h('p', { class: 'empty-title' }, 'No holds yet'),
    h('p', { class: 'hint' }, 'Holds you place, and holds placed for you to collect, appear here.'));
  const notice = h('div', { class: 'msg', hidden: true });
  const keys = new Map(); // capture attempts: `${id}:${amount}` -> key
  const latest = latestWins();
  const drafts = new Map(); // typed capture amounts, kept across list refreshes: id -> {text, remaining}
  let lastSignature = '';

  function say(kind, testid, text) {
    notice.hidden = !text;
    notice.className = `msg msg-${kind}`;
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
      const [me, auths] = await Promise.all([request('GET', '/me'), request('GET', '/authorizations?limit=200')]);
      if (!me.ok || !auths.ok) throw new Error('refresh failed');
      return { me: me.body, auths: auths.body.authorizations };
    }, ({ me, auths }) => {
      summary.update(me);
      const signature = JSON.stringify(auths);
      if (signature !== lastSignature) {   // an unchanged list keeps its inputs and focus
        lastSignature = signature;
        clear(list).append(...auths.map((a) => card(a)));
      }
      empty.hidden = auths.length > 0;
      loading.remove();
    }, () => say('error', 'authorization-load-error', 'We could not load your holds. Try again.'));
  }

  async function act(work) {
    say('error', 'authorization-error', '');
    try {
      const result = await work();
      if (!result.ok) say('error', 'authorization-error', describeError(result));
    } catch (err) {
      if (!(err instanceof NetworkError)) throw err;
      say('uncertain', 'authorization-uncertain', 'We could not confirm that went through. Press the same button again to retry safely.');
    }
    await refresh();
  }

  function captureControls(auth) {
    const id = auth.authorization_id;
    const draft = drafts.get(id);
    const input = h('input', { id: `capture-${id}`, testid: `authorization-capture-amount-${id}`, type: 'text', inputmode: 'decimal',
      autocomplete: 'off', value: draft && draft.remaining === auth.remaining_amount
        ? draft.text : minorToInput(auth.remaining_amount, ctx.me.minor_units) });
    input.addEventListener('input', () => drafts.set(id, { text: input.value, remaining: auth.remaining_amount }));
    return h('div', { class: 'capture' },
      h('div', { class: 'field' }, h('label', { for: input.id }, 'Amount to capture'), input),
      h('button', { type: 'button', class: 'btn btn-primary', testid: `authorization-capture-${id}`, onclick: () => {
        const parsed = parseAmount(input.value, ctx.me.minor_units);
        if (!parsed.ok) { say('error', 'authorization-error', parsed.message); return; }
        const slot = `${id}:${parsed.minor}`;
        if (!keys.has(slot)) keys.set(slot, newKey());
        act(async () => {
          const result = await request('POST', `/authorizations/${encodeURIComponent(id)}/capture`,
            { body: { amount: parsed.minor }, key: keys.get(slot) });
          keys.delete(slot);
          return result;
        });
      } }, 'Capture'));
  }

  function card(auth) {
    const id = auth.authorization_id;
    const outgoing = auth.from_user_id === ctx.me.user_id;
    const open = auth.status === 'open';
    return h('li', { class: `card auth auth-${auth.status}`, testid: `authorization-item-${id}`, 'data-status': auth.status },
      h('div', { class: 'request-head' },
        h('p', { class: 'request-who' }, outgoing ? 'Held for ' : 'Held by ', h('strong', {}, `@${outgoing ? auth.to_handle : auth.from_handle}`)),
        statusBadge(auth.status)),
      h('p', { class: 'request-amount' }, h('span', { class: 'label' }, 'Authorised '),
        h('span', { testid: `authorization-amount-${id}`, text: ctx.format(auth.amount) })),
      auth.status === 'captured' ? h('p', { class: 'meta' }, h('span', { class: 'label' }, 'Captured '),
        h('span', { testid: `authorization-captured-${id}`, text: ctx.format(auth.captured_amount) })) : null,
      open && auth.captured_amount > 0 ? h('p', { class: 'meta' }, `Captured so far ${ctx.format(auth.captured_amount)}; ${ctx.format(auth.remaining_amount)} still held.`) : null,
      auth.note ? h('p', { class: 'request-note', text: auth.note }) : null,
      h('p', { class: 'meta' }, privacyBadge(auth.visibility), h('span', { class: 'label' }, 'Expires '),
        h('time', { datetime: auth.expires_at, title: when(auth.expires_at) }, h('span', { testid: `authorization-expires-${id}`, text: auth.expires_at }))),
      open && !outgoing ? captureControls(auth) : null,
      open && outgoing ? h('div', { class: 'form-actions' },
        h('button', { type: 'button', class: 'btn btn-secondary', testid: `authorization-void-${id}`,
          onclick: () => act(() => request('POST', `/authorizations/${encodeURIComponent(id)}/void`)) }, 'Release hold')) : null);
  }

  const authorize = createMoneyForm(ctx, authorizeFormOptions(ctx, refresh));
  const loading = h('div', { class: 'skeleton' }, h('span', {}), h('span', {}));
  main.append(
    h('h1', { class: 'page-title' }, 'Holds'),
    h('div', { class: 'grid requests-grid' },
      h('div', { class: 'area-summary' }, summary.el, authorize.el),
      h('div', { class: 'area-main' }, notice, loading, empty, list)));
  refresh();
}
