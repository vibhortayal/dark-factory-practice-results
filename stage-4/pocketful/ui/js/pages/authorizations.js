// `/authorizations`: holds you placed or can collect, with capture and void.
import { call, describe, newKey } from '../api.js';
import { badge, emptyPanel, errorPanel, loadingPanel, money, walletCard } from '../components.js';
import { formatWhen, h, relativeTo, replace, tid } from '../dom.js';
import { formatPlain, parseDecimal } from '../money.js';
import { app, loadMe, setMe } from '../session.js';
import { authorizeForm } from './home.js';

const STATUS_LABEL = { open: 'Open', captured: 'Captured', voided: 'Voided', expired: 'Expired' };
const drafts = new Map();   // authorization id -> { amount, keep, edited, key }

export function render(root) {
  let alive = true;
  let latest = 0;
  const walletSlot = h('div', { class: 'slot' });
  const messages = h('div', { class: 'messages', 'aria-live': 'polite' });
  const listSlot = h('div');
  const say = (kind, id, text) => replace(messages, h('p', { class: `msg msg-${kind}`, role: kind === 'ok' ? 'status' : 'alert', ...tid(id) }, text));

  function draftFor(authorization) {
    const id = authorization.authorization_id;
    if (!drafts.has(id)) drafts.set(id, { edited: false, keep: false, key: null });
    const draft = drafts.get(id);
    if (!draft.edited) draft.amount = formatPlain(authorization.remaining_amount, app.me.minor_units);
    return draft;
  }

  function captureControls(authorization) {
    const id = authorization.authorization_id;
    const draft = draftFor(authorization);
    const amount = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: draft.amount, ...tid(`authorization-capture-amount-${id}`) });
    const keep = h('input', { type: 'checkbox', checked: draft.keep ? true : null, id: `keep-${id}` });
    const onEdit = () => { draft.edited = true; draft.amount = amount.value; draft.keep = keep.checked; draft.key = null; };
    amount.addEventListener('input', onEdit);
    keep.addEventListener('change', onEdit);
    amount.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); capture(authorization, amount, keep); } });
    return h('div', { class: 'capture' },
      h('div', { class: 'field' }, h('label', { for: `amt-${id}` }, `Amount to collect (${app.me.currency})`), (amount.id = `amt-${id}`, amount)),
      h('div', { class: 'check' }, keep, h('label', { for: `keep-${id}` }, 'Keep the rest on hold')),
      h('button', { type: 'button', class: 'btn btn-primary', ...tid(`authorization-capture-${id}`), onclick: () => capture(authorization, amount, keep) }, 'Collect'));
  }

  function item(authorization) {
    const me = app.me;
    const id = authorization.authorization_id;
    const outgoing = authorization.from_handle === me.handle;
    const open = authorization.status === 'open';
    return h('li', { class: `auth-item status-${authorization.status}`, ...tid(`authorization-item-${id}`), 'data-status': authorization.status },
      h('div', { class: 'feed-row' },
        h('div', { class: 'feed-people' },
          badge(STATUS_LABEL[authorization.status] || authorization.status, authorization.status),
          h('span', { class: 'parties' }, outgoing ? `You → ${authorization.to_handle}` : `${authorization.from_handle} → you`)),
        h('span', { class: 'amount', ...tid(`authorization-amount-${id}`) }, money(me, authorization.amount))),
      authorization.note ? h('p', { class: 'note' }, authorization.note) : null,
      h('dl', { class: 'facts' },
        authorization.status === 'captured' ? h('div', {}, h('dt', {}, 'Captured'),
          h('dd', { ...tid(`authorization-captured-${id}`) }, money(me, authorization.captured_amount))) : null,
        open && authorization.captured_amount > 0 ? h('div', {}, h('dt', {}, 'Collected so far'), h('dd', {}, money(me, authorization.captured_amount))) : null,
        open ? h('div', {}, h('dt', {}, 'Still on hold'), h('dd', {}, money(me, authorization.remaining_amount))) : null,
        h('div', {}, h('dt', {}, open ? 'Expires' : 'Expiry'),
          h('dd', {}, h('span', { ...tid(`authorization-expires-${id}`) }, authorization.expires_at),
            open ? h('span', { class: 'hint' }, ` (${relativeTo(authorization.expires_at)})`) : null)),
        h('div', {}, h('dt', {}, 'Visibility'), h('dd', {}, authorization.visibility === 'private' ? 'Private' : 'Public'))),
      h('div', { class: 'feed-meta' }, h('time', { datetime: authorization.created_at }, `Placed ${formatWhen(authorization.created_at)}`)),
      open && !outgoing ? captureControls(authorization) : null,
      open && outgoing ? h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn btn-secondary', ...tid(`authorization-void-${id}`), onclick: () => voidIt(authorization) }, 'Release hold')) : null);
  }

  async function finish(result, okText) {
    if (!alive) return;
    if (result.kind === 'ok') say('ok', 'authorization-success', okText);
    else if (result.kind === 'refused') say('error', 'authorization-error', describe(result));
    else say('uncertain', 'authorization-uncertain', 'We could not confirm what happened. Press the button again to retry safely, or refresh.');
    if (result.kind !== 'uncertain') await refresh();
  }

  async function capture(authorization, amountInput, keepInput) {
    const id = authorization.authorization_id;
    const parsed = parseDecimal(amountInput.value, app.me.minor_units);
    if (!parsed.ok) { say('error', 'authorization-error', parsed.error); return; }
    const draft = drafts.get(id);
    const body = { amount: parsed.minor };
    if (keepInput.checked) body.final = false;
    if (!draft.key) draft.key = newKey();
    say('pending', 'authorization-pending', 'Working on it…');
    const result = await call('POST', `/authorizations/${encodeURIComponent(id)}/capture`, { body, key: draft.key });
    if (result.kind === 'ok') drafts.delete(id);
    await finish(result, `Collected ${money(app.me, parsed.minor)}.`);
  }

  async function voidIt(authorization) {
    say('pending', 'authorization-pending', 'Working on it…');
    const result = await call('POST', `/authorizations/${encodeURIComponent(authorization.authorization_id)}/void`);
    await finish(result, 'Hold released.');
  }

  const paintWallet = () => replace(walletSlot, walletCard(app.me, {}));

  async function refresh() {
    const seq = ++latest;
    const [me, list] = await Promise.all([call('GET', '/me'), call('GET', '/authorizations?limit=200')]);
    if (!alive || seq !== latest) return;
    if (me.kind === 'ok') setMe(me.data);
    paintWallet();
    if (list.kind === 'ok') {
      const items = list.data.authorizations;
      replace(listSlot, items.length === 0
        ? emptyPanel('empty-authorizations', 'No authorizations yet', 'Holds you place, or that others place for you, appear here.')
        : h('ul', { class: 'auth-list', ...tid('authorization-list') }, items.map(item)));
    } else if (list.status === 404) {   // a stage-1 service has no authorizations
      replace(listSlot, emptyPanel('empty-authorizations', 'No authorizations yet', 'Holds you place, or that others place for you, appear here.'));
    } else {
      replace(listSlot, errorPanel('Authorizations could not be loaded.', refresh, 'authorization-load-error'));
    }
  }

  async function start() {
    replace(root, loadingPanel('Loading authorizations…'));
    const result = await loadMe();
    if (!alive) return;
    if (result.kind !== 'ok') {
      if (result.kind !== 'refused') replace(root, errorPanel('This page could not be loaded.', start));
      return;
    }
    replace(root, h('h1', {}, 'Authorizations'),
      h('div', { class: 'layout' },
        h('div', { class: 'col col-main' }, walletSlot, authorizeForm(app.me, () => refresh())),
        h('section', { class: 'col col-side card', 'aria-labelledby': 'auth-title' },
          h('h2', { id: 'auth-title' }, 'Holds'), messages, listSlot)));
    paintWallet();
    replace(listSlot, loadingPanel('Loading holds…'));
    refresh();
  }

  start();
  return () => { alive = false; };
}
