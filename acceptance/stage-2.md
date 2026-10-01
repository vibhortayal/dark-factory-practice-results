# Acceptance map — Pocketful stage 2

Sources: `dark-factory-wearedevs/pocketful/spec/stage-2.md` (whole file) on top of
`pocketful/spec/stage-1.md` (whole file, still in force). Target folder: `stage-2/`, created
as a copy of the accepted `stage-1/` (revision 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb)
and extended. `stage-1/` itself must not change.

Check codes: `H` = supplied harness suites (partial sample; stage-2 run executes suites 1 and 2),
`T` = own black-box HTTP test against the built container, `C` = concurrency test,
`B` = browser test (Playwright/Chromium against the built container) at 375 px and at a
desktop width, `I` = inspection. A row is accepted only on Verifier evidence for the head revision.

## B2 — Carry-over and delivery

| Row | Requirement | Check |
|---|---|---|
| B2.1 | Every row of `acceptance/stage-1.md` (D, R, M, I, E, A, K, P, S, X, N, decisions Q1-Q8) still holds for `stage-2/`, except where this map states a stage-2 change (HTML on the screen routes, new fields on `/me` and payments, `available`-based funds checks, seven idempotent paths). | H suite 1 + stage-1 own tests rerun against the stage-2 image + T |
| B2.2 | `stage-2/` is a complete buildable service: source, `Dockerfile`, `RUN.md`, own tests; no nested `.git`; runs alone with `-e PORT`; no outbound network at run time — every script, stylesheet, font and image is served from the image (no CDN, no external font or script URL). | I + H `--mode isolated` + B with network blocked |
| B2.3 | `stage-1/` is byte-identical to the accepted revision (`git diff 8e43652 -- stage-1` empty). | I |
| B2.4 | `stage-2/` implements stage 2 only: no stage-3/4 surface (no `/statement`, no as-of `/me`, no payment corrections, no refunds or batch corrections). Harness prints `claimed stage: 2`. | H + T: such routes/params have no effect |
| B2.5 | Resource limits of stage-1 §2 still hold with the UI: start < 60 s, 2 vCPU / 2 GiB, 50 in flight, 5 s per request, 10 s for reset/export/import. | T + C |
| B2.6 | No request yields a 5xx or a non-§5 error body on API routes (Q8), including the new endpoints and HTML routes with odd `Accept` headers. | T fuzz |

## U — Screens and routing

| Row | Requirement | Check |
|---|---|---|
| U1 | `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` are each directly reachable by URL (deep link / reload) and render their screen. Any other screen is reachable through the UI. | B |
| U2 | `/requests` and `/authorizations` are shared: `Accept: text/html` → the UI (200 HTML, no bearer token needed to fetch the page shell); without that header → the JSON API exactly as specified (auth rules, JSON errors). | T: both Accept variants, with and without token |
| U3 | All `data-testid` names are exactly as listed in the specification; extra elements are allowed. | B |
| U4 | Navigation is consistent across all required routes; signed-out users reaching a wallet screen are led to login; signed-in state survives navigation and reload. | B |

## L — Signup and login screens

| Row | Requirement | Check |
|---|---|---|
| L1 | `/signup`: inputs `signup-email`, `signup-password`, `signup-display-name`, button `signup-submit`; success signs the user in. | B/H |
| L2 | `/login`: `login-email`, `login-password`, `login-submit`; success signs the user in. | B/H |
| L3 | `auth-error` is present only when there is an error (bad login, `email_taken`, `handle_taken`, validation); absent otherwise. | B |
| L4 | `current-user` is visible on every screen when signed in; its text contains the display name. | B |
| L5 | `current-handle` text is exactly the caller's handle: no `@`, no surrounding words or whitespace. | B |
| L6 | `logout-button` signs out: `current-user` gone, wallet screens no longer show data. | B/H |

## Y — Balance, pay and request forms on `/`

