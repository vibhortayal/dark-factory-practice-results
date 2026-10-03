/* Search screen: availability grid, booking form, confirmation. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var form = $("search-form"), results = $("results"), bookingArea = $("booking-area"), searchError = $("search-error");
  var select = $("restaurant-select"), dateInput = $("date-input"), partyInput = $("party-size-input");

  var searchSeq = 0;      // every search/refresh takes a number; only the latest may render
  var ctx = null;         // the rendered search: {rest, avail, party, date}
  var selection = null;   // the open booking form: {ids, local, node...}
  searchError.setAttribute("data-testid", "search-error");

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  var now = new Date();
  dateInput.value = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());

  function setSearchError(text) { searchError.hidden = !text; searchError.textContent = text || ""; }

  /* ---- restaurants ---- */
  function loadRestaurants() {
    TK.api("GET", "/restaurants").then(function (res) {
      var list = (res.data && res.data.restaurants) || [];
      select.textContent = "";
      list.forEach(function (r) { select.appendChild(TK.el("option", { value: r.id }, r.name)); });
      if (!list.length) setSearchError("No restaurants are available right now.");
    }, function () {
      setSearchError("We couldn't load the restaurants. Please reload the page.");
    });
  }

  /* ---- grid ---- */
  function cellNode(ids, slot, available, rest, party) {
    var time = TK.timeOf(slot.starts_at_local);
    var seats = TK.seats(rest, ids);
    var meta = available ? "Free · seats " + seats : (seats < party ? "Too small · seats " + seats : "Booked · seats " + seats);
    var node = TK.el("button", {
      type: "button", class: "cell", "data-testid": "slot-" + ids.join("+") + "-" + time,
      "data-available": available ? "true" : "false", "data-combo": ids.length > 1 ? "true" : false,
      "aria-disabled": available ? false : "true", "aria-pressed": "false",
    }, TK.el("span", { class: "cell-name" }, TK.tablesText(rest, ids)), TK.el("span", { class: "cell-meta" }, meta));
    node.addEventListener("click", function () {
      if (node.getAttribute("data-available") !== "true") return;
      onCell(ids, slot, node);
    });
    node._ids = ids; node._local = slot.starts_at_local;
    return node;
  }

  function renderGrid() {
    results.textContent = "";
    var rest = ctx.rest, avail = ctx.avail;
    if (!avail.slots.length) {
      results.appendChild(TK.el("div", { class: "empty-state", "data-testid": "no-slots" },
        TK.el("p", { class: "empty-title" }, rest.name + " has no tables to book that day"),
        TK.el("p", {}, "The restaurant is closed on " + TK.whenText(avail.date + "T00:00").split(",")[0] + "s. Try another date.")));
      return;
    }
    var grid = TK.el("section", { class: "grid", "data-testid": "availability-grid", "aria-label": "Availability at " + rest.name });
    grid.appendChild(TK.el("div", { class: "results-head" },
      TK.el("h2", {}, rest.name),
      TK.el("p", {}, TK.whenText(avail.date + "T00:00").split(",").slice(0, 2).join(",") + " · party of " + ctx.party + " · times are local to the restaurant")));
    grid.appendChild(TK.el("div", { class: "legend", "aria-hidden": "true" },
      TK.el("span", {}, TK.el("span", { class: "swatch free" }), "Free"),
      TK.el("span", {}, TK.el("span", { class: "swatch taken" }), "Booked or too small"),
      TK.el("span", {}, TK.el("span", { class: "swatch chosen" }), "Your choice")));
    avail.slots.forEach(function (slot) {
      var open = {};
      (slot.available_options || []).forEach(function (o) { open[o.table_ids.join("+")] = true; });
      var cells = TK.el("div", { class: "cells" });
      rest.tables.forEach(function (t) {
        cells.appendChild(cellNode([t.id], slot, !!open[t.id] || slot.available_table_ids.indexOf(t.id) >= 0, rest, ctx.party));
      });
      (slot.available_options || []).forEach(function (o) {
        if (o.table_ids.length > 1) cells.appendChild(cellNode(o.table_ids, slot, true, rest, ctx.party));
      });
      grid.appendChild(TK.el("div", { class: "slot-row" },
        TK.el("h3", { class: "slot-time" }, TK.timeOf(slot.starts_at_local)), cells));
    });
    results.appendChild(grid);
    markSelected();
  }

  function markSelected() {
    Array.prototype.forEach.call(results.querySelectorAll(".cell"), function (c) {
      var on = !!selection && c._local === selection.local && c._ids.join("+") === selection.ids.join("+");
      c.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  /* ---- searching (latest search wins) ---- */
  function fetchSearch(restaurantId, date, party) {
    var q = "?restaurant_id=" + encodeURIComponent(restaurantId) + "&date=" + encodeURIComponent(date) + "&party_size=" + party;
    return Promise.all([TK.api("GET", "/availability" + q), TK.api("GET", "/restaurants/" + encodeURIComponent(restaurantId))]);
  }

  function runSearch(ev) {
    if (ev) ev.preventDefault();
    var party = partyInput.value.trim();
    if (!select.value) return setSearchError("Choose a restaurant first.");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) return setSearchError("Choose a date.");
    if (!/^[0-9]{1,6}$/.test(party) || Number(party) < 1) return setSearchError("Enter a party size of 1 or more.");
    setSearchError("");
    var mine = ++searchSeq;
    ctx = null; closeBooking();
    results.textContent = "";
    results.appendChild(TK.el("div", { class: "loading", role: "status" }, TK.el("span", { class: "spinner" }), "Finding free tables…"));
    var wanted = { id: select.value, date: dateInput.value, party: Number(party) };
    fetchSearch(wanted.id, wanted.date, wanted.party).then(function (pair) {
      if (mine !== searchSeq) return;                       // a newer search superseded this one
      var avail = pair[0], rest = pair[1];
      if (avail.status !== 200 || rest.status !== 200) {
        results.textContent = "";
        results.appendChild(TK.el("p", { class: "notice notice-refused", role: "alert" }, avail.status === 404 ? "We couldn't find that restaurant." : "We couldn't load availability. Please try again."));
        return;
      }
      ctx = { rest: rest.data, avail: avail.data, party: wanted.party, date: wanted.date, restaurantId: wanted.id };
      renderGrid();
    }, function () {
      if (mine !== searchSeq) return;
      results.textContent = "";
      results.appendChild(TK.el("p", { class: "notice notice-refused", role: "alert" }, "We couldn't reach the server. Check your connection and search again."));
    });
  }

  /* Re-read availability for the current search, keeping the booking form as it is. */
  function refreshAvailability() {
    if (!ctx) return;
    var mine = ++searchSeq, was = ctx;
    fetchSearch(was.restaurantId, was.date, was.party).then(function (pair) {
      if (mine !== searchSeq || pair[0].status !== 200 || pair[1].status !== 200) return;
      ctx = { rest: pair[1].data, avail: pair[0].data, party: was.party, date: was.date, restaurantId: was.restaurantId };
      renderGrid();
    }, function () { /* keep what is on screen; the server decides on the next submit */ });
  }

  /* ---- booking ---- */
  function closeBooking() { selection = null; bookingArea.textContent = ""; }

  function onCell(ids, slot, node) {
    if (!TK.session.token()) {
      closeBooking(); markSelected();
      bookingArea.appendChild(TK.el("p", { class: "notice notice-refused", role: "alert", "data-testid": "auth-error" },
        "Please ", TK.el("a", { href: "/login" }, "log in"), " or ", TK.el("a", { href: "/signup" }, "sign up"), " to book a table."));
      return;
    }
    openBooking(ids, slot);
  }

  function openBooking(ids, slot) {
    var rest = ctx.rest, sel = { ids: ids, local: slot.starts_at_local, pending: null, inflight: false, rest: rest, restaurantId: ctx.restaurantId };
    selection = sel;
    var summary = rest.name + " · " + TK.tablesText(rest, ids) + " (seats " + TK.seats(rest, ids) + ") · " + TK.whenText(slot.starts_at_local);
    var party = TK.el("input", { id: "booking-party-size", "data-testid": "booking-party-size", type: "number", min: "1", step: "1", value: String(ctx.party) });
    var submit = TK.el("button", { type: "submit", class: "btn btn-primary", "data-testid": "booking-submit" }, "Confirm booking");
    var feedback = TK.el("div", { id: "booking-feedback", "aria-live": "polite" });
    var confirmation = TK.el("div", { id: "confirmation-slot" });
    var formEl = TK.el("form", { novalidate: true },
      TK.el("div", { class: "booking-fields" },
        TK.el("div", { class: "field" }, TK.el("label", { for: "booking-party-size" }, "Party size"), party), submit), feedback);
    bookingArea.textContent = "";
    bookingArea.appendChild(TK.el("section", { class: "card booking", "data-testid": "booking-form", "aria-label": "Book your table" },
      TK.el("h2", {}, "Reserve your table"),
      TK.el("p", { class: "booking-summary", "data-testid": "booking-summary" }, summary), formEl));
    bookingArea.appendChild(confirmation);
    markSelected();
    formEl.addEventListener("submit", function (ev) { ev.preventDefault(); submitBooking(sel, party, submit, feedback, confirmation); });
    bookingArea.scrollIntoView && bookingArea.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function feedbackNode(kind, text, extra) {
    var attrs = kind === "error"
      ? { class: "notice notice-refused", role: "alert", "data-testid": "booking-error" }
      : { class: "notice notice-uncertain", role: "status", "data-testid": "booking-uncertain" };
    return TK.el("p", attrs, text, extra || null);
  }

  function submitBooking(sel, partyInput, button, feedback, confirmation) {
    if (sel.inflight || selection !== sel) return;
    var party = partyInput.value.trim();
    if (!/^[0-9]{1,6}$/.test(party) || Number(party) < 1) {
      feedback.textContent = "";
      feedback.appendChild(feedbackNode("error", "Enter a party size of 1 or more."));
      return;
    }
    var body = { restaurant_id: sel.restaurantId, starts_at_local: sel.local, party_size: Number(party) };
    if (sel.ids.length === 1) body.table_id = sel.ids[0]; else body.table_ids = sel.ids;
    var sig = JSON.stringify(body);
    // The idempotency identity is made once per distinct form content and only a change of
    // content replaces it; a failed or lost request never does (spec §7, stage-2 retries).
    if (!sel.pending || sel.pending.sig !== sig) sel.pending = { sig: sig, key: TK.newKey(), body: body };
    var pending = sel.pending;
    sel.inflight = true; button.disabled = true; button.textContent = "Booking…";

    function settle() { sel.inflight = false; button.disabled = false; button.textContent = sel.uncertain ? "Try again" : "Confirm booking"; }
    function live() { return selection === sel; }

    TK.api("POST", "/reservations", { body: pending.body, key: pending.key, auth: true }).then(function (res) {
      sel.uncertain = false;
      if (res.status === 201 || res.status === 200) {
        if (live()) showConfirmation(res.data, sel, feedback, confirmation);
        settle(); refreshAvailability();
        return;
      }
      if (res.status >= 500 || !res.data || !res.data.error) {
        sel.uncertain = true;
        if (live()) showUncertain(feedback, confirmation);
        settle(); return;
      }
      if (live()) {
        confirmation.textContent = ""; feedback.textContent = "";
        feedback.appendChild(feedbackNode("error", TK.message(res),
          res.status === 401 ? TK.el("a", { href: "/login" }, " Log in") : null));
      }
      settle();
      if (TK.errorCode(res) === "table_unavailable") refreshAvailability();
    }, function () {
      sel.uncertain = true;
      if (live()) showUncertain(feedback, confirmation);
      settle();
    });
  }

  function showUncertain(feedback, confirmation) {
    confirmation.textContent = ""; feedback.textContent = "";
    feedback.appendChild(feedbackNode("uncertain",
      "We didn't get an answer from the restaurant, so we can't tell yet whether your table is booked. " +
      "Press “Try again” to check — it is safe, you won't be booked twice."));
  }

  function showConfirmation(rez, sel, feedback, confirmation) {
    feedback.textContent = ""; confirmation.textContent = "";
    var rest = sel.rest, tables = TK.tablesText(rest, TK.tableIds(rez));
    confirmation.appendChild(TK.el("section", { class: "confirmation", "data-testid": "confirmation", role: "status" },
      TK.el("h3", {}, "You're booked — see you soon!"),
      TK.el("span", { class: "reference", "data-testid": "confirmation-reference" }, rez.reference),
      TK.el("p", { "data-testid": "confirmation-details" },
        rest.name + " · " + tables + " · " + TK.whenText(rez.starts_at_local) + " · party of " + rez.party_size),
      TK.el("p", {}, "Seating: ", TK.el("strong", { "data-testid": "confirmation-tables" }, tables), ". Keep your reference to look the booking up or cancel it."),
      TK.el("a", { href: "/lookup" }, "Look up a booking")));
  }

  document.addEventListener("tk:signedout", function () { closeBooking(); markSelected(); });
  form.addEventListener("submit", runSearch);
  loadRestaurants();
})();
