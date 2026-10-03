/* Signup and login screens. */
(function () {
  "use strict";
  var isSignup = !!document.getElementById("signup-form");
  var form = document.getElementById(isSignup ? "signup-form" : "login-form");
  var slot = document.getElementById("auth-slot");
  var done = document.getElementById("auth-done");
  var busy = false;

  function showError(text) {
    slot.textContent = "";
    slot.appendChild(TK.el("p", { class: "notice notice-refused", role: "alert", "data-testid": "auth-error" }, text));
  }

  function finish(data) {
    TK.session.set(data.token, { user_id: data.user_id, display_name: data.display_name });
    form.hidden = true;
    done.textContent = "";
    done.appendChild(TK.el("div", { class: "notice notice-success", role: "status" },
      isSignup ? "Welcome, " + data.display_name + "! Your account is ready." : "Good to see you, " + data.display_name + "."));
    done.appendChild(TK.el("a", { class: "btn btn-primary", href: "/" }, "Find a table"));
  }

  function value(id) { return document.getElementById(id).value; }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (busy) return;
    slot.textContent = "";
    var path, body;
    if (isSignup) {
      path = "/auth/signup";
      body = { email: value("signup-email").trim(), password: value("signup-password"), display_name: value("signup-display-name").trim() };
      if (!body.display_name || !body.email || !body.password) return showError("Please fill in your name, email and password.");
    } else {
      path = "/auth/login";
      body = { email: value("login-email").trim(), password: value("login-password") };
      if (!body.email || !body.password) return showError("Please enter your email and password.");
    }
    busy = true;
    TK.api("POST", path, { body: body }).then(function (res) {
      busy = false;
      if (res.status === 200 || res.status === 201) return finish(res.data);
      var code = TK.errorCode(res);
      if (code === "email_taken") showError("That email is already registered. Try logging in instead.");
      else if (code === "unauthenticated") showError("The email or password isn't right. Please try again.");
      else if (res.status === 422) showError("Please use a valid email address and a password of at least 8 characters.");
      else showError("We couldn't complete that just now. Please try again.");
    }, function () {
      busy = false;
      showError("We couldn't reach the server. Check your connection and try again.");
    });
  });
})();
