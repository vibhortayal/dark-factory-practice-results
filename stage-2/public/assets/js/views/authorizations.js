// "/authorizations": holds you placed and holds placed for you, with capture and void.
import { h, field } from '../lib/dom.js';
import { call } from '../lib/api.js';
import { RetryIdentity } from '../lib/retry.js';
import { refusalText, UNCERTAIN_TEXT } from '../lib/feedback.js';
import { parseAmount, formatPlain } from '../money.js';
import { walletPanel } from './wallet.js';
import { rememberFocus, restoreFocus } from '../lib/focus.js';
import { transferForm, authorizeFormConfig } from './forms.js';

const STATUS_LABEL = { open: 'Open', captured: 'Captured', voided: 'Voided', expired: 'Expired' };
const when = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export function mountAuthorizations(main, ctx) {
  const wallet = walletPanel(ctx);
  const status = h('div', { class: 'form-status', 'aria-live': 'polite' });
  const holder = h('div', { class: 'list-holder' }, h('p', { class: 'muted skeleton' }, 'Loading holds…'));
  const identities = new Map(); // authorization id -> RetryIdentity
  // What the user has typed into a capture row survives a list refresh (while the hold stays actionable).
  const edits = new Map(); // authorization id -> { amount?: string, keep?: boolean }
  const edit = (id) => { if (!edits.has(id)) edits.set(id, {}); return edits.get(id); };

  let started = 0;
  let rendered = 0;
  let renderedMe = 0;

  const show = (kind, text) => status.replaceChildren(text ? h('p', { class: `alert alert-${kind}`, testid: `authorization-${kind}`, role: 'alert' }, text) : '');

  async function refresh() {
    const seq = ++started;
    const meRead = call('GET', '/me').then((res) => {
      if (res.kind === 'unauthenticated') return ctx.signOut();
      if (res.kind === 'ok' && seq >= renderedMe) { renderedMe = seq; ctx.setMe(res.data); wallet.apply(res.data); }
    });
    const listRead = call('GET', '/authorizations?limit=200').then((res) => {
      if (res.kind === 'unauthenticated') return ctx.signOut();
      if (res.kind !== 'ok') {
        holder.replaceChildren(h('p', { class: 'alert alert-warning', role: 'status' }, 'Could not load holds. ', h('button', { type: 'button', class: 'btn btn-quiet', onClick: refresh }, 'Try again')));
        return;
      }
      if (seq < rendered) return;
      rendered = seq;
      render(res.data.authorizations);
    });
    await Promise.all([meRead, listRead]);
  }

  // Past its deadline a hold is expired even if this page has not been refreshed yet.
  const effective = (a) => (a.status === 'open' && Date.parse(a.expires_at) <= Date.now() ? 'expired' : a.status);

  function render(list) {
    const focus = rememberFocus();
    const actionable = new Set(list.filter((a) => effective(a) === 'open' && a.to_user_id === ctx.me.user_id).map((a) => a.authorization_id));
    for (const id of [...edits.keys()]) if (!actionable.has(id)) edits.delete(id);
    const rows = list.map(item);
    holder.replaceChildren(...[
      h('ul', { class: 'rows', testid: 'authorization-list' }, rows),
      list.length === 0
        ? h('div', { class: 'empty', testid: 'empty-authorizations' },
          h('p', { class: 'empty-title' }, 'No holds yet'),
          h('p', { class: 'muted' }, 'Place a hold to reserve money for someone, or wait for one to be placed for you.'))
        : null,
    ].filter(Boolean));
    restoreFocus(focus);
  }

  function item(a) {
    const state = effective(a);
    const mine = ctx.me.user_id;
    const outgoing = a.from_user_id === mine;
    const id = a.authorization_id;
    const controls = [];
    if (state === 'open' && !outgoing && a.to_user_id === mine) controls.push(captureControls(a));
    if (state === 'open' && outgoing) {
      const v = h('button', { type: 'button', class: 'btn btn-secondary', testid: `authorization-void-${id}` }, 'Release hold');
      v.addEventListener('click', () => voidHold(a, v));
      controls.push(h('div', { class: 'action-row' }, v));
    }
    return h('li', { class: `row-item status-${state}`, testid: `authorization-item-${id}`, 'data-status': state },
      h('div', { class: 'row-main' },
        h('p', { class: 'row-title' }, outgoing ? `Held for @${a.to_handle}` : `Held for you by @${a.from_handle}`),
        h('p', { class: 'row-note' }, a.note),
        h('p', { class: 'row-meta' },
          h('span', { class: `badge badge-status-${state}` }, STATUS_LABEL[state] || state),
          h('span', { class: 'badge' }, a.visibility === 'private' ? 'Private' : 'Public'),
          a.captured_amount > 0 && state !== 'captured' ? h('span', { class: 'muted' }, `Captured ${ctx.fmt(a.captured_amount)} so far`) : null),
        h('p', { class: 'row-meta' }, h('span', { class: 'muted' }, state === 'expired' ? 'Expired ' : 'Expires '), h('time', { class: 'mono', datetime: a.expires_at, testid: `authorization-expires-${id}` }, a.expires_at))),
      h('div', { class: 'row-figures' },
        h('p', { class: 'row-amount', testid: `authorization-amount-${id}` }, ctx.fmt(a.amount)),
        a.status === 'captured' ? h('p', { class: 'row-sub' }, 'Captured ', h('span', { testid: `authorization-captured-${id}` }, ctx.fmt(a.captured_amount))) : null,
        state === 'open' && a.captured_amount > 0 ? h('p', { class: 'row-sub' }, `${ctx.fmt(a.remaining_amount)} still held`) : null),
      ...controls);
  }

  function captureControls(a) {
    const id = a.authorization_id;
    const saved = edits.get(id) || {};
    const amount = field({ id: `capture-amount-${id}`, label: 'Capture amount', testid: `authorization-capture-amount-${id}`, inputmode: 'decimal', autocomplete: 'off', value: saved.amount ?? formatPlain(a.remaining_amount, ctx.cfg.minor_units) });
    const rest = h('input', { type: 'checkbox', id: `capture-rest-${id}`, testid: `authorization-keep-${id}` });
    rest.checked = saved.keep === true;
    amount.input.addEventListener('input', () => { edit(id).amount = amount.input.value; });
    rest.addEventListener('change', () => { edit(id).keep = rest.checked; });
    const button = h('button', { type: 'button', class: 'btn btn-primary', testid: `authorization-capture-${id}` }, 'Capture');
    button.addEventListener('click', async () => {
      if (!identities.has(id)) identities.set(id, new RetryIdentity());
      const identity = identities.get(id);
      if (identity.busy) return;
      const parsed = parseAmount(amount.input.value, ctx.cfg.minor_units);
      if (!parsed.ok) { show('error', parsed.error); return; }
      const body = { amount: parsed.minor };
      if (rest.checked) body.final = false;
      const key = identity.keyFor(JSON.stringify([amount.input.value, rest.checked]));
      identity.busy = true;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.textContent = 'Capturing…';
      const res = await call('POST', `/authorizations/${encodeURIComponent(id)}/capture`, { body, key });
      identity.busy = false;
      if (button.isConnected) { button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = 'Capture'; }
      if (res.kind === 'ok' || res.kind === 'refused') edits.delete(id); // the row is re-rendered from fresh data
      await settle(res);
    });
    return h('div', { class: 'action-row' }, amount.wrap,
      h('div', { class: 'check' }, rest, h('label', { for: `capture-rest-${id}` }, 'Keep the rest on hold')), button);
  }

  async function voidHold(a, button) {
    if (button.disabled) return;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    const res = await call('POST', `/authorizations/${encodeURIComponent(a.authorization_id)}/void`);
    if (button.isConnected) { button.disabled = false; button.removeAttribute('aria-busy'); }
    await settle(res);
  }

  async function settle(res) {
    if (res.kind === 'ok') { show('error', ''); await refresh(); return; }
    if (res.kind === 'refused') { show('error', refusalText(res)); await refresh(); return; }
    if (res.kind === 'unauthenticated') return ctx.signOut();
    show('uncertain', UNCERTAIN_TEXT);
  }

  main.append(
    h('h1', { class: 'page-title' }, 'Holds'),
    wallet.el,
    transferForm(ctx, authorizeFormConfig(ctx, refresh)),
    status,
    h('section', { class: 'card', 'aria-labelledby': 'holds-title' }, h('h2', { id: 'holds-title', class: 'card-title' }, 'All holds'), holder));
  wallet.apply(ctx.me);
  refresh();
}
