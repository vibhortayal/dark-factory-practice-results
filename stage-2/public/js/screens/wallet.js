// `/`: balance, pay form, request form, hold form and the activity feed.

import { h } from '../dom.js';
import { createModel } from '../model.js';
import { normalizeMe } from '../api.js';
import { payForm, requestForm, authorizeForm } from '../components/forms.js';
import { renderBalance, loading, loadFailure } from '../components/parts.js';
import { renderFeed } from '../components/feed.js';

export function mountWallet({ api, me, main }) {
  const model = createModel({
    api,
    initial: { me, feed: null },
    sources: {
      me: (a) => a.get('/me').then(normalizeMe),
      feed: (a) => a.get('/activity?limit=100'),
    },
  });

  const balanceHost = h('section', { class: 'card balance', 'aria-label': 'Balance' });
  const feedHost = h('div', { class: 'feed-host' }, loading('Loading activity…'));
  const problem = h('div', { class: 'problem' });

  const refresh = () =>
    model.refresh().then(
      () => problem.replaceChildren(),
      () => problem.replaceChildren(loadFailure('We could not refresh your balance and activity.', refresh)),
    );

  model.subscribe((state) => {
    renderBalance(balanceHost, state.me, { onRefresh: refresh });
    renderFeed(feedHost, state.me, state.feed);
  });

  main.replaceChildren(
    h('h1', { class: 'page-title' }, 'Wallet'),
    problem,
    balanceHost,
    h('div', { class: 'grid forms' }, payForm({ api, model }), requestForm({ api, model }), authorizeForm({ api, model })),
    h('section', { class: 'card', 'aria-labelledby': 'feed-title' }, h('h2', { class: 'card-title', id: 'feed-title' }, 'Activity'), feedHost),
  );
  refresh();
}
