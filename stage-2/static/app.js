/* Pocketful web client. Plain JavaScript, no external dependencies. */
(function () {
  'use strict';

  var route = document.body.getAttribute('data-route');
  var appRoot = document.getElementById('app');
  var TOKEN_KEY = 'pocketful.token';
  var ctx = { me: null };

  /* ---------- small helpers ---------- */

  function el(tag, props) {
    var n = document.createElement(tag);
    var p = props || {};
    Object.keys(p).forEach(function (k) {
      var v = p[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') n.className = v;
      else if (k === 'testid') n.setAttribute('data-testid', v);
      else if (k === 'text') n.textContent = v;
      else if (k.indexOf('on') === 0) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) append(n, arguments[i]);
    return n;
  }
  function append(n, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { append(n, x); }); return; }
    n.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function uuid() {
    if (window.crypto && crypto.randomUUID) { try { return crypto.randomUUID(); } catch (e) { /* insecure context */ } }
    var b = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(b);
    else for (var i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
    return Array.prototype.map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
  }

  function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }
  function setToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { /* ignore */ } }
  function dropToken() { try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } }

  /* ---------- money ---------- */

  function fmt(minor) {
    var mu = ctx.me.minor_units, cur = ctx.me.currency, s = String(minor);
    if (mu === 0) return s + ' ' + cur;
    while (s.length < mu + 1) s = '0' + s;
    return s.slice(0, s.length - mu) + '.' + s.slice(s.length - mu) + ' ' + cur;
  }
  function plainDecimal(minor) { return fmt(minor).replace(/ \S+$/, ''); }

  /* "15", "15.5", "15.50" -> minor units, exactly; null when not a valid amount. */
  function parseDecimal(text) {
    var mu = ctx.me.minor_units;
    var t = String(text).trim();
    var re = mu === 0 ? /^[0-9]+$/ : new RegExp('^[0-9]+(\\.[0-9]{1,' + mu + '})?$');
    if (!re.test(t)) return null;
    var parts = t.split('.');
    var frac = parts[1] || '';
    while (frac.length < mu) frac += '0';
    var digits = (parts[0] + frac).replace(/^0+(?=\d)/, '');
    return Number(digits);
  }
  function amountHint() {
    var mu = ctx.me.minor_units;
    return mu === 0 ? 'Whole ' + ctx.me.currency + ' only, e.g. 15'
      : 'Up to ' + mu + ' decimal places, e.g. ' + (mu === 2 ? '15.00' : '15.' + new Array(mu + 1).join('0'));
  }
  function badAmountMessage() {
    return 'Enter a valid amount. ' + amountHint() + '.';
  }

  function equalSplit(amount, n) {
    var base = Math.floor(amount / n), rem = amount - base * n, out = [];
    for (var i = 0; i < n; i++) out.push(base + (i < rem ? 1 : 0));
    return out;
  }

  /* ---------- time ---------- */

  function humanTime(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var now = new Date();
    var same = d.toDateString() === now.toDateString();
    var opts = same ? { hour: '2-digit', minute: '2-digit' }
      : { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' };
    return (same ? 'Today, ' : '') + d.toLocaleString(undefined, opts);
  }
  function relativeExpiry(iso) {
    var ms = new Date(iso).getTime() - Date.now();
    if (isNaN(ms)) return '';
    var past = ms <= 0, s = Math.abs(Math.round(ms / 1000));
    var txt = s < 90 ? s + ' sec' : s < 5400 ? Math.round(s / 60) + ' min'
      : s < 172800 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' days';
    return past ? 'ended ' + txt + ' ago' : 'in ' + txt;
  }

  /* ---------- api ---------- */

  function NetError(msg) { this.message = msg; }

  function api(method, path, body, opts) {
    opts = opts || {};
    var headers = { 'Accept': 'application/json' };
    var tok = getToken();
    if (tok) headers['Authorization'] = 'Bearer ' + tok;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (opts.key) headers['Idempotency-Key'] = opts.key;
    var ctl = window.AbortController ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 20000) : null;
    return fetch(path, {
      method: method, headers: headers, cache: 'no-store',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl ? ctl.signal : undefined
    }).then(function (res) {
      return res.text().then(function (txt) {
        if (timer) clearTimeout(timer);
        var data = null;
        try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
        if (res.status === 401 && !opts.noRedirect && route !== 'login' && route !== 'signup') {
          dropToken();
          location.replace('/login');
        }
        return { ok: res.status >= 200 && res.status < 300, status: res.status, data: data };
      });
    }, function (e) {
      if (timer) clearTimeout(timer);
      throw new NetError(String(e && e.message || e));
    });
  }

  var MESSAGES = {
    insufficient_funds: "Not enough available funds for that. Money on hold can't be spent.",
    not_found: "We couldn't find that person or item. Check the handle and try again.",
    self_payment: "You can't send money to yourself.",
    self_request: "You can't request money from yourself.",
    request_not_pending: 'That request has already been handled, so nothing was changed.',
    authorization_not_open: 'That authorization is no longer open.',
    authorization_expired: 'That authorization has expired and its hold was released.',
    capture_exceeds_authorization: "That's more than what is left on the authorization.",
    forbidden: "You aren't allowed to do that.",
    email_taken: 'That email already has an account. Try logging in instead.',
    handle_taken: 'A handle derived from that email is already taken. Try a different email.',
    malformed_request: 'That request could not be understood. Please check the form.'
  };
  function explain(r) {
    var e = r.data && r.data.error, code = e && e.code;
    if (code === 'validation_failed') return 'Please check the details: ' + (e.message || 'something is invalid') + '.';
    if (code && MESSAGES[code]) return MESSAGES[code];
    if (e && e.message) return e.message;
    return 'Something went wrong (status ' + r.status + '). Please try again.';
  }
  var LOST = "We didn't get a reply, so we can't tell whether this went through. " +
    'Nothing has been repeated: submit the form again unchanged to safely retry, or refresh to check.';

  /* One retry identity per submission: the same fields keep the same idempotency key. */
  function Identity() {
    var cur = null;
    return {
      key: function (body) {
        var j = JSON.stringify(body);
        if (!cur || cur.json !== j) cur = { json: j, key: uuid() };
        return cur.key;
      }
    };
  }

  /* ---------- feedback slots ---------- */

  function show(slot, kind, testid, text) {
    clear(slot);
    slot.appendChild(el('div', { class: 'notice ' + kind, testid: testid, role: kind === 'error' ? 'alert' : 'status', text: text }));
  }

  /* ---------- layout ---------- */

  var NAV = [
    ['/', 'Wallet', 'home'], ['/requests', 'Requests', 'requests'],
    ['/split', 'Split a bill', 'split'], ['/authorizations', 'Authorizations', 'authorizations']
  ];
  var headerWho = el('div', { class: 'who' });

  function buildFrame(title, sub) {
    var nav = el('ul', { class: 'nav' });
    if (getToken()) {
      NAV.forEach(function (n) {
        nav.appendChild(el('li', null, el('a', { href: n[0], 'aria-current': n[2] === route ? 'page' : null, text: n[1] })));
      });
    } else {
      nav.appendChild(el('li', null, el('a', { href: '/login', 'aria-current': route === 'login' ? 'page' : null, text: 'Log in' })));
      nav.appendChild(el('li', null, el('a', { href: '/signup', 'aria-current': route === 'signup' ? 'page' : null, text: 'Sign up' })));
    }
    var top = el('header', { class: 'topbar' }, el('div', { class: 'topbar-inner' },
      el('a', { class: 'brand', href: getToken() ? '/' : '/login' }, el('span', { class: 'brand-mark', 'aria-hidden': 'true' }), 'Pocketful'),
      el('nav', { 'aria-label': 'Main' }, nav), headerWho));
    var main = el('main', { id: 'main' }, el('div', null, el('h1', { class: 'page-title', text: title }), sub ? el('p', { class: 'page-sub', text: sub }) : null));
    clear(appRoot);
    appRoot.appendChild(top);
    appRoot.appendChild(main);
    return main;
  }

  function renderWho() {
    clear(headerWho);
    if (!ctx.me) return;
    var me = ctx.me;
    headerWho.appendChild(el('span', { class: 'avatar', 'aria-hidden': 'true', text: (me.display_name || '?').trim().charAt(0).toUpperCase() || '?' }));
    headerWho.appendChild(el('span', { class: 'who-name', testid: 'current-user', text: me.display_name }));
    headerWho.appendChild(el('span', { class: 'who-handle' }, '@', el('span', { testid: 'current-handle', text: me.handle })));
    headerWho.appendChild(el('button', { class: 'secondary small', type: 'button', testid: 'logout-button', text: 'Log out', onclick: logout }));
  }
  function logout() { dropToken(); location.assign('/login'); }

  /* ---------- wallet card ---------- */

  var walletHost = el('section', { class: 'wallet', 'aria-label': 'Wallet' });
  var walletFoot = el('div', { class: 'wallet-foot' });

  function renderWallet() {
    var me = ctx.me;
    clear(walletHost);
    walletHost.appendChild(el('p', { class: 'eyebrow', text: 'Available to spend' }));
    if (!me) {
      walletHost.appendChild(el('div', null, el('span', { class: 'skeleton', 'aria-label': 'Loading balance' })));
      return;
    }
    walletHost.appendChild(el('div', { class: 'available', testid: 'wallet-available', 'data-amount': String(me.available), text: fmt(me.available) }));
    var dl = el('dl', { class: 'wallet-secondary' },
      el('div', null, el('dt', { text: 'Total' }), el('dd', { testid: 'wallet-balance', 'data-amount': String(me.total), text: fmt(me.total) })));
    if (me.held > 0) {
      dl.appendChild(el('div', { class: 'held-tag' }, el('dt', { text: 'On hold' }),
        el('dd', { testid: 'wallet-held', 'data-amount': String(me.held), text: fmt(me.held) })));
    }
    walletHost.appendChild(dl);
    if (walletFoot.childNodes.length) walletHost.appendChild(walletFoot);
  }

  function loadMe() {
    return api('GET', '/me').then(function (r) {
      if (r.ok) { ctx.me = r.data; }
      return r;
    });
  }
  function refreshMeOnly() {
    return loadMe().then(function () { renderWallet(); }, function () { /* keep the last numbers */ });
  }

  /* ---------- home: pay, request, feed ---------- */

  var feedSeq = 0;
  var feedHost = el('div', { class: 'stack' });
  var refreshState = { busy: false };
  var refreshNote = el('span', { class: 'hint', role: 'status' });
  var refreshBtn = null;

  function setRefreshBusy(b) {
    refreshState.busy = b;
    if (refreshBtn) {
      if (b) refreshBtn.setAttribute('aria-busy', 'true'); else refreshBtn.removeAttribute('aria-busy');
    }
    refreshNote.textContent = b ? 'Refreshing…' : '';
  }

  /* Latest refresh wins: only the most recently started refresh may render. */
  function refreshWallet() {
    var mine = ++feedSeq;
    setRefreshBusy(true);
    return Promise.all([api('GET', '/me'), api('GET', '/activity?limit=200')]).then(function (rs) {
      if (mine !== feedSeq) return;
      if (rs[0].ok) { ctx.me = rs[0].data; renderWallet(); renderWho(); }
      if (rs[1].ok) renderFeed(rs[1].data.payments);
      else renderFeedError();
      setRefreshBusy(false);
    }, function () {
      if (mine !== feedSeq) return;
      renderFeedError();
      setRefreshBusy(false);
    });
  }

  function renderFeedError() {
    if (feedHost.querySelector('[data-testid="activity-list"]')) return;
    clear(feedHost);
    feedHost.appendChild(el('div', { class: 'notice error', role: 'alert' }, 'We couldn’t load your activity. ',
      el('button', { class: 'secondary small', type: 'button', onclick: refreshWallet, text: 'Try again' })));
  }

  function renderFeed(payments) {
    clear(feedHost);
    if (!payments.length) {
      feedHost.appendChild(el('div', { class: 'empty', testid: 'empty-activity' },
        el('strong', { text: 'No activity yet' }),
        el('span', { text: 'Payments you send or receive, and public payments from others, will show up here.' })));
      return;
    }
    var me = ctx.me;
    var ul = el('ul', { class: 'list', testid: 'activity-list' });
    payments.forEach(function (p) {
      var sent = p.from_handle === me.handle, got = p.to_handle === me.handle;
      var dir = sent ? 'Sent' : got ? 'Received' : 'Between others';
      ul.appendChild(el('li', { class: 'item', testid: 'activity-item-' + p.payment_id, 'data-visibility': p.visibility },
        el('div', { class: 'item-top' },
          el('div', { class: 'item-main' },
            el('div', { class: 'chips' },
              el('span', { class: 'chip ' + (sent ? 'sent' : got ? 'received' : 'public'), text: dir }),
              el('span', { class: 'chip ' + p.visibility, text: p.visibility === 'private' ? 'Private' : 'Public' })),
            el('div', { class: 'parties', testid: 'activity-parties-' + p.payment_id, text: p.from_handle + ' → ' + p.to_handle }),
            el('div', { class: 'note', testid: 'activity-note-' + p.payment_id, text: p.note })),
          el('div', { class: 'item-side' },
            el('div', { class: 'amount-line' },
              sent ? el('span', { class: 'sign out', 'aria-label': 'money out', text: '−' }) : got ? el('span', { class: 'sign in', 'aria-label': 'money in', text: '+' }) : null,
              el('span', { class: 'amount', testid: 'activity-amount-' + p.payment_id, text: fmt(p.amount) })),
            el('time', { class: 'meta', datetime: p.created_at, title: p.created_at, text: humanTime(p.created_at) })))));
    });
    feedHost.appendChild(ul);
  }

  function amountField(id, label, testid, value) {
    return el('div', { class: 'field' },
      el('label', { for: id, text: label }),
      el('input', { id: id, testid: testid, type: 'text', inputmode: 'decimal', autocomplete: 'off', value: value || '', 'aria-describedby': id + '-hint' }),
      el('span', { class: 'hint', id: id + '-hint', text: amountHint() }));
  }
  function textField(id, label, testid, hint, extra) {
    var props = { id: id, testid: testid, type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false' };
    Object.keys(extra || {}).forEach(function (k) { props[k] = extra[k]; });
    return el('div', { class: 'field' }, el('label', { for: id, text: label }), el('input', props),
      hint ? el('span', { class: 'hint', text: hint }) : null);
  }
  function visibilityField(id, testid) {
    return el('div', { class: 'field' }, el('label', { for: id, text: 'Who can see this' }),
      el('select', { id: id, testid: testid },
        el('option', { value: 'public', text: 'Public – shows in the activity feed' }),
        el('option', { value: 'private', text: 'Private – only you and the recipient' })));
  }
  function val(testid) { return document.querySelector('[data-testid="' + testid + '"]').value; }
  function cleanHandle(s) { return String(s).trim().replace(/^@/, ''); }

  function payForm() {
    var slot = el('div', { class: 'slot' });
    var btn = el('button', { class: 'primary', type: 'submit', testid: 'pay-submit', text: 'Send money' });
    var ident = Identity();
    var busy = false;
    var form = el('form', { class: 'card', novalidate: true, 'aria-labelledby': 'pay-title' },
      el('div', { class: 'card-head' }, el('h2', { id: 'pay-title', text: 'Send money' })),
      textField('pay-handle', 'To (handle)', 'pay-handle', null, { placeholder: 'e.g. bob' }),
      amountField('pay-amount', 'Amount (' + ctx.me.currency + ')', 'pay-amount'),
      textField('pay-note', 'Note (optional)', 'pay-note', null, { maxlength: '200' }),
      visibilityField('pay-visibility', 'pay-visibility'),
      btn, slot);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (busy) return;
      var amount = parseDecimal(val('pay-amount'));
      if (amount === null) { show(slot, 'error', 'pay-error', badAmountMessage()); return; }
      var handle = cleanHandle(val('pay-handle'));
      if (!handle) { show(slot, 'error', 'pay-error', 'Enter the handle of the person you are paying.'); return; }
      var body = { to_handle: handle, amount: amount, note: val('pay-note'), visibility: val('pay-visibility') };
      var key = ident.key(body);
      busy = true; btn.setAttribute('aria-busy', 'true');
      show(slot, 'loading', null, 'Sending…');
      api('POST', '/payments', body, { key: key }).then(function (r) {
        if (r.ok) {
          show(slot, 'ok', 'pay-success', r.status === 200
            ? 'That payment was already sent – nothing was charged twice.'
            : 'Sent ' + fmt(r.data.amount) + ' to ' + r.data.to_handle + '.');
          return refreshWallet();
        }
        if (r.status >= 500 || r.status === 0) { show(slot, 'uncertain', 'pay-uncertain', LOST); return; }
        show(slot, 'error', 'pay-error', explain(r));
        return refreshWallet();
      }, function () {
        show(slot, 'uncertain', 'pay-uncertain', LOST);
      }).then(function () { busy = false; btn.removeAttribute('aria-busy'); });
    });
    return form;
  }

  function requestForm() {
    var slot = el('div', { class: 'slot' });
    var btn = el('button', { class: 'secondary', type: 'submit', testid: 'request-submit', text: 'Request money' });
    var ident = Identity();
    var busy = false;
    var form = el('form', { class: 'card', novalidate: true, 'aria-labelledby': 'request-title' },
      el('div', { class: 'card-head' }, el('h2', { id: 'request-title', text: 'Request money' })),
      textField('request-handle', 'From (handle)', 'request-handle', null, { placeholder: 'e.g. ada' }),
      amountField('request-amount', 'Amount (' + ctx.me.currency + ')', 'request-amount'),
      textField('request-note', 'Note (optional)', 'request-note', null, { maxlength: '200' }),
      btn, slot);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (busy) return;
      var amount = parseDecimal(val('request-amount'));
      if (amount === null) { show(slot, 'error', 'request-error', badAmountMessage()); return; }
      var handle = cleanHandle(val('request-handle'));
      if (!handle) { show(slot, 'error', 'request-error', 'Enter the handle of the person you are asking.'); return; }
      var body = { payer_handle: handle, amount: amount, note: val('request-note') };
      busy = true; btn.setAttribute('aria-busy', 'true');
      show(slot, 'loading', null, 'Sending request…');
      api('POST', '/requests', body, { key: ident.key(body) }).then(function (r) {
        if (r.ok) {
          show(slot, 'ok', 'request-success', 'Requested ' + fmt(r.data.amount) + ' from ' + r.data.payer_handle + '.');
          return refreshWallet();
        }
        if (r.status >= 500) { show(slot, 'uncertain', 'request-uncertain', LOST); return; }
        show(slot, 'error', 'request-error', explain(r));
      }, function () { show(slot, 'uncertain', 'request-uncertain', LOST); })
        .then(function () { busy = false; btn.removeAttribute('aria-busy'); });
    });
    return form;
  }

  function authorizeForm(onDone) {
    var slot = el('div', { class: 'slot' });
    var btn = el('button', { class: 'primary', type: 'submit', testid: 'authorize-submit', text: 'Place hold' });
    var ident = Identity();
    var busy = false;
    var form = el('form', { class: 'card', novalidate: true, 'aria-labelledby': 'authorize-title' },
      el('div', { class: 'card-head' }, el('h2', { id: 'authorize-title', text: 'Authorize a payment' })),
      el('p', { class: 'hint', text: 'Reserve money for someone to collect later. Nothing moves until they capture it.' }),
      textField('authorize-handle', 'For (handle)', 'authorize-handle', null, { placeholder: 'e.g. bob' }),
      amountField('authorize-amount', 'Amount (' + ctx.me.currency + ')', 'authorize-amount'),
      textField('authorize-note', 'Note (optional)', 'authorize-note', null, { maxlength: '200' }),
      visibilityField('authorize-visibility', 'authorize-visibility'),
      btn, slot);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (busy) return;
      var amount = parseDecimal(val('authorize-amount'));
      if (amount === null) { show(slot, 'error', 'authorize-error', badAmountMessage()); return; }
      var handle = cleanHandle(val('authorize-handle'));
      if (!handle) { show(slot, 'error', 'authorize-error', 'Enter the handle of the person who will collect.'); return; }
      var body = { to_handle: handle, amount: amount, note: val('authorize-note'), visibility: val('authorize-visibility') };
      busy = true; btn.setAttribute('aria-busy', 'true');
      show(slot, 'loading', null, 'Placing hold…');
      api('POST', '/authorizations', body, { key: ident.key(body) }).then(function (r) {
        if (r.ok) {
          show(slot, 'ok', 'authorize-success', 'Holding ' + fmt(r.data.amount) + ' for ' + r.data.to_handle + '.');
          return onDone();
        }
        if (r.status >= 500) { show(slot, 'uncertain', 'authorize-uncertain', LOST); return; }
        show(slot, 'error', 'authorize-error', explain(r));
        return onDone();
      }, function () { show(slot, 'uncertain', 'authorize-uncertain', LOST); })
        .then(function () { busy = false; btn.removeAttribute('aria-busy'); });
    });
    return form;
  }

  function pageHome() {
    var main = buildFrame('Wallet', 'Send and request money, and see what is happening.');
    renderWallet();
    refreshBtn = el('button', { class: 'secondary small', type: 'button', testid: 'wallet-refresh', text: 'Refresh', onclick: refreshWallet });
    walletFoot.appendChild(refreshBtn);
    walletFoot.appendChild(refreshNote);
    renderWallet();
    feedHost.appendChild(el('div', { class: 'card' }, el('span', { class: 'skeleton', 'aria-label': 'Loading activity' })));
    main.appendChild(walletHost);
    main.appendChild(el('div', { class: 'two-col' },
      el('div', { class: 'stack' }, payForm(), requestForm(), authorizeForm(refreshWallet)),
      el('section', { class: 'stack', 'aria-labelledby': 'feed-title' }, el('h2', { id: 'feed-title', text: 'Activity' }), feedHost)));
    refreshWallet();
  }

  /* ---------- requests ---------- */

  var reqSeq = 0;
  var reqHost = el('div', { class: 'stack' });
  var reqSlot = el('div', { class: 'slot' });
  var reqIdent = {};

  function loadRequests() {
    var mine = ++reqSeq;
    return Promise.all([api('GET', '/requests?direction=incoming&limit=200'), api('GET', '/requests?direction=outgoing&limit=200')]).then(function (rs) {
      if (mine !== reqSeq) return;
      if (rs[0].ok && rs[1].ok) renderRequests(rs[0].data.requests, rs[1].data.requests);
      else if (!reqHost.querySelector('[data-testid="incoming-list"]')) {
        clear(reqHost);
        reqHost.appendChild(el('div', { class: 'notice error', role: 'alert' }, 'We couldn’t load your requests. ',
          el('button', { class: 'secondary small', type: 'button', onclick: loadRequests, text: 'Try again' })));
      }
    }, function () {
      if (mine === reqSeq && !reqHost.querySelector('[data-testid="incoming-list"]')) {
        clear(reqHost);
        reqHost.appendChild(el('div', { class: 'notice error', role: 'alert' }, 'We couldn’t reach the server. ',
          el('button', { class: 'secondary small', type: 'button', onclick: loadRequests, text: 'Try again' })));
      }
    });
  }

  function requestAction(kind, rq, buttons, visSelect) {
    var path = '/requests/' + encodeURIComponent(rq.request_id) + '/' + kind;
    buttons.forEach(function (b) { b.setAttribute('disabled', ''); });
    clear(reqSlot);
    var p;
    if (kind === 'pay') {
      var body = { visibility: visSelect.value };
      reqIdent[rq.request_id] = reqIdent[rq.request_id] || Identity();
      p = api('POST', path, body, { key: reqIdent[rq.request_id].key(body) });
    } else {
      p = api('POST', path);
    }
    return p.then(function (r) {
      if (r.ok) {
        var msg = kind === 'pay' ? 'Paid ' + fmt(rq.amount) + ' to ' + rq.requester_handle + '.'
          : kind === 'decline' ? 'Request declined.' : 'Request cancelled.';
        show(reqSlot, 'ok', 'request-success', msg);
      } else if (r.status >= 500) {
        show(reqSlot, 'uncertain', 'request-error', LOST);
      } else {
        show(reqSlot, 'error', 'request-error', explain(r));
      }
    }, function () {
      show(reqSlot, 'uncertain', 'request-error', LOST);
    }).then(function () { return Promise.all([loadRequests(), refreshMeOnly()]); });
  }

  function requestItem(rq, incoming) {
    var buttons = [];
    var actions = null;
    var visSelect = null;
    if (rq.status === 'pending') {
      actions = el('div', { class: 'actions' });
      if (incoming) {
        visSelect = el('select', { id: 'rv-' + rq.request_id, 'aria-label': 'Visibility of the payment' },
          el('option', { value: 'public', text: 'Public payment' }), el('option', { value: 'private', text: 'Private payment' }));
        var pay = el('button', { class: 'primary small', type: 'button', testid: 'request-pay-' + rq.request_id, text: 'Pay ' + fmt(rq.amount) });
        var dec = el('button', { class: 'secondary small', type: 'button', testid: 'request-decline-' + rq.request_id, text: 'Decline' });
        buttons.push(pay, dec);
        pay.addEventListener('click', function () { requestAction('pay', rq, buttons, visSelect); });
        dec.addEventListener('click', function () { requestAction('decline', rq, buttons, visSelect); });
        actions.appendChild(el('div', { class: 'field' }, visSelect));
        actions.appendChild(pay);
        actions.appendChild(dec);
      } else {
        var can = el('button', { class: 'danger small', type: 'button', testid: 'request-cancel-' + rq.request_id, text: 'Cancel request' });
        buttons.push(can);
        can.addEventListener('click', function () { requestAction('cancel', rq, buttons, null); });
        actions.appendChild(can);
      }
    }
    return el('li', { class: 'item', testid: 'request-item-' + rq.request_id, 'data-status': rq.status },
      el('div', { class: 'item-top' },
        el('div', { class: 'item-main' },
          el('div', { class: 'parties', text: incoming ? rq.requester_handle + ' is asking you for' : 'You asked ' + rq.payer_handle + ' for' }),
          el('div', { class: 'note', testid: 'request-note-' + rq.request_id, text: rq.note })),
        el('div', { class: 'item-side' },
          el('div', { class: 'amount-line' }, el('span', { class: 'amount', testid: 'request-amount-' + rq.request_id, text: fmt(rq.amount) })),
          el('div', { class: 'chips' }, el('span', { class: 'chip ' + rq.status, text: rq.status.charAt(0).toUpperCase() + rq.status.slice(1) })),
          el('time', { class: 'meta', datetime: rq.created_at, title: rq.created_at, text: humanTime(rq.created_at) }))),
      actions);
  }

  function renderRequests(incoming, outgoing) {
    clear(reqHost);
    var none = !incoming.length && !outgoing.length;
    if (none) {
      reqHost.appendChild(el('div', { class: 'empty', testid: 'empty-requests' },
        el('strong', { text: 'No requests yet' }),
        el('span', { text: 'Requests you send or receive will appear here.' })));
    }
    function section(title, id, list, isIn, emptyText) {
      var ul = el('ul', { class: 'list', testid: id });
      list.forEach(function (rq) { ul.appendChild(requestItem(rq, isIn)); });
      var sec = el('section', { class: 'stack', 'aria-label': title, hidden: none ? '' : null },
        el('div', { class: 'section-title' }, el('h2', { text: title })),
        list.length ? null : el('p', { class: 'hint', text: emptyText }), ul);
      return sec;
    }
    reqHost.appendChild(section('Incoming', 'incoming-list', incoming, true, 'Nobody is asking you for money.'));
    reqHost.appendChild(section('Outgoing', 'outgoing-list', outgoing, false, 'You haven’t asked anyone for money.'));
  }

  function pageRequests() {
    var main = buildFrame('Requests', 'Pay, decline or cancel requests.');
    renderWallet();
    main.appendChild(walletHost);
    main.appendChild(reqSlot);
    reqHost.appendChild(el('div', { class: 'card' }, el('span', { class: 'skeleton', 'aria-label': 'Loading requests' })));
    main.appendChild(reqHost);
    loadRequests();
  }

  /* ---------- split ---------- */

  function pageSplit() {
    var main = buildFrame('Split a bill', 'Ask friends for their equal share of something you paid for.');
    renderWallet();
    var slot = el('div', { class: 'slot' });
    var preview = el('div', { class: 'preview', 'aria-live': 'polite' });
    var btn = el('button', { class: 'primary', type: 'submit', testid: 'split-submit', text: 'Send requests' });
    var ident = Identity();
    var busy = false;

    function handles() {
      return val('split-handles').split(',').map(function (h) { return cleanHandle(h); }).filter(function (h) { return h; });
    }
    function updatePreview() {
      clear(preview);
      var amount = parseDecimal(val('split-amount'));
      var hs = handles();
      if (amount === null || !hs.length) {
        preview.appendChild(el('p', { class: 'hint', text: 'Enter an amount and at least one handle to preview each share.' }));
        return;
      }
      var seen = {}, uniq = [];
      hs.forEach(function (h) { if (!seen[h]) { seen[h] = true; uniq.push(h); } });
      var shares = equalSplit(amount, hs.length);
      var ul = el('ul');
      var shown = {};
      hs.forEach(function (h, i) {
        if (shown[h]) return;
        shown[h] = true;
        ul.appendChild(el('li', null, el('span', { text: h }), el('span', { class: 'share', testid: 'split-share-' + h, text: fmt(shares[i]) })));
      });
      var box = el('div', { testid: 'split-preview' }, el('p', { class: 'label', text: 'Each share' }), ul);
      if (uniq.length !== hs.length) box.appendChild(el('p', { class: 'hint', text: 'Each handle can only appear once.' }));
      preview.appendChild(box);
    }

    var form = el('form', { class: 'card', novalidate: true, 'aria-labelledby': 'split-title' },
      el('h2', { id: 'split-title', text: 'Split a bill' }),
      amountField('split-amount', 'Total amount (' + ctx.me.currency + ')', 'split-amount'),
      textField('split-handles', 'People (handles, comma separated)', 'split-handles',
        'In order: when it does not divide evenly, the first people pay one unit more. Include yourself to take a share.', { placeholder: 'ada, bob, cy' }),
      textField('split-note', 'Note (optional)', 'split-note', null, { maxlength: '200' }),
      preview, btn, slot);
    form.addEventListener('input', updatePreview);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (busy) return;
      var amount = parseDecimal(val('split-amount'));
      if (amount === null) { show(slot, 'error', 'split-error', badAmountMessage()); return; }
      var hs = handles();
      if (!hs.length) { show(slot, 'error', 'split-error', 'Add at least one handle to split with.'); return; }
      var body = { amount: amount, participant_handles: hs, note: val('split-note') };
      busy = true; btn.setAttribute('aria-busy', 'true');
      show(slot, 'loading', null, 'Creating requests…');
      api('POST', '/splits', body, { key: ident.key(body) }).then(function (r) {
        if (r.ok) {
          var n = r.data.requests.length;
          clear(slot);
          slot.appendChild(el('div', { class: 'notice ok', role: 'status', testid: 'split-success' },
            n + (n === 1 ? ' request' : ' requests') + ' created. ', el('a', { href: '/requests', text: 'View requests' })));
          return refreshMeOnly();
        }
        if (r.status >= 500) { show(slot, 'uncertain', 'split-uncertain', LOST); return; }
        show(slot, 'error', 'split-error', explain(r));
      }, function () { show(slot, 'uncertain', 'split-uncertain', LOST); })
        .then(function () { busy = false; btn.removeAttribute('aria-busy'); });
    });
    main.appendChild(walletHost);
    main.appendChild(form);
    updatePreview();
  }

  /* ---------- authorizations ---------- */

  var authSeq = 0;
  var authHost = el('div', { class: 'stack' });
  var authSlot = el('div', { class: 'slot' });
  var captureIdent = {};

  function loadAuthorizations() {
    var mine = ++authSeq;
    return api('GET', '/authorizations?limit=200').then(function (r) {
      if (mine !== authSeq) return;
      if (r.ok) renderAuthorizations(r.data.authorizations);
      else if (!authHost.querySelector('[data-testid="authorization-list"]')) {
        clear(authHost);
        authHost.appendChild(el('div', { class: 'notice error', role: 'alert' }, 'We couldn’t load your authorizations. ',
          el('button', { class: 'secondary small', type: 'button', onclick: loadAuthorizations, text: 'Try again' })));
      }
    }, function () { /* keep what is on screen */ });
  }

  function afterAuthWrite() { return Promise.all([loadAuthorizations(), refreshMeOnly()]); }

  function authorizationItem(a) {
    var me = ctx.me, incoming = a.to_handle === me.handle, id = a.authorization_id;
    var actions = null;
    if (a.status === 'open') {
      actions = el('div', { class: 'actions' });
      if (incoming) {
        var amountIn = el('input', { id: 'cap-' + id, testid: 'authorization-capture-amount-' + id, type: 'text', inputmode: 'decimal', autocomplete: 'off', value: plainDecimal(a.remaining_amount) });
        var keep = el('input', { id: 'keep-' + id, type: 'checkbox' });
        var capBtn = el('button', { class: 'primary small', type: 'button', testid: 'authorization-capture-' + id, text: 'Capture' });
        capBtn.addEventListener('click', function () {
          var amt = parseDecimal(amountIn.value);
          clear(authSlot);
          if (amt === null) { show(authSlot, 'error', 'authorization-error', badAmountMessage()); return; }
          var body = { amount: amt };
          if (keep.checked) body.final = false;
          captureIdent[id] = captureIdent[id] || Identity();
          capBtn.setAttribute('disabled', '');
          api('POST', '/authorizations/' + encodeURIComponent(id) + '/capture', body, { key: captureIdent[id].key(body) }).then(function (r) {
            if (r.ok) show(authSlot, 'ok', 'authorization-success', 'Captured ' + fmt(r.data.amount) + ' from ' + a.from_handle + '.');
            else if (r.status >= 500) show(authSlot, 'uncertain', 'authorization-error', LOST);
            else show(authSlot, 'error', 'authorization-error', explain(r));
          }, function () { show(authSlot, 'uncertain', 'authorization-error', LOST); }).then(afterAuthWrite);
        });
        actions.appendChild(el('div', { class: 'field' },
          el('label', { for: 'cap-' + id, text: 'Amount to capture' }), amountIn));
        actions.appendChild(el('label', { class: 'checkbox', for: 'keep-' + id }, keep, 'Keep the rest on hold'));
        actions.appendChild(capBtn);
      } else {
        var voidBtn = el('button', { class: 'danger small', type: 'button', testid: 'authorization-void-' + id, text: 'Release hold' });
        voidBtn.addEventListener('click', function () {
          clear(authSlot);
          voidBtn.setAttribute('disabled', '');
          api('POST', '/authorizations/' + encodeURIComponent(id) + '/void').then(function (r) {
            if (r.ok) show(authSlot, 'ok', 'authorization-success', 'Hold released.');
            else if (r.status >= 500) show(authSlot, 'uncertain', 'authorization-error', LOST);
            else show(authSlot, 'error', 'authorization-error', explain(r));
          }, function () { show(authSlot, 'uncertain', 'authorization-error', LOST); }).then(afterAuthWrite);
        });
        actions.appendChild(voidBtn);
      }
    }
    var label = a.status.charAt(0).toUpperCase() + a.status.slice(1);
    var extra = [];
    if (a.status === 'captured') {
      extra.push(el('div', { class: 'meta' }, 'Captured ', el('span', { testid: 'authorization-captured-' + id, text: fmt(a.captured_amount) })));
    } else if (a.captured_amount > 0) {
      extra.push(el('div', { class: 'meta', text: 'Captured so far ' + fmt(a.captured_amount) }));
    }
    if (a.status === 'open') extra.push(el('div', { class: 'meta', text: 'Still held ' + fmt(a.remaining_amount) }));
    return el('li', { class: 'item', testid: 'authorization-item-' + id, 'data-status': a.status },
      el('div', { class: 'item-top' },
        el('div', { class: 'item-main' },
          el('div', { class: 'chips' },
            el('span', { class: 'chip ' + a.status, text: label }),
            el('span', { class: 'chip ' + (incoming ? 'received' : 'sent'), text: incoming ? 'Incoming' : 'Outgoing' }),
            el('span', { class: 'chip ' + a.visibility, text: a.visibility === 'private' ? 'Private' : 'Public' })),
          el('div', { class: 'parties', text: incoming ? a.from_handle + ' is holding money for you' : 'You are holding money for ' + a.to_handle }),
          el('div', { class: 'note', testid: 'authorization-note-' + id, text: a.note })),
        el('div', { class: 'item-side' },
          el('div', { class: 'amount-line' }, el('span', { class: 'amount', testid: 'authorization-amount-' + id, text: fmt(a.amount) })),
          extra,
          el('div', { class: 'meta' }, 'Expires ', el('span', { testid: 'authorization-expires-' + id, text: a.expires_at }),
            ' ', el('span', { text: '(' + relativeExpiry(a.expires_at) + ')' })))),
      actions);
  }

  function renderAuthorizations(list) {
    clear(authHost);
    var ul = el('ul', { class: 'list', testid: 'authorization-list' });
    list.forEach(function (a) { ul.appendChild(authorizationItem(a)); });
    if (!list.length) {
      authHost.appendChild(el('div', { class: 'empty', testid: 'empty-authorizations' },
        el('strong', { text: 'No authorizations yet' }),
        el('span', { text: 'Holds you place or that are placed for you will show up here.' })));
      ul.setAttribute('hidden', '');
    }
    authHost.appendChild(ul);
  }

  function pageAuthorizations() {
    var main = buildFrame('Authorizations', 'Reserve money now, capture it later.');
    renderWallet();
    main.appendChild(walletHost);
    authHost.appendChild(el('div', { class: 'card' }, el('span', { class: 'skeleton', 'aria-label': 'Loading authorizations' })));
    main.appendChild(el('div', { class: 'two-col' },
      authorizeForm(afterAuthWrite),
      el('section', { class: 'stack', 'aria-labelledby': 'auth-title' }, el('h2', { id: 'auth-title', text: 'Your authorizations' }), authSlot, authHost)));
    loadAuthorizations();
  }

  /* ---------- signup / login ---------- */

  function authPage(kind) {
    var main = buildFrame(kind === 'login' ? 'Welcome back' : 'Create your account',
      kind === 'login' ? 'Log in to your wallet.' : 'Your handle comes from your email address.');
    var slot = el('div', { class: 'slot' });
    var btn = el('button', { class: 'primary', type: 'submit', testid: kind + '-submit', text: kind === 'login' ? 'Log in' : 'Sign up' });
    var fields = [];
    if (kind === 'signup') fields.push(textField('signup-display-name', 'Display name', 'signup-display-name', null, { autocomplete: 'name', autocapitalize: 'words' }));
    fields.push(textField(kind + '-email', 'Email', kind + '-email', null, { type: 'email', autocomplete: 'email' }));
    fields.push(el('div', { class: 'field' }, el('label', { for: kind + '-password', text: 'Password' }),
      el('input', { id: kind + '-password', testid: kind + '-password', type: 'password', autocomplete: kind === 'login' ? 'current-password' : 'new-password' }),
      kind === 'signup' ? el('span', { class: 'hint', text: 'At least 8 characters.' }) : null));
    var busy = false;
    var form = el('form', { class: 'card auth-card', novalidate: true }, fields, btn, slot,
      el('p', { class: 'hint' }, kind === 'login' ? 'New here? ' : 'Already have an account? ',
        el('a', { href: kind === 'login' ? '/signup' : '/login', text: kind === 'login' ? 'Create an account' : 'Log in' })));
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (busy) return;
      var email = val(kind + '-email').trim(), password = val(kind + '-password');
      var body = { email: email, password: password };
      if (kind === 'signup') body.display_name = val('signup-display-name');
      busy = true; btn.setAttribute('aria-busy', 'true');
      api('POST', '/auth/' + kind, body, { noRedirect: true }).then(function (r) {
        if (r.ok && r.data && r.data.token) { setToken(r.data.token); location.assign('/'); return; }
        var code = r.data && r.data.error && r.data.error.code;
        show(slot, 'error', 'auth-error', code === 'unauthenticated' ? 'That email and password don’t match. Please try again.' : explain(r));
      }, function () {
        show(slot, 'error', 'auth-error', 'We couldn’t reach the server. Check your connection and try again.');
      }).then(function () { busy = false; btn.removeAttribute('aria-busy'); });
    });
    main.appendChild(form);
  }

  /* ---------- boot ---------- */

  function boot() {
    var token = getToken();
    var publicRoute = route === 'login' || route === 'signup';
    if (!token && !publicRoute) { location.replace('/login'); return; }
    if (publicRoute) {
      authPage(route);
      if (token) loadMe().then(function (r) { if (r.ok) renderWho(); else if (r.status === 401) dropToken(); });
      return;
    }
    buildFrame('Loading…');
    loadMe().then(function (r) {
      if (!r.ok) {
        if (r.status !== 401) {
          clear(appRoot);
          appRoot.appendChild(el('main', { id: 'main' }, el('div', { class: 'notice error', role: 'alert' }, 'We couldn’t load your wallet. ',
            el('button', { class: 'secondary small', type: 'button', onclick: boot, text: 'Try again' }))));
        }
        return;
      }
      renderWho();
      ({ home: pageHome, requests: pageRequests, split: pageSplit, authorizations: pageAuthorizations })[route]();
      renderWho();
    }, function () {
      clear(appRoot);
      appRoot.appendChild(el('main', { id: 'main' }, el('div', { class: 'notice error', role: 'alert' }, 'We couldn’t reach the server. ',
        el('button', { class: 'secondary small', type: 'button', onclick: boot, text: 'Try again' }))));
    });
  }

  boot();
})();