| Row | Requirement | Check |
|---|---|---|
| Y1 | `wallet-balance`: text exactly the formatted `total`; attribute `data-amount="{minor units}"`. | B/H |
| Y2 | Formatted amount = decimal with exactly `minor_units` places, one space, currency code: `100.00 EUR`; `minor_units` 0 → no decimal point: `1200 JPY`; `minor_units` 3 → `1.500 BHD`; no sign, no thousands separators. Used for every "formatted amount" element. | B with EUR, JPY, BHD fixtures |
| Y3 | Pay form: `pay-handle`, `pay-amount` (decimal string), `pay-note`, `pay-visibility` (select; option values exactly `public` and `private`), `pay-submit`. | B/H |
| Y4 | Decimal input → minor units: with `minor_units` 2, `15.00` and `15` → 1500, `15.5` → 1550. Non-numeric input or more than `minor_units` decimal places (e.g. `15.005`; any decimal point content with `minor_units` 0) shows the form's error element and sends **no** request. Never rounds. Conversion is exact (no float arithmetic). | B: network log shows no POST |
| Y5 | `pay-error` shown when a payment is refused, including insufficient funds and unknown handle; absent after a success. | B/H |
| Y6 | Pay form keeps its values after success. Submitting again without changing any field sends no second payment: `wallet-balance` falls once, feed has one payment, `pay-error` absent (same idempotency key and body are reused, per §7). Rapid double-click also yields one payment. | B/H |
| Y7 | Changing any field makes the next submission a new payment (new key). | B/H |
| Y8 | Request form: `request-handle`, `request-amount`, `request-note`, `request-submit`; `request-error` when refused (unknown handle, self request, bad amount). Same decimal rules as the pay form. | B |
| Y9 | After any successful action the balance, feed and request lists on the same page show the new state without manual reload; the refresh happens only after the write succeeded. | B |

## F — Activity feed on `/`

| Row | Requirement | Check |
|---|---|---|
| F1 | `activity-list` container; its children are the items, newest first in the DOM. | B/H |
| F2 | `activity-item-{payment_id}` one per visible payment, with `data-visibility="public"` or `"private"`. | B/H |
| F3 | `activity-parties-{payment_id}` text contains both handles. | B/H |
| F4 | `activity-amount-{payment_id}` text exactly the formatted amount. | B/H |
| F5 | `activity-note-{payment_id}` text exactly the note (verbatim, HTML-escaped not interpreted — a note `<b>x</b>` shows as text; leading/trailing spaces and emoji intact in `textContent`); element present even when the note is empty. | B |
| F6 | `empty-activity` shown instead of the list when nothing is visible. | B/H |
| F7 | Feed shows exactly what `GET /activity` returns for the caller (private payments of others never rendered). Captures appear as ordinary payments; open authorisations never appear. | B |

## Q — Requests screen `/requests`

| Row | Requirement | Check |
|---|---|---|
| Q-1 | `incoming-list` and `outgoing-list` containers. | B/H |
| Q-2 | `request-item-{request_id}` one per request, `data-status="{status}"`. | B/H |
| Q-3 | `request-amount-{request_id}` text exactly the formatted amount. | B |
| Q-4 | `request-pay-{id}` and `request-decline-{id}` present only on a `pending` incoming request; `request-cancel-{id}` only on a `pending` outgoing request. | B/H |
| Q-5 | Pay, decline and cancel work from the screen and the list refreshes afterwards. | B/H |
| Q-6 | `request-error` shown when a pay, decline or cancel is refused (e.g. insufficient funds). | B/H |
| Q-7 | `empty-requests` shown when both lists are empty. | B/H |

## T — Split screen `/split`

