// The balance block: available is the headline, total and held are secondary.
import { h } from '../dom.js';

export function createWalletSummary(ctx) {
  const el = h('section', { class: 'card hero', 'aria-labelledby': 'hero-label' });

  function update(me) {
    ctx.me = me;
    const money = (minor) => ctx.format(minor);
    const held = Number(me.held) > 0;
    el.replaceChildren(...[
      h('p', { id: 'hero-label', class: 'hero-label' }, 'Available to spend'),
      h('p', { class: 'hero-amount', testid: 'wallet-available', 'data-amount': me.available,
        text: money(me.available) }),
      h('dl', { class: 'hero-meta' },
        h('div', { class: 'hero-meta-item' },
          h('dt', {}, 'Total balance'),
          h('dd', { testid: 'wallet-balance', 'data-amount': me.total ?? me.balance,
            text: money(me.total ?? me.balance) })),
        held ? h('div', { class: 'hero-meta-item hero-held' },
          h('dt', {}, 'On hold'),
          h('dd', { testid: 'wallet-held', 'data-amount': me.held, text: money(me.held) })) : null),
      held ? h('p', { class: 'hint' }, 'Held money is reserved for authorisations and cannot be spent until it is released.') : null,
    ].filter(Boolean));
  }

  update(ctx.me);
  return { el, update };
}
