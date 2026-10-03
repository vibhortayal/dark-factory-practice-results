/* Shared browser helpers: API client, session, header, formatting. */
(function () {
  "use strict";
  var TK = (window.TK = {});
  var TOKEN = "tk_token", USER = "tk_user";

  TK.session = {
    token: function () { return localStorage.getItem(TOKEN); },
    user: function () { try { return JSON.parse(localStorage.getItem(USER)); } catch (e) { return null; } },
    set: function (token, user) {
      localStorage.setItem(TOKEN, token); localStorage.setItem(USER, JSON.stringify(user));
      TK.renderAccount();
    },
    clear: function () {
      localStorage.removeItem(TOKEN); localStorage.removeItem(USER);
      TK.renderAccount();
    },
  };

  /* el("div", {class: "x", "data-testid": "y"}, "text", childNode) -> element (text is never parsed as HTML) */
  TK.el = function (tag, attrs) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] === false || attrs[k] == null) return;
      node.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      node.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
    }
    return node;
  };

  TK.newKey = function () {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var bytes = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(bytes);
    else for (var i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    return Array.prototype.map.call(bytes, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  };

  /* Resolves {status, data}; rejects with {network: true} when no usable response arrived. */
  TK.api = function (method, path, opts) {
    opts = opts || {};
    var headers = {};
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (opts.key) headers["Idempotency-Key"] = opts.key;
    if (opts.auth && TK.session.token()) headers["Authorization"] = "Bearer " + TK.session.token();
    var ctl = window.AbortController ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, opts.timeout || 15000) : null;
    return fetch(path, {
      method: method, headers: headers, signal: ctl ? ctl.signal : undefined,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    }).then(function (resp) {
      return resp.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (resp.status === 401 && opts.auth) TK.session.clear();
        return { status: resp.status, data: data };
      });
    }, function () { throw { network: true }; }).then(function (r) { clearTimeout(timer); return r; },
      function (e) { clearTimeout(timer); throw e; });
  };

  TK.errorCode = function (res) { return res.data && res.data.error && res.data.error.code; };

  var MESSAGES = {
    table_unavailable: "That table was just taken by someone else. We've refreshed the availability — please choose another table or time.",
    not_on_slot_grid: "That start time isn't one the restaurant offers.",
    outside_opening_hours: "The restaurant isn't open at that time.",
    party_exceeds_capacity: "That party is too large for the chosen table(s).",
    combination_not_allowed: "Those tables can't be booked together.",
    invalid_local_time: "That time doesn't exist on this date.",
    cutoff_passed: "This booking starts too soon to be changed online. Please call the restaurant.",
    reservation_cancelled: "This booking has already been cancelled.",
    unauthenticated: "Your session has ended. Please log in again.",
    not_found: "We couldn't find that.",
    validation_failed: "Please check the details you entered.",
  };
  TK.message = function (res) {
    var code = TK.errorCode(res);
    return MESSAGES[code] || (res.data && res.data.error && res.data.error.message) || "Something went wrong.";
  };

  /* ---- table labels and times ---- */
  TK.tableName = function (rest, id) {
    var t = (rest.tables || []).filter(function (x) { return x.id === id; })[0];
    return t ? String(t.label) : id;
  };
  TK.tablesText = function (rest, ids) {
    var names = ids.map(function (id) { return TK.tableName(rest, id); });
    return (names.length > 1 ? "Tables " : "Table ") + names.join(" + ");
  };
  TK.seats = function (rest, ids) {
    return ids.reduce(function (sum, id) {
      var t = (rest.tables || []).filter(function (x) { return x.id === id; })[0];
      return sum + (t ? t.capacity : 0);
    }, 0);
  };
  TK.timeOf = function (local) { return local.slice(11, 16); };
  TK.whenText = function (local) {
    var p = local.split(/[-T:]/).map(Number);
    var day = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
    return day.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
      + ", " + TK.timeOf(local);
  };

  /* ---- header ---- */
  TK.renderAccount = function () {
    var box = document.getElementById("account");
    if (!box) return;
    var user = TK.session.token() && TK.session.user();
    box.textContent = "";
    if (user) {
      var out = TK.el("button", { type: "button", class: "btn btn-small", "data-testid": "logout-button" }, "Log out");
      out.addEventListener("click", function () {
        TK.session.clear();
        document.dispatchEvent(new CustomEvent("tk:signedout"));
      });
      box.appendChild(TK.el("span", { class: "current-user", "data-testid": "current-user" }, "Signed in as ",
        TK.el("strong", {}, user.display_name)));
      box.appendChild(out);
    } else {
      box.appendChild(TK.el("a", { href: "/login" }, "Log in"));
      box.appendChild(TK.el("a", { class: "btn btn-small", href: "/signup" }, "Sign up"));
    }
  };

  var page = document.body.getAttribute("data-page");
  Array.prototype.forEach.call(document.querySelectorAll("[data-nav]"), function (a) {
    if (a.getAttribute("data-nav") === page) a.setAttribute("aria-current", "page");
  });
  TK.renderAccount();
})();
