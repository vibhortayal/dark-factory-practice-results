# Stage 2 self-check (row by row)

Evidence at the reported revision: `stage-2/tests` against the built image (`docker run --cpus 2 --memory 2g`):
`test_api` + `test_concurrency` (stage-1 rows, adapted only for the two stage-2 changes: payment objects gain
`authorization_id`, `/authorizations` and `/` are no longer 404), `test_stage2_api` (33 tests), `test_browser`
(34 Playwright/Chromium tests, 375 px and 1280 px). Supplied harness: `claimed stage: 2`. The unmodified stage-1 own
tests (from 8e43652) against the stage-2 image fail exactly those two stage-changed assertions and nothing else.
Screens at 375 px and 1280 px were looked at (`SHOTS=` screenshots) for every route.

| Rows | How checked | Result |
|---|---|---|
| B2.1 | Supplied suite 1 (147 checks) passes against stage-2; own stage-1 tests rerun (see above); stage-1 export (real container of the accepted image) imported into stage-2 by hand | OK |
| B2.2 | Dockerfile copies `app.py` + `static/`; everything served from the image; isolated harness run; browser tests run with no external requests (page errors/console errors asserted empty) | OK |
| B2.3 | `git diff 8e43652 -- stage-1` empty | OK |
| B2.4 | `UiRouting.test_no_stage3_surface`: `/statement`, `as_of`, refunds, corrections have no effect | OK |
| B2.5 | `Fixtures.test_reset_5000_users_within_limit` (4.7 s under 2 CPUs), concurrency suite 50-way, expiry under load | OK |
| B2.6 | `UiRouting.test_odd_accept_headers_never_5xx`, mutated-export fuzz for the new state, inherited stage-1 fuzz | OK |
| U1-U4 | `Screens.test_routes_signed_out_and_in` (deep links, reload, redirect to login, logout), `UiRouting.test_accept_negotiation` (HTML vs JSON on `/requests` and `/authorizations`, with/without token and Accept variants) | OK |
| L1-L6 | `Screens.test_signup_login_errors`, harness checks, `current-handle` exact text | OK |
| Y1-Y9 | `Screens.test_formats_and_headline` (EUR/JPY/BHD), `Pay` (decimals, no request on bad input, JPY no decimal point, double submit/dblclick once, new key on change, request form) | OK |
| F1-F7 | `Pay.test_feed_rows` (newest first, exact amount/note text incl. `<b>`, spaces, combining chars, emoji, empty note element, visibility attribute, private of others hidden) | OK |
| Q-1..Q-7, Q-5/6 | `Requests` | OK |
| T1-T5 | `Split` (preview before any POST, order dependence, 0.01 among three, submit, errors) | OK |
| R2.1-R2.7 | `Competing`: refresh keeps form; stale `/me` answer released after a newer refresh does not overwrite (request interception); refused payment after competing spend; stale request pay button; lost response after commit then same-key retry (one payment); lost before commit; no polling in code | OK |
| G1 | Real stage-1 container export imported into stage-2 by hand (login, tokens, replay of lost payment 200, pending request payable, new authorization works); `RoundTrip.test_stage1_export_accepted`; harness `previous_api` check | OK |
| G2-G4 | `Competing.test_upgrade_between_requests` (export after a lost response, reset to other data, import, same page without reload: still signed in, form kept, retry recovers the payment with the same key, imported request payable) | OK |
| G5 G6 | `RoundTrip` (authorizations, captures, ttl, idempotency records of both new paths; invalid and mutated authorization state -> 422 with destination unchanged) | OK |
| W1-W7 | `Wallet`, `Capture`, `Fixtures`, `Concurrent.test_holds_never_overspend` | OK |
| Z1-Z19 | `Capture` (default and extended capture, errors and S2-1 order, idempotency incl. `{}` vs `{"amount"}` and `final`, void, partial then void/expiry, list filters and paging, expiry by the clock with ttl 1-2 s, no activity item for holds) | OK |
| X2.1-X2.6 | `Fixtures` (ttl default/validation, seeded statuses, expired seeded open ignored, holds above balance -> 422 nothing changed, seeded holds capturable/voidable) | OK |
| A2.3 / S2-8 | `AuthorizeFormOnBothRoutes`: the authorise form (all six testids, unique per page) on `/` and on `/authorizations`; refusal shows `authorize-error` on the route used; success refreshes wallet numbers in place without clearing the pay form on `/`, and the list on `/authorizations` | OK |
| A2.1-A2.10 | `Screens.test_formats_and_headline` (headline font size vs total/held, held absent at zero), `Authorizations` (authorize, partial capture keeping the rest, final capture, void, refused capture, expiry, seeded holds after reset, empty state) | OK |
| V1-V6 | Screenshot review of every route at both widths; `Narrow`/`Wide` assert `scrollWidth <= clientWidth` with 200-char notes; `Accessibility` (labels on every input, focus outlines, keyboard-only login, computed WCAG contrast over all text on four screens with a held balance, request and private payment present); distinct states: available/held/pending/loading/ok/refused/uncertain have different colours and icons plus text | OK |
| C2.1 C2.2 | `Concurrent` (over-capture race, capture vs void vs final, mixed load incl. exports and expiry, same-key races) | OK |

