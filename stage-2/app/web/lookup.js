/* Look up a reservation by reference; cancel it. */
(function () {
  "use strict";
  var form = document.getElementById("lookup-form");
  var slot = document.getElementById("lookup-slot");
  var input = document.getElementById("lookup-reference-input");
  var cancelling = false;

  function showError(text, withLogin) {
    slot.textContent = "";
    var box = TK.el("p", { class: "notice notice-refused", role: "alert", "data-testid": "reservation-error" }, text);
    if (withLogin) { box.appendChild(document.createTextNode(" ")); box.appendChild(TK.el("a", { href: "/login" }, "Log in")); }
    slot.appendChild(box);
  }

  function row(dl, term, value) {
    dl.appendChild(TK.el("dt", {}, term));
    dl.appendChild(value && value.nodeType ? TK.el("dd", {}, value) : TK.el("dd", {}, value));
  }

  function render(rez, rest) {
    slot.textContent = "";
    var status = TK.el("span", { class: "badge badge-" + rez.status, "data-testid": "reservation-status" }, rez.status);
    var dl = TK.el("dl", { class: "detail-list" });
    row(dl, "Reference", rez.reference);
    row(dl, "Restaurant", rest.name);
    row(dl, "When", TK.whenText(rez.starts_at_local));
    dl.appendChild(TK.el("dt", {}, "Table"));
    dl.appendChild(TK.el("dd", { "data-testid": "reservation-tables" }, TK.tablesText(rest, rez.table_ids)));
    row(dl, "Party of", String(rez.party_size));
    var card = TK.el("section", { class: "card lookup-card", "data-testid": "reservation-detail" },
      TK.el("h2", {}, "Your booking ", status), dl);
    if (rez.status === "confirmed") {
      var btn = TK.el("button", { type: "button", class: "btn", "data-testid": "reservation-cancel-button" }, "Cancel this booking");
      btn.addEventListener("click", function () { cancel(rez, rest, btn); });
      card.appendChild(TK.el("div", { class: "lookup-actions" }, btn));
    }
    slot.appendChild(card);
  }

  function showFailure(rez, rest, text) {
    var old = slot.querySelector("[data-testid='reservation-error']");
    if (old) old.remove();
    slot.insertBefore(TK.el("p", { class: "notice notice-refused", role: "alert", "data-testid": "reservation-error" }, text), slot.firstChild);
  }

  function cancel(rez, rest, btn) {
    if (cancelling) return;
    cancelling = true; btn.disabled = true;
    TK.api("POST", "/reservations/" + encodeURIComponent(rez.reference) + "/cancel", { auth: true }).then(function (res) {
      cancelling = false;
      if (res.status === 200) return render(res.data, rest);
      btn.disabled = false;
      showFailure(rez, rest, TK.message(res));
    }, function () {
      cancelling = false; btn.disabled = false;
      showFailure(rez, rest, "We couldn't reach the server. Your booking has not been changed here — please try again.");
    });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var ref = input.value.trim().toUpperCase();
    slot.textContent = "";
    if (!ref) return showError("Enter the reference from your confirmation.");
    if (!TK.session.token()) return showError("Please log in to look up your bookings.", true);
    TK.api("GET", "/reservations/" + encodeURIComponent(ref), { auth: true }).then(function (res) {
      if (res.status === 401) return showError("Your session has ended.", true);
      if (res.status === 404) return showError("We couldn't find a booking with that reference on your account.");
      if (res.status !== 200) return showError("We couldn't look that up just now. Please try again.");
      var rez = res.data;
      return TK.api("GET", "/restaurants/" + encodeURIComponent(rez.restaurant_id)).then(function (r) {
        render(rez, r.status === 200 ? r.data : { name: rez.restaurant_id, tables: [] });
      }, function () { render(rez, { name: rez.restaurant_id, tables: [] }); });
    }, function () { showError("We couldn't reach the server. Please try again."); });
  });
  document.addEventListener("tk:signedout", function () { slot.textContent = ""; });
})();
