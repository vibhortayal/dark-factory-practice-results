// `/`: balance, pay form, request form, authorise form and the activity feed.
import { latestWins, request } from '../api.js';
import { clear, h, icon } from '../dom.js';
import { createMoneyForm } from '../components/moneyform.js';
import { renderFeed } from '../components/feed.js';
import { createWalletSummary } from '../components/wallet.js';
import { authorizeFormOptions } from './authorizations.js';

export function mountWallet(main, ctx) {
  const summary = createWalletSummary(ctx);
  const feedBox = h('div', { class: 'feed-box', 'aria-live': 'polite' }, skeleton());
  const banner = h('div', { class: 'msg msg-error', role: 'alert', hidden: true });
  const moreBtn = h('button', { type: 'button', class: 'btn btn-quiet', hidden: true,
    onclick: () => { limit = Math.min(200, limit + 50); refresh(); } }, 'Show older activity');
  const refreshBtn = h('button', { type: 'button', class: 'btn btn-secondary', testid: 'wallet-refresh',
    onclick: () => refresh() }, icon('refresh'), 'Refresh');
  let limit = 50;
  let lastFeed = '';
  const latest = latestWins();

  function refresh() {
    refreshBtn.classList.add('is-loading');
    feedBox.setAttribute('aria-busy', 'true');
    return latest(async () => {
      const [me, feed] = await Promise.all([request('GET', '/me'), request('GET', `/activity?limit=${limit}`)]);
      if (!me.ok || !feed.ok) throw new Error('refresh failed');
      return { me: me.body, feed: feed.body };
    }, ({ me, feed }) => {
      summary.update(me);
      const signature = JSON.stringify(feed.payments);
      if (signature !== lastFeed) {
        lastFeed = signature;
        clear(feedBox).append(renderFeed(ctx, feed.payments));
      }
      moreBtn.hidden = !feed.has_more;
      banner.hidden = true;
      refreshBtn.classList.remove('is-loading');
      feedBox.removeAttribute('aria-busy');
    }, () => {
      banner.hidden = false;
      banner.replaceChildren(icon('alert'), h('span', {}, 'We could not refresh your balance and activity. Try again.'));
      refreshBtn.classList.remove('is-loading');
      feedBox.removeAttribute('aria-busy');
    });
  }

  const pay = createMoneyForm(ctx, {
    prefix: 'pay', title: 'Send money', intro: 'Pay someone by their handle. It arrives instantly.',
    handleLabel: 'Send to (handle)', handleField: 'to_handle', handleMissing: 'Enter the handle of the person you are paying.',
    endpoint: '/payments', withVisibility: true, submitLabel: 'Send money', onChange: refresh,
    successText: (payment, c) => `Sent ${c.format(payment.amount)} to @${payment.to_handle}.`,
  });
  const requestForm = createMoneyForm(ctx, {
    prefix: 'request', title: 'Request money', intro: 'Ask someone to pay you. They choose whether to pay.',
    handleLabel: 'Ask (handle)', handleField: 'payer_handle', handleMissing: 'Enter the handle of the person you are asking.',
    endpoint: '/requests', withVisibility: false, submitLabel: 'Request money', onChange: refresh,
    successText: (req, c) => `Requested ${c.format(req.amount)} from @${req.payer_handle}.`,
  });
  const authorize = createMoneyForm(ctx, authorizeFormOptions(ctx, refresh));

  main.append(
    h('h1', { class: 'sr-only' }, 'Wallet'),
    h('div', { class: 'grid wallet-grid' },
      h('div', { class: 'area-summary' }, summary.el,
        h('div', { class: 'toolbar' }, refreshBtn)),
      h('div', { class: 'area-forms' }, pay.el, requestForm.el, authorize.el),
      h('section', { class: 'area-feed card', 'aria-labelledby': 'feed-title' },
        h('h2', { id: 'feed-title', class: 'card-title' }, 'Activity'),
        banner, feedBox, h('div', { class: 'center' }, moreBtn))));
  refresh();
}

function skeleton() {
  return h('div', { class: 'skeleton', 'aria-label': 'Loading activity' },
    h('span', {}), h('span', {}), h('span', {}));
}