| Row | Requirement | Check |
|---|---|---|
| T1 | `split-amount` (decimal, same rule as `pay-amount`), `split-handles` (comma-separated handles, in order), `split-note`, `split-submit`. | B/H |
| T2 | `split-preview` shows, before anything is posted, the shares the server would compute by stage-1 §9, with one `split-share-{handle}` per participant whose text is exactly the formatted share. No POST is sent to produce the preview. | B/H |
| T3 | Preview and submitted split have identical shares, including handle-order dependence of the extra unit. | B/H |
| T4 | `split-error` when the split is refused (unknown handle, duplicate, empty, bad amount). | B/H |
| T5 | Successful submit creates the requests (visible on `/requests` as outgoing). | B/H |

## R2 — Competing clients and uncertain outcomes

| Row | Requirement | Check |
|---|---|---|
| R2.1 | `wallet-refresh` button on `/` refreshes balance (total, available, held) and feed without clearing the pay form. | B/H |
| R2.2 | Latest refresh wins: a delayed earlier read never overwrites a later refresh, also when responses arrive out of order. | B: delay the first `/me`/`/activity` response via request interception |
| R2.3 | A payment refused because another client spent the balance: `pay-error` shown, balance and feed refreshed, all pay inputs preserved. | B |
| R2.4 | A request cancelled elsewhere while its pay button is visible: clicking pay shows `request-error` and the list refreshes so the stale pay button disappears. | B |
| R2.5 | Lost payment response (including after `POST /payments` committed): show `pay-uncertain` with non-empty text and **not** `pay-error`. The unchanged form stays retryable with the same key and same body. | B: abort the response via interception |
| R2.6 | A successful retry removes both `pay-error` and `pay-uncertain`, refreshes balance and feed, and money has moved exactly once. An unknown outcome is never presented as a confirmed rejection. | B |
| R2.7 | No background polling, live sync or cross-reload recovery is required; the same refresh rules apply to available and held amounts. | I |

## G — Existing clients after an upgrade

| Row | Requirement | Check |
|---|---|---|
| G1 | The stage-2 service accepts an unchanged export produced by the stage-1 service (`stage-1/` at the accepted revision): 204, all stage-1 state preserved as in stage-1 §10 (accounts, hashed-password login, tokens, balances, payments, requests, operators, idempotency records and responses). Absent stage-2 data defaults: no authorisations, `authorization_ttl_seconds` 600. | H (`previous_api`) + T: stage-1 container → export → stage-2 container import |
| G2 | A browser signed in before the import stays signed in afterwards (its token is still valid; no reload or new screen needed). | B |
| G3 | Pending requests from the imported state remain payable through the request screen. | B |
| G4 | A payment whose response was lost before the export stays retryable after import with the same body and key; the UI recovers the original payment (no double move) and refreshes the imported balance. The form contents and the pending retry identity survive the upgrade (import happens between browser requests; no reload). | B |
| G5 | Stage-2's own export → import round trip preserves everything stage-1 §10 lists **plus** authorisations (status, amounts, captures, `payment_ids`, `expires_at`), holds, `authorization_ttl_seconds`, and idempotency records of the two new paths. Replays after import return the original bodies. | T |
| G6 | Invalid import state still gives 422 without changing the destination (incl. malformed authorisation records). | T |

## W — Wallet totals and holds

| Row | Requirement | Check |
|---|---|---|
| W1 | `GET /me` → `{user_id, display_name, handle, balance, total, available, held, currency, minor_units}`; `balance == total` always; `held` = sum of remaining amounts of open, unexpired holds where the user is payer; `available = total − held`. | T/H |
| W2 | With no open holds `balance`, `total`, `available` agree, `held` is 0 and every stage-1 behaviour is unchanged. | H suite 1 |
| W3 | Sum of all wallet `total` values always equals the seeded total. A hold moves no money. | C |
| W4 | `available` is never negative, including transiently. Held funds cannot fund payments, request payments, new authorisations or settlement net debits. | C |
| W5 | Every `409 insufficient_funds` (`POST /payments`, `POST /requests/{id}/pay`, `POST /settlements`, `POST /authorizations`) is evaluated against `available`. For settlements: affordable iff every wallet's `total` after all transfers minus its `held` is ≥ 0. | T |
| W6 | `POST /payments` stays an immediate transfer with no intermediate hold; paying a request stays immediate; `POST /splits` unchanged. | T |
| W7 | Payments carry `authorization_id` (null unless created by a capture) beside `request_id` and `settlement_id`, in every response that contains a payment. | T |

