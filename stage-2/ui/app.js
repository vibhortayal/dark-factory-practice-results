/* Pocketful web client. Plain JavaScript, no dependencies, no external requests.
 * Data and actions go through the documented JSON API of this origin with a bearer token.
 * Every answer is normalised in one place (norm*) before it is rendered, and every panel loads,
 * fails and renders on its own, so one bad answer never blanks another part of a screen. */
(function () {
  'use strict';

  var TOKEN_KEY = 'pocketful.token';
  var USER_KEY = 'pocketful.user';

  // ---------------------------------------------------------------- storage
  function load(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) {
    try { if (v == null) window.localStorage.removeItem(k); else window.localStorage.setItem(k, v); } catch (e) { /* ignore */ }
  }

  // ---------------------------------------------------------- value helpers
  function isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
  function isInt(v) { return typeof v === 'number' && isFinite(v) && Math.floor(v) === v; }
  function str(v, d) { return typeof v === 'string' ? v : (d === undefined ? '' : d); }
  function intOr(v, d) { return isInt(v) ? v : d; }
  function vis(v) { return v === 'private' ? 'private' : 'public'; }

  var S = { token: load(TOKEN_KEY), user: null, me: null, cur: 'EUR', mu: 2 };
  try { S.user = JSON.parse(load(USER_KEY) || 'null'); } catch (e) { S.user = null; }
  if (!isObj(S.user)) S.user = null;

  // -------------------------------------------------------------------- DOM
  function h(tag, props, kids) {
    var el = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v == null || v === false) return;
      if (k === 'cls') el.className = v;
      else if (k === 'tid') el.setAttribute('data-testid', v);
      else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) {
      if (c == null || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  function field(id, label, control, hint) {
    return h('div', { cls: 'field' }, [
      h('label', { 'for': id, text: label }),
      control,
      hint ? h('p', { cls: 'hint', id: id + '-hint', text: hint }) : null
    ]);
  }
  function textInput(id, extra) {
    var p = { id: id, tid: id, type: 'text', autocomplete: 'off', spellcheck: 'false' };
    Object.keys(extra || {}).forEach(function (k) { p[k] = extra[k]; });
    return h('input', p);
  }
  function visibilitySelect(id) {
    return h('select', { id: id, tid: id }, [
      h('option', { value: 'public', text: 'Public: shown in the activity feed' }),
      h('option', { value: 'private', text: 'Private: only you and the other person' })
    ]);
  }

  // ------------------------------------------------------------------ money
  function digits(n) { try { return BigInt(n).toString(); } catch (e) { return '0'; } }
  function plain(n) {
    var s = digits(n);
    if (S.mu === 0) return s;
    s = s.padStart(S.mu + 1, '0');
    return s.slice(0, -S.mu) + '.' + s.slice(-S.mu);
  }
  function fmt(n) { return plain(n) + ' ' + S.cur; }
  /* Exact decimal-string to minor units (digits, no leading zeros) or null. No floats. */
  function parseAmount(text) {
    var t = String(text == null ? '' : text).trim();
    var re = S.mu === 0 ? /^[0-9]+$/ : new RegExp('^[0-9]+(\\.[0-9]{1,' + S.mu + '})?$');
    if (!re.test(t)) return null;
    var parts = t.split('.');
    var frac = (parts[1] || '').padEnd(S.mu, '0');
    return (parts[0] + frac).replace(/^0+(?=[0-9])/, '');
  }
  function amountHint() {
    return S.mu === 0 ? 'Whole amounts only, for example 15.' :
      'For example 15 or 15.50 (up to ' + S.mu + ' decimal places).';
  }
  function amountError() {
    return S.mu === 0 ? 'Enter a whole amount such as 15, without decimals.' :
      'Enter an amount such as 15 or 15.50, with at most ' + S.mu + ' decimal places.';
  }

  function when(iso) {
    try {
      return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));
    } catch (e) { return String(iso); }
  }

  function newKey() {
    var a = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  // ------------------------------------------------- normalising API answers
  /* Each returns a complete, well-typed object, or null when the answer cannot be used at all. An older
   * service (before the upgrade) answers /me with `balance` only and payments without authorization_id. */
  function normMe(d) {
    if (!isObj(d) || !isInt(d.balance)) return null;
    var total = intOr(d.total, d.balance);
    var held = intOr(d.held, 0);
    return {
      user_id: str(d.user_id), display_name: str(d.display_name), handle: str(d.handle),
      balance: d.balance, total: total, available: intOr(d.available, total - held), held: held,
      currency: str(d.currency, S.cur), minor_units: [0, 2, 3].indexOf(d.minor_units) >= 0 ? d.minor_units : S.mu
    };
  }
  function normPayment(p) {
    if (!isObj(p) || typeof p.payment_id !== 'string' || !isInt(p.amount)) return null;
    return {
      payment_id: p.payment_id, from_user_id: str(p.from_user_id), from_handle: str(p.from_handle, '?'),
      to_user_id: str(p.to_user_id), to_handle: str(p.to_handle, '?'), amount: p.amount, note: str(p.note),
      visibility: vis(p.visibility), request_id: str(p.request_id, null), settlement_id: str(p.settlement_id, null),
      authorization_id: str(p.authorization_id, null), created_at: str(p.created_at)
    };
  }
  function normRequest(r) {
    if (!isObj(r) || typeof r.request_id !== 'string' || !isInt(r.amount)) return null;
    return {
      request_id: r.request_id, requester_id: str(r.requester_id), requester_handle: str(r.requester_handle, '?'),
      payer_id: str(r.payer_id), payer_handle: str(r.payer_handle, '?'), amount: r.amount, note: str(r.note),
      status: ['pending', 'paid', 'declined', 'cancelled'].indexOf(r.status) >= 0 ? r.status : 'pending',
      payment_id: str(r.payment_id, null), created_at: str(r.created_at)
    };
  }
  function normAuth(a) {
    if (!isObj(a) || typeof a.authorization_id !== 'string' || !isInt(a.amount)) return null;
    var status = ['open', 'captured', 'voided', 'expired'].indexOf(a.status) >= 0 ? a.status : 'open';
    var captured = intOr(a.captured_amount, 0);
    return {
      authorization_id: a.authorization_id, from_user_id: str(a.from_user_id), from_handle: str(a.from_handle, '?'),
      to_user_id: str(a.to_user_id), to_handle: str(a.to_handle, '?'), amount: a.amount, captured_amount: captured,
      remaining_amount: intOr(a.remaining_amount, status === 'open' ? a.amount - captured : 0), note: str(a.note),
      visibility: vis(a.visibility), status: status, expires_at: str(a.expires_at), created_at: str(a.created_at)
    };
  }
  var NORM = { payments: normPayment, requests: normRequest, authorizations: normAuth };

  // -------------------------------------------------------------------- API
  function call(method, path, o) {
    o = o || {};
    var ctl = new AbortController();
    var timer = setTimeout(function () { ctl.abort(); }, o.timeout || 15000);
    var headers = { 'Accept': 'application/json' };
    if (o.token !== false && S.token) headers.Authorization = 'Bearer ' + S.token;
    if (o.body != null) headers['Content-Type'] = 'application/json';
    if (o.key) headers['Idempotency-Key'] = o.key;
    var lost = function () { clearTimeout(timer); return { status: 0, data: null, bad: true, net: true }; };
    var req;
    try {
      req = fetch(path, { method: method, headers: headers, body: o.body, signal: ctl.signal, cache: 'no-store' });
    } catch (e) { return Promise.resolve(lost()); }
    return req.then(function (res) {
      return res.text().then(function (t) {
        clearTimeout(timer);
        var data = null, bad = false;
        if (t) { try { data = JSON.parse(t); } catch (e) { bad = true; } } else if (res.status !== 204) { bad = true; }
        var r = { status: res.status, data: data, bad: bad, net: false };
        if (r.status === 401 && o.token !== false) { signedOut(); }
        return r;
      }, lost);
    }, lost);
  }
  /* 'ok' | 'refused' (a confirmed rejection with an error body) | 'uncertain' (outcome unknown) */
  function kind(r) {
    if (r.net || r.bad) return 'uncertain';
    if (r.status >= 200 && r.status < 300) return 'ok';
    if (r.status >= 500) return 'uncertain';
    return 'refused';
  }
  function errCode(r) { return isObj(r.data) && isObj(r.data.error) ? r.data.error.code : undefined; }
  var FRIENDLY = {
    insufficient_funds: 'There is not enough available money for that. Held funds cannot be spent.',
    not_found: 'We could not find that person or item.',
    self_payment: 'You cannot send money to yourself.',
    self_request: 'You cannot request money from yourself.',
    validation_failed: 'Please check the details and try again.',
    malformed_request: 'Please check the details and try again.',
    request_not_pending: 'That request is no longer pending.',
    forbidden: 'You are not allowed to do that.',
    authorization_not_open: 'That authorization is no longer open.',
    authorization_expired: 'That authorization has expired.',
    capture_exceeds_authorization: 'That is more than is still held for this authorization.',
    idempotency_key_reuse: 'That change conflicts with an earlier attempt. Please review and try again.',
    email_taken: 'That email is already registered.',
    handle_taken: 'That email would create a handle that is already taken.',
    unauthenticated: 'Email or password is incorrect.'
  };
  function friendly(r) {
    var c = errCode(r);
    return FRIENDLY[c] || 'Something went wrong (' + (c || r.status) + ').';
  }

  /* Every page of a list, normalised. Resolves {items} or {fail: response} (never throws). */
  function loadAll(path, key) {
    var out = [];
    function page(off) {
      var sep = path.indexOf('?') < 0 ? '?' : '&';
      return call('GET', path + sep + 'limit=200&offset=' + off).then(function (r) {
        if (kind(r) !== 'ok' || !isObj(r.data) || !Array.isArray(r.data[key])) return { fail: r };
        r.data[key].forEach(function (x) { var n = NORM[key](x); if (n) out.push(n); });
        return r.data.has_more === true && r.data[key].length ? page(off + 200) : { items: out };
      });
    }
    return page(0);
  }
  function loadMe() {
    return call('GET', '/me').then(function (r) {
      var me = kind(r) === 'ok' ? normMe(r.data) : null;
      return me ? { me: me } : { fail: r };
    });
  }

  // ------------------------------------------------------------------- auth
  function signedOut() {
    S.token = null; S.user = null; S.me = null;
    save(TOKEN_KEY, null); save(USER_KEY, null);
    if (!/^\/(login|signup)$/.test(location.pathname)) location.replace('/login');
  }
  function setMe(me) {
    S.me = me; S.cur = me.currency; S.mu = me.minor_units;
    S.user = { display_name: me.display_name, handle: me.handle };
    save(USER_KEY, JSON.stringify(S.user));
    var bar = document.querySelector('.topbar');
    if (bar && S.token) bar.replaceWith(header());
  }
  /* A read of /me made to learn who is signed in (header, currency): stamped like every other read; a stale
   * answer may still fill an empty header but never replaces newer state. */
  function bootMe() {
    var id = ++refreshSeq;
    return loadMe().then(function (r) {
      if (r.me && (id >= (APPLIED.me || 0) || !S.me)) {
        if (id >= (APPLIED.me || 0)) APPLIED.me = id;
        setMe(r.me);
      }
      return r;
    });
  }
  function signIn(token) {
    S.token = token; save(TOKEN_KEY, token);
    return bootMe().then(function (r) { return !!r.me; });
  }

  // ----------------------------------------------------------------- layout
  var NAV = [['/', 'Wallet'], ['/requests', 'Requests'], ['/split', 'Split a bill'], ['/authorizations', 'Authorizations']];

  function header() {
    var path = location.pathname;
    var nav = h('nav', { cls: 'nav', 'aria-label': 'Main' });
    if (S.token) {
      NAV.forEach(function (n) {
        nav.appendChild(h('a', { href: n[0], text: n[1], 'aria-current': path === n[0] ? 'page' : null }));
      });
    } else {
      nav.appendChild(h('a', { href: '/login', text: 'Sign in', 'aria-current': path === '/login' ? 'page' : null }));
      nav.appendChild(h('a', { href: '/signup', text: 'Create account', 'aria-current': path === '/signup' ? 'page' : null }));
    }
    var who = h('div', { cls: 'who' });
    if (S.token && S.user) {
      who.appendChild(h('span', { cls: 'name', tid: 'current-user', text: str(S.user.display_name) }));
      who.appendChild(h('span', { cls: 'handle' }, ['@', h('span', { tid: 'current-handle', text: str(S.user.handle) })]));
      who.appendChild(h('button', {
        cls: 'btn secondary small', type: 'button', tid: 'logout-button', text: 'Sign out',
        onclick: function () { signedOut(); location.assign('/login'); }
      }));
    }
    return h('div', { cls: 'topbar' }, [h('div', { cls: 'topbar-in' }, [
      h('a', { cls: 'brand', href: S.token ? '/' : '/login', text: 'Pocketful' }), nav, who
    ])]);
  }

  var main;
  function shell(title, subtitle) {
    var app = document.getElementById('app');
    app.textContent = '';
    app.appendChild(h('a', { cls: 'skip', href: '#main', text: 'Skip to content' }));
    app.appendChild(header());
    main = h('main', { id: 'main' });
    main.appendChild(pageTitle(title, subtitle));
    app.appendChild(main);
    document.title = title + ' · Pocketful';
    return main;
  }
  function pageTitle(title, subtitle) {
    return h('div', { cls: 'page-title' }, [h('h1', { text: title }), subtitle ? h('p', { text: subtitle }) : null]);
  }

  function loadingState(text) { return h('p', { cls: 'state loading', role: 'status', text: text || 'Loading…' }); }
  function emptyState(tid, title, text) {
    return h('div', { cls: 'empty', tid: tid }, [h('strong', { text: title }), h('span', { text: text })]);
  }
  function failState(retry, text) {
    return h('div', { cls: 'msg error', role: 'alert' }, [
      (text || 'We could not load this right now.') + ' ',
      retry ? h('button', { cls: 'btn secondary small', type: 'button', text: 'Try again', onclick: retry }) : null
    ]);
  }
  /* Why a read failed, in words: an older service has no such screen. */
  function failText(r, what) {
    if (r && (r.status === 404 || r.status === 405)) return 'Your ' + what + ' are not available on this service.';
    return 'We could not load your ' + what + ' right now.';
  }

  /* A last resort: an unexpected script error becomes a visible message instead of a silent blank. */
  function showFatal() {
    var app = document.getElementById('app');
    if (!app || document.getElementById('fatal')) return;
    var box = h('div', { id: 'fatal', cls: 'msg error', tid: 'page-error', role: 'alert' }, [
      'Something went wrong on this page. ',
      h('button', { cls: 'btn secondary small', type: 'button', text: 'Reload', onclick: function () { location.reload(); } })]);
    var m = document.getElementById('main') || app;
    m.insertBefore(box, m.firstChild);
  }
  window.addEventListener('error', function () { showFatal(); });
  window.addEventListener('unhandledrejection', function (ev) { showFatal(); ev.preventDefault(); });

  // ------------------------------------------------------ panels and refresh
  /* A panel owns one region and one loader. Latest refresh wins per panel: a result is applied only
   * if no later refresh has already been applied to that panel. */
  var refreshSeq = 0;
  /* The single gate: every read is stamped from one counter when it is SENT, and its answer (success or failure)
   * is shown only if no read of the same resource with a higher stamp has already been shown. */
  var APPLIED = {};
  function Panel(resource, loader, render, fail) {
    this.resource = resource; this.loader = loader; this.render = render; this.fail = fail; this.ok = false;
  }
  Panel.prototype.fetch = function () {
    var done;
    try { done = this.loader(); } catch (e) { done = Promise.resolve({ fail: { status: 0 } }); }
    return done.then(function (res) { return res; }, function () { return { fail: null }; });
  };
  Panel.prototype.apply = function (id, res) {
    if (id < (APPLIED[this.resource] || 0)) return false;
    APPLIED[this.resource] = id;
    try {
      if (res && !res.fail) { this.ok = true; this.render(res); return true; }
      this.fail(res ? res.fail : null, this.ok);
    } catch (e) { showFatal(); }
    return false;
  };
  Panel.prototype.run = function (id) {
    var p = this;
    return p.fetch().then(function (res) { return p.apply(id, res); });
  };
  /* The panels of one refresh are shown together (so balance, feed and lists always agree), unless one
   * of them is slow: after a short grace period the ones that are ready are shown and the rest follow. */
  function refreshPanels(panels) {
    var id = ++refreshSeq;
    var pending = panels.length, ready = [], timer = null, flushed = false;
    function flush() {
      clearTimeout(timer);
      flushed = true;
      ready.splice(0).forEach(function (x) { x.p.apply(id, x.res); });
    }
    return Promise.all(panels.map(function (p) {
      return p.fetch().then(function (res) {
        if (flushed) { p.apply(id, res); return; }
        ready.push({ p: p, res: res });
        pending--;
        if (pending === 0) flush();
        else if (!timer) timer = setTimeout(flush, 300);
      });
    }));
  }

  // --------------------------------------------------------- messages / forms
  function setMsg(box, kindName, tid, text) {
    clearMsg(box);
    box.appendChild(h('div', { cls: 'msg ' + kindName, tid: tid, role: kindName === 'error' ? 'alert' : 'status', text: text }));
  }
  function clearMsg(box) { box.textContent = ''; }

  /* A form whose idempotency key is minted only when its values changed since the last key. */
  function keyed(formEl) {
    var k = { key: null, dirty: true, busy: false };
    var touch = function () { k.dirty = true; };
    formEl.addEventListener('input', touch);
    formEl.addEventListener('change', touch);
    k.take = function () { if (k.dirty || !k.key) { k.key = newKey(); k.dirty = false; } return k.key; };
    return k;
  }

  /* Common submit flow for pay / request / authorize / split.
   * cfg: prefix, form, box, button, build() -> {body} | {error}, path, okText(r), onDone() */
  function wireSubmit(cfg) {
    var state = keyed(cfg.form);
    var btn = cfg.button;
    cfg.form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (state.busy) return;
      var built = cfg.build();
      if (built.error) {
        setMsg(cfg.box, 'error', cfg.prefix + '-error', built.error);
        return;
      }
      var key = state.take();
      state.busy = true;
      btn.disabled = true;
      call('POST', cfg.path, { body: built.body, key: key }).then(function (r) {
        state.busy = false;
        btn.disabled = false;
        var k = kind(r);
        if (k === 'ok') {
          var text = 'Done.';
          try { text = cfg.okText(r); } catch (e) { /* an unexpected answer shape still counts as success */ }
          setMsg(cfg.box, 'success', cfg.prefix + '-success', text);
          cfg.onDone(r);
        } else if (k === 'refused') {
          setMsg(cfg.box, 'error', cfg.prefix + '-error', friendly(r));
          cfg.onDone(r);
        } else {
          setMsg(cfg.box, 'uncertain', cfg.prefix + '-uncertain',
            'We could not confirm whether this went through. Nothing has been lost: press the button again to retry safely, and it will be applied only once.');
        }
      });
    });
  }

  function handleValue(v) { return String(v || '').trim().replace(/^@/, '').toLowerCase(); }

  // ---------------------------------------------------------------- wallet
  /* The wallet frame (and its refresh button) exists from first paint; its numbers arrive later. */
  function walletCard(onRefresh) {
    var body = h('div', {}, [loadingState('Loading your wallet…')]);
    var el = h('section', { cls: 'card wallet', 'aria-label': 'Wallet' }, [body]);
    if (onRefresh) el.appendChild(h('button', { cls: 'btn ghost', type: 'button', tid: 'wallet-refresh', text: 'Refresh', onclick: onRefresh }));
    var api = { el: el };
    api.update = function (me) {
      body.textContent = '';
      body.appendChild(h('div', {}, [
        h('p', { cls: 'label', text: 'Available to spend' }),
        h('p', { cls: 'headline', tid: 'wallet-available', 'data-amount': String(me.available), text: fmt(me.available) })
      ]));
      var sec = h('div', { cls: 'secondary' }, [
        h('div', {}, [h('p', { cls: 'label', text: 'Total' }),
          h('p', { cls: 'num', tid: 'wallet-balance', 'data-amount': String(me.total), text: fmt(me.total) })])
      ]);
      if (me.held > 0) {
        sec.appendChild(h('div', { cls: 'held' }, [h('p', { cls: 'label', text: 'On hold' }),
          h('p', { cls: 'num', tid: 'wallet-held', 'data-amount': String(me.held), text: fmt(me.held) })]));
      }
      body.appendChild(sec);
    };
    /* keep the last good numbers when a later refresh fails; show the problem next to them */
    api.fail = function (r, hadData, retry) {
      var msg = h('div', { cls: 'msg error', role: 'alert', text: 'We could not refresh your wallet. ' });
      if (retry) msg.appendChild(h('button', { cls: 'btn secondary small', type: 'button', text: 'Try again', onclick: retry }));
      var old = body.querySelector('.msg');
      if (old) old.remove();
      if (!hadData) body.textContent = '';
      body.appendChild(msg);
    };
    api.clearFail = function () { var old = body.querySelector('.msg'); if (old) old.remove(); };
    return api;
  }

  // ------------------------------------------------------------------ forms
  function payCard(page) {
    var handle = textInput('pay-handle', { placeholder: 'e.g. bob', autocapitalize: 'none' });
    var amount = textInput('pay-amount', { inputmode: 'decimal', placeholder: '15.00', 'aria-describedby': 'pay-amount-hint' });
    var note = textInput('pay-note', { placeholder: 'What is it for? (optional)' });
    var visibility = visibilitySelect('pay-visibility');
    var box = h('div', { 'aria-live': 'polite' });
    var btn = h('button', { cls: 'btn', type: 'submit', tid: 'pay-submit', text: 'Send money' });
    var form = h('form', { novalidate: true }, [
      h('div', { cls: 'row two' }, [field('pay-handle', 'Pay to (handle)', handle), field('pay-amount', 'Amount (' + S.cur + ')', amount, amountHint())]),
      field('pay-note', 'Note', note),
      field('pay-visibility', 'Who can see it', visibility),
      box, h('div', { cls: 'actions' }, [btn])
    ]);
    wireSubmit({
      prefix: 'pay', form: form, box: box, button: btn, path: '/payments',
      build: function () {
        var to = handleValue(handle.value);
        if (!to) return { error: 'Enter the handle of the person you are paying.' };
        var d = parseAmount(amount.value);
        if (d == null) return { error: amountError() };
        return { body: '{"to_handle":' + JSON.stringify(to) + ',"amount":' + d + ',"note":' + JSON.stringify(note.value) +
          ',"visibility":' + JSON.stringify(visibility.value) + '}' };
      },
      okText: function (r) { return 'Sent ' + fmt(r.data.amount) + ' to @' + r.data.to_handle + '.'; },
      onDone: function () { page.reload(); }
    });
    return h('section', { cls: 'card', 'aria-labelledby': 'pay-title' }, [
      h('header', {}, [h('h2', { id: 'pay-title', text: 'Send money' }), h('p', { cls: 'sub', text: 'Money moves right away.' })]), form]);
  }

  function requestCard(page) {
    var handle = textInput('request-handle', { placeholder: 'e.g. ada', autocapitalize: 'none' });
    var amount = textInput('request-amount', { inputmode: 'decimal', placeholder: '12.00' });
    var note = textInput('request-note', { placeholder: 'What is it for? (optional)' });
    var box = h('div', { 'aria-live': 'polite' });
    var btn = h('button', { cls: 'btn secondary', type: 'submit', tid: 'request-submit', text: 'Request money' });
    var form = h('form', { novalidate: true }, [
      h('div', { cls: 'row two' }, [field('request-handle', 'Ask (handle)', handle), field('request-amount', 'Amount (' + S.cur + ')', amount, amountHint())]),
      field('request-note', 'Note', note), box, h('div', { cls: 'actions' }, [btn])
    ]);
    wireSubmit({
      prefix: 'request', form: form, box: box, button: btn, path: '/requests',
      build: function () {
        var from = handleValue(handle.value);
        if (!from) return { error: 'Enter the handle of the person you are asking.' };
        var d = parseAmount(amount.value);
        if (d == null) return { error: amountError() };
        return { body: '{"payer_handle":' + JSON.stringify(from) + ',"amount":' + d + ',"note":' + JSON.stringify(note.value) + '}' };
      },
      okText: function (r) { return 'Asked @' + r.data.payer_handle + ' for ' + fmt(r.data.amount) + '.'; },
      onDone: function () { page.reload(); }
    });
    return h('section', { cls: 'card', 'aria-labelledby': 'request-title' }, [
      h('header', {}, [h('h2', { id: 'request-title', text: 'Request money' }), h('p', { cls: 'sub', text: 'They choose whether to pay.' })]), form]);
  }

  function authorizeCard(page) {
    var handle = textInput('authorize-handle', { placeholder: 'e.g. bob', autocapitalize: 'none' });
    var amount = textInput('authorize-amount', { inputmode: 'decimal', placeholder: '20.00' });
    var note = textInput('authorize-note', { placeholder: 'What is it for? (optional)' });
    var visibility = visibilitySelect('authorize-visibility');
    var box = h('div', { 'aria-live': 'polite' });
    var btn = h('button', { cls: 'btn secondary', type: 'submit', tid: 'authorize-submit', text: 'Place a hold' });
    var form = h('form', { novalidate: true }, [
      h('div', { cls: 'row two' }, [field('authorize-handle', 'Hold for (handle)', handle), field('authorize-amount', 'Amount (' + S.cur + ')', amount, amountHint())]),
      field('authorize-note', 'Note', note), field('authorize-visibility', 'Who can see the payment when it is collected', visibility),
      box, h('div', { cls: 'actions' }, [btn])
    ]);
    wireSubmit({
      prefix: 'authorize', form: form, box: box, button: btn, path: '/authorizations',
      build: function () {
        var to = handleValue(handle.value);
        if (!to) return { error: 'Enter the handle of the person who may collect the money.' };
        var d = parseAmount(amount.value);
        if (d == null) return { error: amountError() };
        return { body: '{"to_handle":' + JSON.stringify(to) + ',"amount":' + d + ',"note":' + JSON.stringify(note.value) +
          ',"visibility":' + JSON.stringify(visibility.value) + '}' };
      },
      okText: function (r) { return fmt(r.data.amount) + ' is now on hold for @' + r.data.to_handle + '.'; },
      onDone: function () { page.reload(); }
    });
    return h('section', { cls: 'card', 'aria-labelledby': 'authorize-title' }, [
      h('header', {}, [h('h2', { id: 'authorize-title', text: 'Reserve money' }),
        h('p', { cls: 'sub', text: 'A hold sets money aside for someone to collect later. It stays yours until they collect it.' })]), form]);
  }

  // ------------------------------------------------------------------- feed
  function feedItem(p) {
    var mine = S.user ? S.user.handle : '';
    var dir = p.from_handle === mine ? 'sent' : (p.to_handle === mine ? 'received' : 'other');
    var id = p.payment_id;
    var label = dir === 'sent' ? 'Sent' : (dir === 'received' ? 'Received' : 'Public payment');
    return h('li', { cls: 'item ' + dir, tid: 'activity-item-' + id, 'data-visibility': p.visibility }, [
      h('div', { cls: 'main' }, [
        h('div', {}, [h('span', { cls: 'badge ' + dir, text: label }), ' ',
          h('span', { cls: 'parties', tid: 'activity-parties-' + id, text: p.from_handle + ' → ' + p.to_handle })]),
        h('p', { cls: 'note', tid: 'activity-note-' + id, text: p.note })
      ]),
      h('p', { cls: 'amount', tid: 'activity-amount-' + id, text: fmt(p.amount) }),
      h('div', { cls: 'meta' }, [
        p.created_at ? h('span', { text: when(p.created_at) }) : null,
        h('span', { cls: 'badge ' + p.visibility, text: p.visibility === 'private' ? 'Private' : 'Public' }),
        p.authorization_id ? h('span', { text: 'Collected from a hold' }) : null,
        p.request_id ? h('span', { text: 'Paid a request' }) : null,
        p.settlement_id ? h('span', { text: 'Settlement' }) : null
      ])
    ]);
  }

  function feedCard(retry) {
    var body = h('div', {}, [loadingState('Loading activity…')]);
    var api = { el: h('section', { cls: 'card span-2', 'aria-labelledby': 'feed-title' }, [
      h('header', {}, [h('h2', { id: 'feed-title', text: 'Activity' }), h('p', { cls: 'sub', text: 'Newest first. Private payments are only visible to the two people involved.' })]), body]) };
    api.update = function (items) {
      body.textContent = '';
      if (!items.length) {
        body.appendChild(emptyState('empty-activity', 'Nothing here yet', 'Payments you can see will appear here.'));
        return;
      }
      var ul = h('ul', { cls: 'list', tid: 'activity-list' });
      items.forEach(function (p) { ul.appendChild(feedItem(p)); });
      body.appendChild(ul);
    };
    api.fail = function () { body.textContent = ''; body.appendChild(failState(retry, 'We could not load your activity.')); };
    return api;
  }

  // ------------------------------------------------------------- page: home
  function homePage() {
    var m = shell('Your wallet', 'Available funds are what you can spend right now.');
    var page = { built: false };
    var wallet = walletCard(function () { page.reload(); });
    var feed, panels = [];
    // the wallet panel exists from the start so that the page-load read takes part in the same ordering as every refresh
    var walletPanel = new Panel('me', loadMe, function (res) { setMe(res.me); wallet.clearFail(); wallet.update(res.me); },
      function (r, had) { wallet.fail(r, had, function () { page.reload(); }); });
    m.appendChild(wallet.el);

    function build() {
      page.built = true;
      feed = feedCard(function () { page.reload(); });
      m.textContent = '';
      m.appendChild(pageTitle('Your wallet', 'Available funds are what you can spend right now.'));
      m.appendChild(h('div', { cls: 'grid two' }, [
        h('div', { cls: 'span-2' }, [wallet.el]),
        payCard(page), requestCard(page), authorizeCard(page), feed.el
      ]));
      panels = [walletPanel, new Panel('activity', function () { return loadAll('/activity', 'payments'); },
        function (res) { feed.update(res.items); }, function () { feed.fail(); })];
    }
    function start() {
      var id = ++refreshSeq;
      return walletPanel.fetch().then(function (res) {
        walletPanel.apply(id, res);  // skipped when a later refresh has already been shown
        if (!page.built) build();
        return refreshPanels([panels[1]]);
      });
    }
    page.reload = function () {
      if (!page.built) return start();
      return refreshPanels(panels);
    };
    start();
  }

  var expiryTimer = null;
  /* Refresh once when the nearest open hold expires, so its release shows without a manual refresh. */
  function scheduleRefresh(auths, page) {
    clearTimeout(expiryTimer);
    var next = null;
    (auths || []).forEach(function (a) {
      if (a.status !== 'open') return;
      var t = Date.parse(a.expires_at);
      if (!isNaN(t) && (next == null || t < next)) next = t;
    });
    if (next == null) return;
    var wait = next - Date.now() + 300;
    if (wait < 0) wait = 300;
    if (wait > 3600000) return;
    expiryTimer = setTimeout(function () { page.reload(); }, wait);
  }

  // ---------------------------------------------------------- page: requests
  function statusLabel(s) { return { pending: 'Pending', paid: 'Paid', declined: 'Declined', cancelled: 'Cancelled' }[s] || s; }

  function requestsPage() {
    var m = shell('Requests', 'Money you have been asked for, and money you have asked for.');
    var box = h('div', { 'aria-live': 'polite' });
    var incoming = h('ul', { cls: 'list', tid: 'incoming-list' });
    var outgoing = h('ul', { cls: 'list', tid: 'outgoing-list' });
    var inHint = h('div', {}, [loadingState()]);
    var outHint = h('div', {}, [loadingState()]);
    var overall = h('div');
    var payKeys = {}, privChoice = {};
    var counts = { inc: null, out: null };

    function item(r, incomingSide) {
      var id = r.request_id;
      var other = incomingSide ? r.requester_handle : r.payer_handle;
      var controls = h('div', { cls: 'controls' });
      if (r.status === 'pending' && incomingSide) {
        var priv = h('input', { type: 'checkbox', id: 'priv-' + id });
        priv.checked = !!privChoice[id];
        priv.addEventListener('change', function () { privChoice[id] = priv.checked; });
        controls.appendChild(h('button', { cls: 'btn small', type: 'button', tid: 'request-pay-' + id, text: 'Pay ' + fmt(r.amount),
          onclick: function () { act(this, 'pay', r, priv.checked); } }));
        controls.appendChild(h('button', { cls: 'btn danger small', type: 'button', tid: 'request-decline-' + id, text: 'Decline',
          onclick: function () { act(this, 'decline', r); } }));
        controls.appendChild(h('label', { cls: 'check' }, [priv, 'Keep this payment private']));
      }
      if (r.status === 'pending' && !incomingSide) {
        controls.appendChild(h('button', { cls: 'btn danger small', type: 'button', tid: 'request-cancel-' + id, text: 'Cancel request',
          onclick: function () { act(this, 'cancel', r); } }));
      }
      return h('li', { cls: 'item ' + (incomingSide ? 'sent' : 'received'), tid: 'request-item-' + id, 'data-status': r.status }, [
        h('div', { cls: 'main' }, [
          h('div', {}, [h('span', { cls: 'badge ' + r.status, text: statusLabel(r.status) }), ' ',
            h('span', { cls: 'parties', text: incomingSide ? '@' + other + ' asks you' : 'You ask @' + other })]),
          r.note ? h('p', { cls: 'note', text: r.note }) : null
        ]),
        h('p', { cls: 'amount', tid: 'request-amount-' + id, text: fmt(r.amount) }),
        h('div', { cls: 'meta' }, r.created_at ? [h('span', { text: when(r.created_at) })] : []),
        controls
      ]);
    }
    function overallState() {
      overall.textContent = '';
      if (counts.inc === 0 && counts.out === 0) {
        overall.appendChild(emptyState('empty-requests', 'No requests yet', 'Requests you send or receive will appear here.'));
      }
    }
    function listPanel(path, ul, hint, side, label, empty) {
      return new Panel(side ? 'requests_in' : 'requests_out', function () { return loadAll(path, 'requests'); }, function (res) {
        ul.textContent = '';
        res.items.forEach(function (r) { ul.appendChild(item(r, side)); });
        hint.textContent = '';
        if (!res.items.length) hint.appendChild(h('p', { cls: 'state', text: empty }));
        counts[side ? 'inc' : 'out'] = res.items.length;
        overallState();
      }, function (r) {
        hint.textContent = '';
        hint.appendChild(failState(reload, failText(r, label)));
        counts[side ? 'inc' : 'out'] = null;
        overallState();
      });
    }
    var panels = [
      listPanel('/requests?direction=incoming', incoming, inHint, true, 'incoming requests', 'No incoming requests.'),
      listPanel('/requests?direction=outgoing', outgoing, outHint, false, 'outgoing requests', 'No outgoing requests.')
    ];
    function reload() { return refreshPanels(panels); }
    function act(btn, what, r, priv) {
      var id = r.request_id;
      var path = '/requests/' + encodeURIComponent(id) + '/' + what;
      var o = {};
      if (what === 'pay') {
        var body = priv ? '{"visibility":"private"}' : '{}';
        var st = payKeys[id];
        if (!st || st.body !== body) { st = payKeys[id] = { body: body, key: newKey() }; }
        o = { body: body, key: st.key };
      }
      btn.disabled = true;
      call('POST', path, o).then(function (res) {
        btn.disabled = false;
        var k = kind(res);
        if (k === 'ok') clearMsg(box);
        else if (k === 'refused') setMsg(box, 'error', 'request-error', friendly(res));
        else setMsg(box, 'uncertain', 'request-uncertain', 'We could not confirm that. Refresh the list to see the current state, or try again.');
        return reload();
      });
    }

    m.appendChild(box);
    m.appendChild(overall);
    m.appendChild(h('div', { cls: 'grid two' }, [
      h('section', { cls: 'card', 'aria-labelledby': 'in-title' }, [h('header', {}, [h('h2', { id: 'in-title', text: 'Incoming' }), h('p', { cls: 'sub', text: 'People asking you for money.' })]), incoming, inHint]),
      h('section', { cls: 'card', 'aria-labelledby': 'out-title' }, [h('header', {}, [h('h2', { id: 'out-title', text: 'Outgoing' }), h('p', { cls: 'sub', text: 'Money you have asked for.' })]), outgoing, outHint])
    ]));
    bootMe().then(reload);
  }

  // ------------------------------------------------------------- page: split
  function splitPage() {
    var m = shell('Split a bill', 'Share an amount you already paid. Everyone else gets a request for their share.');
    m.appendChild(loadingState());
    bootMe().then(function (r) {
      var amount = textInput('split-amount', { inputmode: 'decimal', placeholder: '30.00' });
      var handles = textInput('split-handles', { placeholder: 'ada, bob, cy', autocapitalize: 'none' });
      var note = textInput('split-note', { placeholder: 'What is it for? (optional)' });
      var box = h('div', { 'aria-live': 'polite' });
      var previewBox = h('div', { 'aria-live': 'polite' });
      var btn = h('button', { cls: 'btn', type: 'submit', tid: 'split-submit', text: 'Split and send requests' });
      var form = h('form', { novalidate: true }, [
        field('split-amount', 'Total amount (' + S.cur + ')', amount, amountHint()),
        field('split-handles', 'Who is splitting it (handles, comma separated, in order)', handles,
          'Include yourself if you are sharing the cost. The first people listed get any extra unit.'),
        field('split-note', 'Note', note), previewBox, box, h('div', { cls: 'actions' }, [btn])
      ]);
      function participants() {
        return handles.value.split(',').map(handleValue).filter(function (x) { return x; });
      }
      function updatePreview() {
        previewBox.textContent = '';
        var d = parseAmount(amount.value);
        var hs = participants();
        if (d == null || !hs.length || new Set(hs).size !== hs.length) return;
        var total = BigInt(d), n = BigInt(hs.length);
        var base = total / n, rem = total % n;
        var pv = h('div', { cls: 'preview', tid: 'split-preview', role: 'group', 'aria-label': 'Preview of the shares' }, [
          h('p', { cls: 'sub', text: 'Preview of the shares' })]);
        hs.forEach(function (hd, i) {
          var share = base + (BigInt(i) < rem ? 1n : 0n);
          pv.appendChild(h('div', { cls: 'line' }, [h('span', { text: '@' + hd }),
            h('strong', { tid: 'split-share-' + hd, text: fmt(share.toString()) })]));
        });
        previewBox.appendChild(pv);
      }
      amount.addEventListener('input', updatePreview);
      handles.addEventListener('input', updatePreview);
      wireSubmit({
        prefix: 'split', form: form, box: box, button: btn, path: '/splits',
        build: function () {
          var d = parseAmount(amount.value);
          if (d == null) return { error: amountError() };
          return { body: '{"amount":' + d + ',"participant_handles":' + JSON.stringify(participants()) + ',"note":' + JSON.stringify(note.value) + '}' };
        },
        okText: function (resp) {
          var n = isObj(resp.data) && Array.isArray(resp.data.requests) ? resp.data.requests.length : 0;
          return 'Split saved. ' + n + (n === 1 ? ' request was' : ' requests were') + ' sent.';
        },
        onDone: function () {}
      });
      m.textContent = '';
      m.appendChild(pageTitle('Split a bill', 'Share an amount you already paid. Everyone else gets a request for their share.'));
      m.appendChild(h('section', { cls: 'card narrow', 'aria-label': 'Split form' }, [form]));
      updatePreview();
    });
  }

  // ------------------------------------------------------ page: authorizations
  var AUTH_LABEL = { open: 'On hold', captured: 'Collected', voided: 'Released', expired: 'Expired' };

  function authorizationsPage() {
    var m = shell('Authorizations', 'Holds set money aside for someone to collect later.');
    var page = {};
    var capKeys = {};
    var box = h('div', { 'aria-live': 'polite' });
    var listBox = h('div', {}, [loadingState('Loading authorizations…')]);
    var wallet = walletCard(null);
    var panels = [];

    function item(a) {
      var id = a.authorization_id;
      var mine = S.me ? S.me.user_id : '';
      var incomingSide = mine ? a.to_user_id === mine : a.to_handle === (S.user ? S.user.handle : '');
      var controls = h('div', { cls: 'controls' });
      if (a.status === 'open' && incomingSide) {
        var st = capKeys[id] || (capKeys[id] = { key: null, sig: null, dirty: true, value: null, keep: false });
        var cap = textInput('authorization-capture-amount-' + id, { inputmode: 'decimal', 'aria-label': 'Amount to collect' });
        cap.id = 'cap-' + id;
        // keep what the person is typing across list refreshes; otherwise offer what is still held
        cap.value = st.value != null ? st.value : plain(a.remaining_amount);
        var keep = h('input', { type: 'checkbox', id: 'keep-' + id });
        keep.checked = st.keep;
        var btn = h('button', { cls: 'btn small', type: 'button', tid: 'authorization-capture-' + id, text: 'Collect',
          onclick: function () { capture(btn, a, cap, keep.checked, st); } });
        cap.addEventListener('input', function () { st.dirty = true; st.value = cap.value; });
        keep.addEventListener('change', function () { st.dirty = true; st.keep = keep.checked; });
        controls.appendChild(h('div', { cls: 'field' }, [h('label', { 'for': 'cap-' + id, text: 'Amount to collect (' + S.cur + ')' }), cap]));
        controls.appendChild(btn);
        controls.appendChild(h('label', { cls: 'check' }, [keep, 'Keep the rest on hold']));
      }
      if (a.status === 'open' && !incomingSide) {
        controls.appendChild(h('button', { cls: 'btn danger small', type: 'button', tid: 'authorization-void-' + id, text: 'Release hold',
          onclick: function () { voidIt(this, a); } }));
      }
      var partial = a.status === 'open' && a.captured_amount > 0 ? h('span', { text: fmt(a.captured_amount) + ' collected so far, ' + fmt(a.remaining_amount) + ' still held' }) : null;
      return h('li', { cls: 'item ' + (incomingSide ? 'received' : 'sent'), tid: 'authorization-item-' + id, 'data-status': a.status }, [
        h('div', { cls: 'main' }, [
          h('div', {}, [h('span', { cls: 'badge ' + a.status, text: AUTH_LABEL[a.status] || a.status }), ' ',
            h('span', { cls: 'parties', text: incomingSide ? '@' + a.from_handle + ' holds money for you' : 'You hold money for @' + a.to_handle })]),
          a.note ? h('p', { cls: 'note', text: a.note }) : null
        ]),
        h('p', { cls: 'amount', tid: 'authorization-amount-' + id, text: fmt(a.amount) }),
        h('div', { cls: 'meta' }, [
          a.status === 'captured' ? h('span', {}, ['Collected ', h('strong', { tid: 'authorization-captured-' + id, text: fmt(a.captured_amount) })]) : null,
          partial,
          h('span', {}, ['Expires ', h('span', { tid: 'authorization-expires-' + id, text: a.expires_at })]),
          h('span', { cls: 'badge ' + a.visibility, text: a.visibility === 'private' ? 'Private' : 'Public' })
        ]),
        controls
      ]);
    }

    function capture(btn, a, cap, keepHeld, st) {
      var d = parseAmount(cap.value);
      if (d == null) { setMsg(box, 'error', 'authorization-error', amountError()); return; }
      var body = '{"amount":' + d + (keepHeld ? ',"final":false' : '') + '}';
      if (st.dirty || !st.key || st.sig !== body) { st.key = newKey(); st.sig = body; st.dirty = false; }
      btn.disabled = true;
      call('POST', '/authorizations/' + encodeURIComponent(a.authorization_id) + '/capture', { body: body, key: st.key }).then(function (r) {
        btn.disabled = false;
        var k = kind(r);
        if (k === 'ok') { clearMsg(box); st.value = null; st.keep = false; st.key = null; }
        else if (k === 'refused') setMsg(box, 'error', 'authorization-error', friendly(r));
        else setMsg(box, 'uncertain', 'authorization-uncertain', 'We could not confirm that. Press Collect again to retry safely; it will be applied only once.');
        if (k !== 'uncertain') page.reload();
      });
    }
    function voidIt(btn, a) {
      btn.disabled = true;
      call('POST', '/authorizations/' + encodeURIComponent(a.authorization_id) + '/void', {}).then(function (r) {
        btn.disabled = false;
        var k = kind(r);
        if (k === 'ok') clearMsg(box);
        else if (k === 'refused') setMsg(box, 'error', 'authorization-error', friendly(r));
        else setMsg(box, 'uncertain', 'authorization-uncertain', 'We could not confirm that. Refresh to see the current state.');
        page.reload();
      });
    }

    panels = [
      new Panel('me', loadMe, function (res) { setMe(res.me); wallet.clearFail(); wallet.update(res.me); },
        function (r, had) { wallet.fail(r, had, function () { page.reload(); }); }),
      new Panel('authorizations', function () { return loadAll('/authorizations', 'authorizations'); }, function (res) {
        listBox.textContent = '';
        if (!res.items.length) {
          listBox.appendChild(emptyState('empty-authorizations', 'No authorizations yet', 'Holds you place or receive will appear here.'));
        } else {
          var ul = h('ul', { cls: 'list', tid: 'authorization-list' });
          res.items.forEach(function (a) { ul.appendChild(item(a)); });
          listBox.appendChild(ul);
        }
        scheduleRefresh(res.items, page);
      }, function (r) {
        listBox.textContent = '';
        listBox.appendChild(failState(page.reload, failText(r, 'authorizations')));
      })
    ];
    page.reload = function () { return refreshPanels(panels); };

    m.appendChild(h('div', { cls: 'grid two' }, [
      h('div', {}, [wallet.el]), authorizeCard(page),
      h('section', { cls: 'card span-2', 'aria-labelledby': 'auth-list-title' }, [
        h('header', {}, [h('h2', { id: 'auth-list-title', text: 'Your holds' }), h('p', { cls: 'sub', text: 'Newest first.' })]), box, listBox])
    ]));
    // currency and decimals first (labels and the amount rule depend on them), then every panel on its own
    bootMe().then(function () { return page.reload(); });
  }

  // ----------------------------------------------------------- page: auth
  function authPage(mode) {
    var signup = mode === 'signup';
    var m = shell(signup ? 'Create your account' : 'Welcome back', signup ? 'Join Pocketful to send, request and split money.' : 'Sign in to your wallet.');
    var box = h('div', { 'aria-live': 'polite' });
    var email = h('input', { id: mode + '-email', tid: mode + '-email', type: 'email', autocomplete: signup ? 'email' : 'username', spellcheck: 'false' });
    var pw = h('input', { id: mode + '-password', tid: mode + '-password', type: 'password', autocomplete: signup ? 'new-password' : 'current-password' });
    var name = signup ? h('input', { id: 'signup-display-name', tid: 'signup-display-name', type: 'text', autocomplete: 'name' }) : null;
    var btn = h('button', { cls: 'btn', type: 'submit', tid: mode + '-submit', text: signup ? 'Create account' : 'Sign in' });
    var form = h('form', { novalidate: true }, [
      signup ? field('signup-display-name', 'Your name', name) : null,
      field(mode + '-email', 'Email', email),
      field(mode + '-password', 'Password', pw, signup ? 'At least 8 characters.' : null),
      box, h('div', { cls: 'actions' }, [btn])
    ]);
    var busy = false;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (busy) return;
      var path = signup ? '/auth/signup' : '/auth/login';
      var payload = signup ? { email: email.value, password: pw.value, display_name: name.value } : { email: email.value, password: pw.value };
      busy = true; btn.disabled = true;
      call('POST', path, { body: JSON.stringify(payload), token: false }).then(function (r) {
        var k = kind(r);
        if (k === 'ok' && isObj(r.data) && typeof r.data.token === 'string') {
          return signIn(r.data.token).then(function (ok) {
            if (ok) { location.assign('/'); return; }
            busy = false; btn.disabled = false;
            setMsg(box, 'error', 'auth-error', 'Signed in, but we could not load your wallet. Please try again.');
          });
        }
        busy = false; btn.disabled = false;
        if (k === 'refused') setMsg(box, 'error', 'auth-error', friendly(r));
        else setMsg(box, 'error', 'auth-error', 'We could not reach the service. Please try again.');
      });
    });
    var other = signup ? h('p', { cls: 'sub' }, ['Already have an account? ', h('a', { href: '/login', text: 'Sign in' })])
      : h('p', { cls: 'sub' }, ['New here? ', h('a', { href: '/signup', text: 'Create an account' })]);
    m.appendChild(h('section', { cls: 'card narrow', 'aria-label': signup ? 'Sign up' : 'Sign in' }, [form, other]));
    if (S.token && !S.user) bootMe();
  }

  // ------------------------------------------------------------------ start
  function start() {
    var p = location.pathname;
    if (p === '/login') return authPage('login');
    if (p === '/signup') return authPage('signup');
    if (!S.token) { location.replace('/login'); return; }
    if (p === '/requests') return requestsPage();
    if (p === '/split') return splitPage();
    if (p === '/authorizations') return authorizationsPage();
    return homePage();
  }
  function boot() { try { start(); } catch (e) { showFatal(); } }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
