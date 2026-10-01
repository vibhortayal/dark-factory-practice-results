// The balance panel: available funds are the headline, total and held are secondary.
import { h } from '../lib/dom.js';

export function walletPanel(ctx, { withRefresh = false, onRefresh = () => {} } = {}) {
  const body = h('div', { class: 'wallet-body', 'aria-busy': 'true' }, h('p', { class: 'muted skeleton' }, 'Loading your balance…'));
  const refreshButton = withRefresh
    ? h('button', { type: 'button', class: 'btn btn-quiet', testid: 'wallet-refresh', onClick: () => onRefresh() }, 'Refresh')
    : null;
  const el = h('section', { class: 'card wallet-card', 'aria-label': 'Wallet' },
    h('div', { class: 'wallet-head' }, h('h2', { class: 'card-title' }, 'Available to spend'), refreshButton),
    body);

  function apply(raw) {
    // A stage-1 service answers /me without total/available/held: fall back to the balance.
    const total = raw.total ?? raw.balance;
    const held = raw.held ?? 0;
    const me = { total, held, available: raw.available ?? total - held };
    const amountEl = (testid, minor, cls) => h('span', { testid, class: cls, 'data-amount': String(minor) }, ctx.fmt(minor));
    const children = [
      h('p', { class: 'wallet-available' }, amountEl('wallet-available', me.available, 'amount-xl')),
      h('dl', { class: 'wallet-secondary' },
        h('div', {}, h('dt', {}, 'Total'), h('dd', {}, amountEl('wallet-balance', me.total, 'amount-md'))),
        me.held > 0 ? h('div', { class: 'is-held' }, h('dt', {}, 'On hold'), h('dd', {}, amountEl('wallet-held', me.held, 'amount-md'))) : null),
    ];
    body.replaceChildren(...children.filter(Boolean));
    body.removeAttribute('aria-busy');
  }
  return { el, apply };
}