## Z — Authorisations API

| Row | Requirement | Check |
|---|---|---|
| Z1 | `POST /authorizations {to_handle, amount, note?, visibility?}` with `Idempotency-Key`; caller is payer → 201 `{authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount: 0, remaining_amount, currency, note, visibility, status: "open", expires_at, payment_id: null, payment_ids: [], created_at}`. | T/H |
| Z2 | `expires_at` = `created_at` + `authorization_ttl_seconds`, RFC 3339 with offset. | T |
| Z3 | Errors: `available` below `amount` → 409 `insufficient_funds`; amount < 1, > 1000000000 or non-integer → 422; own handle → 422 `self_payment`; note > 200 or bad visibility → 422; unknown handle → 404. Defaults as `POST /payments`. | T |
| Z4 | Creating a hold reduces payer `available` by `amount`, raises `held`, leaves both `total`s unchanged. An open authorisation never appears in `GET /activity`. | T/H |
| Z5 | `POST /authorizations/{id}/capture {amount?, final?}` with `Idempotency-Key`; only the receiver → 201 with the created payment in exactly the `POST /payments` shape, `authorization_id` set, `request_id` null, `amount` = captured amount, `note` and `visibility` copied from the authorisation; it follows the ordinary feed rule. | T |
| Z6 | `amount` defaults to the remaining amount. Default (`final` omitted or `true`): authorisation becomes `captured`, `captured_amount` and `payment_id` set, uncaptured remainder released to the payer's `available` in the same step (capture 1500 of 2000 → 500 back). | T |
| Z7 | A second capture after a final capture → 409 `authorization_not_open`. | T |
| Z8 | Extended mode `final: false` with remainder left: status stays `open`, remainder stays held, further captures allowed up to the remainder. Capturing the whole remainder closes it (`captured`) even with `final: false`. A later final capture closes it and releases the rest. | T |
| Z9 | `captured_amount` is cumulative; `payment_id` is the latest capture; `payment_ids` lists every capture in order; `remaining_amount` is the amount still held (0 when closed) and is on every authorisation response. | T |
| Z10 | Capture errors: not `open` → 409 `authorization_not_open`; `expires_at` at or before now → 409 `authorization_expired`; amount above the **remaining** amount → 422 `capture_exceeds_authorization`; amount < 1 or non-integer → 422 `validation_failed`; caller not the receiver (incl. third parties) → 403; unknown → 404. `final` of the wrong JSON type → 400 `malformed_request`. | T |
| Z11 | Capture idempotency: replay must send the identical body; `{}` vs `{"amount": 2000}` (and `{"amount":700}` vs `{"amount":700,"final":true}`) are different JSON values → 409 `idempotency_key_reuse`. Each idempotent capture moves money once; replay returns the original payment even after the authorisation closed. | T + C |
| Z12 | Cumulative captures never exceed the authorised amount, also under concurrent captures with different keys. A closed hold cannot be captured again. | C |
| Z13 | Captures spend the money reserved for them: a capture succeeds even when the payer's `available` is 0. | T |
| Z14 | `POST /authorizations/{id}/void` (payer only, no idempotency key) → 200 authorisation with `status: "voided"`, hold released; repeat → 200 current state; `captured` or `expired` → 409 `authorization_not_open`; caller not the payer (incl. third parties) → 403; unknown → 404. | T |
| Z15 | Void and expiry may close a partially captured authorisation: only the remainder is released, capture records (`captured_amount`, `payment_ids`, payments) are preserved. | T |
| Z16 | Expiry by the clock: once `expires_at` ≤ now the authorisation is `expired` and holds nothing, on every read and write, with no request needed at the deadline: `GET /authorizations` shows `status: "expired"`, `GET /me` includes the released remainder in `available`, funds checks see it. | T with `authorization_ttl_seconds: 1` |
| Z17 | `GET /authorizations?direction=&status=&limit=&offset=` → `{authorizations, has_more}`; only authorisations where caller is payer or receiver; newest first by `created_at`; `direction` `outgoing` (payer) / `incoming` (receiver) / absent; `status` one of `open`, `captured`, `voided`, `expired` or absent; unknown value → 422; clock-expired matches `expired`, never `open`; `limit`/`offset`/`has_more` exactly as `GET /requests` (incl. digit-only rule). | T |
| Z18 | Seven idempotent write paths, each with the full stage-1 §7 rules independently (K1-K11 for `POST /authorizations` and `POST /authorizations/{id}/capture`). | T + C |
| Z19 | Authorising a request is out of scope (no such endpoint). | I |

