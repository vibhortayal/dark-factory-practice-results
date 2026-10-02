// `/`: wallet, pay form, request form, authorize form and the activity feed.
import { call } from '../api.js';
import { errorPanel, loadingPanel, money, sendForm, walletCard } from '../components.js';
import { h, replace } from '../dom.js';
import { feedView } from '../feed.js';
import { app, loadMe, setMe } from '../session.js';

export function authorizeForm(me, onDone) {
  return sendForm({
    prefix: 'authorize', title: 'Reserve money for someone',
    intro: 'Place a hold now; they collect it later, in full or in parts.',
    handleLabel: 'Recipient handle', handleKey: 'to_handle', path: '/authorizations',
    button: 'Place hold', withVisibility: true,
    successText: (data) => `Holding ${money(me, data.amount)} for ${data.to_handle}.`,
    uncertainText: 'We could not confirm whether the hold was placed. Your form is unchanged: press the button again to retry safely.',
  }, me, onDone);
}

export function render(root) {
  let alive = true;
  let latest = 0;
  let refreshing = false;
  const walletSlot = h('div', { class: 'slot' });
  const feedSlot = h('section', { class: 'card', 'aria-labelledby': 'feed-title' });
  const formsSlot = h('div', { class: 'stack' });

  const paintWallet = () => replace(walletSlot, walletCard(app.me, { onRefresh: () => refresh(), refreshing }));

  async function refresh() {
    const seq = ++latest;       // latest refresh wins: older responses are dropped
    refreshing = true;
    if (app.me) paintWallet();
    const [me, feed] = await Promise.all([call('GET', '/me'), call('GET', '/activity?limit=200')]);
    if (!alive || seq !== latest) return;
    refreshing = false;
    if (me.kind === 'ok') setMe(me.data);
    if (app.me) paintWallet();
    if (feed.kind === 'ok') {
      replace(feedSlot, h('h2', { id: 'feed-title' }, 'Activity'), feedView(feed.data.payments, app.me, feed.data.has_more));
    } else {
      replace(feedSlot, h('h2', { id: 'feed-title' }, 'Activity'),
        errorPanel('The activity feed could not be loaded.', () => refresh(), 'feed-error'));
    }
  }

  async function start() {
    replace(root, loadingPanel('Loading your wallet…'));
    const result = await loadMe();
    if (!alive) return;
    if (result.kind !== 'ok') {
      if (result.kind !== 'refused') replace(root, errorPanel('Your wallet could not be loaded.', start));
      return;
    }
    const me = app.me;
    replace(formsSlot,
      sendForm({
        prefix: 'pay', title: 'Send money', handleLabel: 'Recipient handle', handleKey: 'to_handle',
        path: '/payments', button: 'Send payment', withVisibility: true,
        successText: (data) => `Sent ${money(me, data.amount)} to ${data.to_handle}.`,
        uncertainText: 'We could not confirm whether this payment went through. Your form is unchanged: press Send payment again to retry — it will not pay twice.',
      }, me, () => refresh()),
      sendForm({
        prefix: 'request', title: 'Request money', handleLabel: 'Ask this handle to pay', handleKey: 'payer_handle',
        path: '/requests', button: 'Send request', withVisibility: false,
        successText: (data) => `Asked ${data.payer_handle} for ${money(me, data.amount)}.`,
        uncertainText: 'We could not confirm whether the request was sent. Press Send request again to retry safely.',
      }, me, () => refresh()),
      authorizeForm(me, () => refresh()));
    replace(root,
      h('h1', { class: 'sr-only' }, 'Wallet'),
      h('div', { class: 'layout' },
        h('div', { class: 'col col-main' }, walletSlot, formsSlot),
        h('div', { class: 'col col-side' }, feedSlot)));
    paintWallet();
    replace(feedSlot, h('h2', { id: 'feed-title' }, 'Activity'), loadingPanel('Loading activity…'));
    refresh();
  }

  start();
  return () => { alive = false; };
}