Known incomplete: none. Design choices (also in the handoff):
S2-1..S2-7 followed. Authorization timestamps carry millisecond precision (`created_at`, `expires_at`, so
`expires_at - created_at == ttl` holds exactly and short ttls do not expire early); other timestamps keep second
precision. Retry identity (key + body) lives in page memory per form. Seeded fixture users are hashed with scrypt
n=2^9 (stored in the hash), signups with n=2^12.

Round S2-8: the authorise form is on both `/` (under the request form, pay stays first) and `/authorizations`.

Round 1 (Verifier BLOCK on 10c60b0): F1 capture amount above 1000000000 (or any size) is now `capture_exceeds_authorization`; only amounts below 1 / non-integral stay `validation_failed` (`Capture.test_errors_and_precedence`). F2 the per-request payment-visibility select has a visible `<label>` (`Competing.test_stale_request_pay_button` checks label count and visibility). Also: closed authorizations no longer say "is holding" / "(in N min)"; item side column has a fixed minimum width so amounts align.

Round 1 continued (Architect S2-9..S2-12): S2-9 capture amount rule (see above, also 1e30, 2^53+1 -> `capture_exceeds_authorization`; 1.5, 0, negatives -> `validation_failed`). S2-10 decimal inputs accept `.5` and `15.` (never more than `minor_units` fraction digits; `minor_units` 0 refuses any fraction digits except a bare trailing dot), in pay, request, split, authorise and capture (`Decimals`). S2-11 retry identity of pay/request/authorise/split forms is the typed text of every field: `15` -> `15.00` is a new payment, an unchanged form replays (`Decimals.test_typed_text_is_the_retry_identity`). S2-12 `Labels.test_every_control_has_a_visible_label` (every visible input/select/checkbox on every route at 375 and 1280 px has a visible `<label>`, no horizontal scroll); closed authorizations describe what happened (captured: collected/released amounts, voided, expired) and keep exact `authorization-expires-{id}` text (`Labels.test_closed_authorization_copy`); amounts are aligned to a fixed right column on cards.
Browser suite is now 34 tests.

Round 2 (Architect, Z10/S2-9 and V2/V4): amounts are classified by numeric value, not spelling. A JSON number too large for Decimal is kept as an opaque value classified from its text (zero / negative / non-integral / positive integral, exponents parsed exactly with a cap). Capture: zero, negatives and non-integral values in any spelling (`0`, `0.0`, `-0`, `0e5`, `0e1000000000000000000`, `-1e30`, `0.0e-999999999999999999999`, `1e-1000000000000000000`, ...) -> 422 `validation_failed`; positive integral values of any size (`1e30`, `1e1000000000000000000`, `20010e-1`) -> compared with the remainder -> 422 `capture_exceeds_authorization`; closed authorization -> 409 first. The same spelling sets on payments, requests, splits, authorizations and settlement entries -> 422 `validation_failed`; a fixture balance written `0`, `0.0`, `0e5`, `0e1000000000000000000` is valid (204), other spellings of non-zero/non-integral/negative/huge -> 422; fixture authorization amounts and ttl likewise. Tests: `AmountSpellings` (3). Cosmetic: `authorization-expires-{id}` is `white-space: nowrap` in a 15 rem side column, so the value never breaks mid-token (checked in the 1280 px screenshot; no horizontal scroll at 375 px, browser suite).
