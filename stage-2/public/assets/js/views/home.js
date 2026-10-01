// "/": balance, pay / request / hold forms and the activity feed.
import { h } from '../lib/dom.js';
import { call } from '../lib/api.js';
import { walletPanel } from './wallet.js';
import { feedSection } from './feed.js';
import { transferForm, payFormConfig, requestFormConfig, authorizeFormConfig } from './forms.js';

export function mountHome(main, ctx) {
  const wallet = walletPanel(ctx, { withRefresh: true, onRefresh: () => refresh() });
  const feed = feedSection(ctx);
  const notice = h('div', { class: 'refresh-notice' });

  // Latest refresh wins: every refresh gets a number; a response is rendered only when no
  // later refresh has already been rendered for that resource.
  let started = 0;
  const rendered = { me: 0, feed: 0 };
  let items = [];

  const showFeed = (payments, hasMore) => {
    items = payments;
    feed.render(items, hasMore, loadMore);
  };

  async function loadMore() {
    const res = await call('GET', `/activity?limit=200&offset=${items.length}`);
    if (res.kind === 'ok') showFeed([...items, ...res.data.payments], res.data.has_more);
  }

  function refresh() {
    const seq = ++started;
    let failed = false;
    const done = () => { notice.replaceChildren(failed ? h('p', { class: 'alert alert-warning', role: 'status' }, 'Could not refresh just now. Your form is untouched; try Refresh again.') : ''); };
    const meRead = call('GET', '/me').then((res) => {
      if (res.kind === 'unauthenticated') return ctx.signOut();
      if (res.kind !== 'ok') { failed = true; return; }
      if (seq < rendered.me) return;
      rendered.me = seq;
      ctx.setMe(res.data);
      wallet.apply(res.data);
    });
    const feedRead = call('GET', '/activity?limit=200').then((res) => {
      if (res.kind !== 'ok') { failed = true; return; }
      if (seq < rendered.feed) return;
      rendered.feed = seq;
      showFeed(res.data.payments, res.data.has_more);
    });
    return Promise.all([meRead, feedRead]).then(done);
  }

  main.append(
    h('h1', { class: 'page-title' }, 'Your wallet'),
    wallet.el,
    notice,
    h('div', { class: 'form-grid' },
      transferForm(ctx, payFormConfig(ctx, refresh)),
      transferForm(ctx, requestFormConfig(ctx, refresh)),
      transferForm(ctx, authorizeFormConfig(ctx, refresh))),
    feed.el);

  wallet.apply(ctx.me);
  rendered.me = 0;
  refresh();
}