## X2 — Fixture changes

| Row | Requirement | Check |
|---|---|---|
| X2.1 | Fixture `authorization_ttl_seconds`: default 600 when omitted; when supplied must be a positive integer, otherwise reset → 422 and nothing changes. Applies to every API-created authorisation. | T |
| X2.2 | Fixture `authorizations` array (may be omitted = empty): `{id, from_user_id, to_user_id, amount, note, visibility, status, expires_at}` with status `open`, `captured`, `voided` or `expired`; only `open` holds anything; seeded ones use their own absolute `expires_at`. | T/H |
| X2.3 | Seeded `balance` is `total`; `available` is derived by subtracting seeded open, unexpired holds. | T/H |
| X2.4 | Sum of seeded unexpired open holds greater than that user's `balance` → reset 422 `validation_failed`, nothing changes. | T |
| X2.5 | A seeded `open` authorisation whose `expires_at` is in the past is `expired` and holds nothing (and does not count in X2.4). | T |
| X2.6 | Seeded authorisations are capturable/voidable by the proper party and listed in `GET /authorizations`. | T |

## A2 — Authorisations screen and wallet numbers

| Row | Requirement | Check |
|---|---|---|
| A2.1 | `wallet-available`: formatted `available` with `data-amount`; presented as the headline number (visually the most prominent monetary value); `wallet-balance` (total) and `wallet-held` visibly secondary. | B + screenshot review |
| A2.2 | `wallet-held`: formatted `held` with `data-amount`; **absent** when `held` is zero. | B |
| A2.3 | Authorise form: `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit`, same input rules as the pay form; `authorize-error` when refused, including insufficient available funds. | B |
| A2.4 | `/authorizations`: `authorization-list` container, children newest first; `authorization-item-{id}` with `data-status="{status}"`; `authorization-amount-{id}` exactly the formatted authorised amount. | B |
| A2.5 | `authorization-captured-{id}`: formatted captured amount, present only when status is `captured`. | B |
| A2.6 | `authorization-expires-{id}`: text is the RFC 3339 `expires_at`. | B |
| A2.7 | `authorization-capture-amount-{id}` (decimal input pre-filled with the remaining amount) and `authorization-capture-{id}` present only on an incoming `open` authorisation; `authorization-void-{id}` only on an outgoing `open` one. | B |
| A2.8 | Capture and void work from the screen and the list and wallet numbers refresh; `authorization-error` when a capture or void is refused. | B |
| A2.9 | `empty-authorizations` shown when the list is empty. | B |
| A2.10 | UI reflects seeded and newly created holds; available funds are shown as the spending balance immediately after a reset with open holds. | B |

## V — Product and visual quality

| Row | Requirement | Check |
|---|---|---|
| V1 | Coherent, presentation-ready consumer finance product with a calm, trustworthy character: one consistent system for typography, spacing, colour, controls and feedback; primary actions easy to identify. | Screenshot review of every route, signed in and out |
| V2 | Payments, requests, splits and authorisations are easy to scan; status, direction (sent/received), privacy and money movement are understandable without reading raw API data. People, amounts and timestamps formatted for people; technical ids shown only where they help. (Exact-text testid elements keep their exact text; human formatting goes in sibling elements.) | Screenshot review |
| V3 | Available, held, pending, loading, successful, refused and uncertain states are visually distinct. | B + screenshots of each state |
| V4 | Usable at 375 CSS px and at desktop widths with no horizontal page scrolling (`scrollWidth <= clientWidth` on every route, including long notes/handles). | B at 375 and 1280 |
| V5 | Inputs have visible labels; keyboard focus is apparent; text and controls have sufficient contrast (WCAG AA 4.5:1 for text). Forms are operable by keyboard. | B + contrast computation |
| V6 | Considered empty, loading and error states on every screen. | B |

## C2 — Concurrency

| Row | Requirement | Check |
|---|---|---|
| C2.1 | Concurrent requests produce results equal to some serial order, and W1-W4, Z12 hold at every read: mixed 50-way load of payments, authorisations, captures (final and non-final), voids, settlements, expiries, reads and exports. | C |
| C2.2 | Capture vs void vs expiry races on one authorisation yield exactly one consistent outcome; capture vs capture never over-captures. | C |

## Decisions recorded by the Architect

| # | Choice | Reason |
|---|---|---|
| S2-1 | Check order on capture mirrors `/requests/{id}/pay` from stage 1 (Q1, Q2, Q6): auth → key present/length → body is a JSON object → claimed-key resolution → unknown authorisation 404 → caller not receiver 403 → field validation (`amount`, `final`) → state (`authorization_not_open` for captured/voided, `authorization_expired` when `expires_at` ≤ now) → `capture_exceeds_authorization`. Void: 404 → 403 → state. | Spec gives the cases but no order; permission before state follows Q6 and "For an existing authorization, capture and void return 403 when the caller is not the permitted party". |
| S2-2 | Capture on an authorisation that expired by the clock (or was seeded `expired`) → 409 `authorization_expired`; on `captured` or `voided` → 409 `authorization_not_open`. Void on an expired one → 409 `authorization_not_open` (as the spec states). | Two distinct rows in the capture table; expiry row is the more specific one for expired holds. |
| S2-3 | Seeded authorisations: `captured_amount` = fixture `captured_amount` if present, else `amount` when status is `captured`, else 0; `payment_id` = fixture value if present else null; `payment_ids` = `[payment_id]` or `[]`; `created_at` = fixture value if present, else assigned at reset in fixture order. `remaining_amount` = `amount − captured_amount` when open and unexpired, else 0. | Fixture format lists no such fields; responses still need valid values. |
| S2-4 | HTML is served when the `Accept` header contains `text/html`; otherwise JSON. `/`, `/split`, `/signup`, `/login` are UI-only routes and serve the UI for browsers. | "Return the UI for `Accept: text/html`; API requests without that header receive JSON." |
| S2-5 | The browser keeps its session token and the pending pay retry identity (key + body) in page memory/localStorage; no server session cookies are needed. | G2/G4 need the token and retry identity to survive an import without reload. |
| S2-6 | Reset must stay within 10 s for fixtures up to 5000 users: keep per-user salts and a real password-hashing function but tune its cost; hash parameters are stored per hash so stage-1 exports (older parameters) still log in. | Verifier risk note on stage 1 (≈7.4 ms per user); stage-1 §2 gives reset 10 s and states no fixture size. |
| S2-7 | "New fields do not change idempotency body equality": equality stays raw JSON-value equality of the body sent, so adding `final` to a body makes it a different body. | Stage-1 §7 "Same body means the same JSON value after parsing". |
