# Acceptance map: stage 2 (Pocketful: wallet screens and payment authorizations)

Source: `dark-factory-wearedevs/pocketful/spec/stage-2.md` (sha256 699fcdd4…317af12) on top of
`stage-1.md`. Target folder: `stage-2/`, created as a copy of the accepted `stage-1/` (revision
43ecb3c) and extended. "Harness" = supplied checks (`harness run --track pocketful --stage 2`,
which runs suites 1 and 2 against `stage-2/`; they are about a third of the graded stage-2 suite).
"Own" = checks the Implementer and the Verifier each write from the specification. "Browser" = an
own check driving a real browser (Playwright/Chromium) against the running container.

## K. Carry-forward and delivery

| Row | Requirement | Check |
|---|---|---|
| K1 | `stage-2/` is `stage-1/` copied forward and extended: complete on its own (source, `Dockerfile`, `RUN.md`), no nested `.git`, builds from a clean clone. `stage-1/` is not modified. | Own: `git diff 43ecb3c -- stage-1` empty; clean build |
| K2 | Every row of `acceptance/stage-1.md` (incl. clarifications C-1..C-5) still holds for `stage-2/`, with only the changes this map states (K5, Q-rows). | Harness suite 1 on stage-2; Own: the whole stage-1 list re-run against stage-2 |
| K3 | Runtime limits unchanged: 2 vCPU, 2 GiB, healthy ≤ 60 s, 50 in flight, 5 s per request (10 s test-control calls), no outbound network at run time. All UI assets (scripts, styles, fonts, icons) are inside the image; the pages load nothing from another origin. | Harness isolated; Browser: record every request, none leaves the origin |
| K4 | Nothing from stage 3 or 4 is implemented. | Harness stage-3 probe on `stage-2/` must not be a full pass; route review |
| K5 | Stage-1 response conventions hold for the API; UI routes answer `text/html; charset=utf-8`; assets carry their proper types. No 5xx anywhere, including UI routes and assets with odd methods/paths. | Own |

## U. UI routes and shared behaviour

| Row | Requirement | Check |
|---|---|---|
| U1 | Screens reachable by URL: `/` (balance, pay form, request form, activity feed), `/requests`, `/split`, `/signup`, `/login`, `/authorizations`. Every other screen is reachable through the UI. | Harness; Browser |
| U2 | `/requests` and `/authorizations` are shared: `GET` with an `Accept` header containing `text/html` → the UI (no token needed); otherwise JSON API exactly as specified (401 without token; `Accept` absent, `*/*` or `application/json` → JSON). | Own: curl with each Accept form |
| U3 | Consistent navigation on all routes; `current-user` (text contains the display name), `current-handle` (text exactly the handle, no `@`, no other words) and `logout-button` are visible on every screen when signed in. | Harness; Browser on all six routes |
| U4 | After any successful action the balance, feed and request/authorization lists on the same page show the new state without manual reload; the refresh happens only after the write succeeded. No polling/live update required. | Harness; Browser |
| U5 | Every listed `data-testid` exists exactly as named, found by `[data-testid='…']` alone; ids interpolated into test ids are the API ids verbatim (also for fixture ids with unusual characters). User text (notes, names, handles) is rendered as text, never as markup. | Browser: note `<img src=x onerror=…>` renders literally |

## V. Product and visual quality (§ Product and visual direction)

| Row | Requirement | Check |
|---|---|---|
| V1 | Coherent, calm, presentation-ready consumer-finance look: one visual system for typography, spacing, colour, controls, feedback; primary actions easy to identify. | Browser screenshots of all six routes at 375 px and 1280 px, reviewed |
| V2 | Available funds are the clearest monetary value once holds exist; total and held are visibly secondary. | Screenshot review with a seeded hold |
| V3 | Payments, requests, splits, authorisations are easy to scan; status, direction (sent/received, incoming/outgoing), privacy and money movement are understandable without raw API data; people, amounts, timestamps formatted for people; technical ids only where they help. | Screenshot review |
| V4 | Available, held, pending, loading, successful, refused and uncertain states are visually distinct. | Browser: force each state, screenshot |
| V5 | Usable at 375 CSS px and at desktop widths with no horizontal page scrolling (`scrollWidth <= clientWidth` on every route, with long notes/handles/amounts). | Browser at 375, 768, 1280, 1920 |
| V6 | Inputs have visible labels; keyboard focus is apparent; text and controls have sufficient contrast (WCAG AA: 4.5:1 text, 3:1 controls); all flows work by keyboard. | Browser: label association, focus ring, computed contrast |
| V7 | Considered empty, loading and error states on every screen. | Browser |

## W. Signup and login

| Row | Requirement | Check |
|---|---|---|
| W1 | `/signup`: `signup-email`, `signup-password`, `signup-display-name`, `signup-submit`; success signs the user in (then `current-user`, `current-handle` show). | Harness |
| W2 | `/login`: `login-email`, `login-password`, `login-submit`; success shows `current-user`. | Harness |
| W3 | `auth-error` present only when there is an error (bad login, taken email/handle, short password, bad email); absent otherwise and removed on the next attempt/success. | Harness; Browser |
| W4 | `logout-button` signs out: `current-user` leaves the DOM; protected screens then lead to login. | Harness; Browser |
| W5 | Sign-in persists across navigations between routes (full page loads) in the same browser context. | Harness |

## X. Balance and pay on `/`

| Row | Requirement | Check |
|---|---|---|
| X1 | `wallet-balance`: text exactly the formatted `total`, attribute `data-amount` = minor units. | Harness |
| X2 | Formatted amount everywhere: decimal with exactly `minor_units` places, one space, currency code (`100.00 EUR`, `0.05 EUR`, `1.234 BHD`); `minor_units` 0 → no decimal point (`1200 JPY`); no sign, no grouping separators. | Harness; Browser with EUR/JPY/BHD, large values up to 2^53 exact |
| X3 | `pay-handle`, `pay-amount` (decimal string), `pay-note`, `pay-visibility` (option values exactly `public` and `private`), `pay-submit`. | Harness |
| X4 | Decimal input rule: `15.00` and `15` → 1500, `15.5` → 1550 (minor_units 2); non-numeric input or more than `minor_units` decimal places (`15.005`; `1.5` in JPY) shows the form's error element and sends NO request; never rounded; conversion is exact (string arithmetic, no floats: `0.29` → 29, `1234567.89` → 123456789). | Harness; Browser with request log |
| X5 | `pay-error` shown when the payment is refused (insufficient funds, unknown handle, self payment, validation); absent after success. | Harness; Browser |
| X6 | The pay form keeps its values after success. Submitting again without changing a field sends no new payment: balance falls once, feed has one payment, `pay-error` absent (same key and body → replay). Changing a field makes the next submission a new payment (new key). | Harness; Browser incl. double-click and rapid repeated clicks |
| X7 | Request form on `/`: `request-handle`, `request-amount`, `request-note`, `request-submit`; `request-error` when refused (unknown handle, self request, bad amount). Same decimal rule. | Browser |

## Y. Activity feed on `/`

| Row | Requirement | Check |
|---|---|---|
| Y1 | `activity-list` container; children newest first in the DOM; one `activity-item-{payment_id}` per visible payment (feed contract of stage 1) with `data-visibility` = `public`/`private`. | Harness |
| Y2 | `activity-parties-{id}` text contains both handles; `activity-amount-{id}` text exactly the formatted amount; `activity-note-{id}` text exactly the note and present even when empty. | Harness; Browser with unicode/whitespace notes |
| Y3 | `empty-activity` shown instead of the list when nothing is visible. | Harness |
| Y4 | Captures and settlement members appear as ordinary payments under the feed rule; open authorisations never appear. | Browser |

## Z. Requests screen `/requests`

| Row | Requirement | Check |
|---|---|---|
| Z1 | `incoming-list`, `outgoing-list` containers; `request-item-{id}` with `data-status`; `request-amount-{id}` exactly the formatted amount (also `0.00 EUR` for a zero share). | Harness |
| Z2 | `request-pay-{id}` and `request-decline-{id}` only on a pending incoming request; `request-cancel-{id}` only on a pending outgoing request. | Harness |
| Z3 | Pay/decline/cancel update the item's `data-status` without reload; a refused action shows `request-error` and refreshes the lists. | Harness; Browser |
| Z4 | `empty-requests` shown when both lists are empty. | Harness |

## S. Split screen `/split`

| Row | Requirement | Check |
|---|---|---|
| S1 | `split-amount` (decimal rule X4), `split-handles` (comma-separated, in order; surrounding spaces tolerated), `split-note`, `split-submit`. | Harness |
| S2 | `split-preview` shows the shares the server would compute (stage-1 §9) before anything is posted: one `split-share-{handle}` per participant, text exactly the formatted share; preview and submitted split have identical shares (incl. caller omitted, zero shares, order changes). | Harness; Browser comparing preview to the POST /splits response |
| S3 | Submit creates the split (requests appear for the others); `split-error` when refused (unknown handle, duplicate, empty, bad amount). | Harness |

## C. Competing clients and uncertain outcomes

| Row | Requirement | Check |
|---|---|---|
| C1 | `wallet-refresh` button on `/` refreshes balance (total, available, held) and feed without clearing the pay form. | Harness |
| C2 | Latest refresh wins: a delayed earlier read never overwrites a later refresh, also when responses arrive out of order. | Browser: delay the first `/me` + `/activity` responses, click refresh twice, release in reverse order |
| C3 | A payment refused because another client spent the balance shows `pay-error`, refreshes balance and feed, preserves all pay inputs. | Browser |
| C4 | A request cancelled elsewhere while its pay button is visible: paying shows `request-error` and refreshes the list so the stale pay button disappears. | Browser |
| C5 | Lost payment response (network failure after or before commit, timeout, unreadable response): show `pay-uncertain` (non-empty text), NOT `pay-error`. The unchanged form stays retryable with the same key and body; a successful retry removes `pay-uncertain` and `pay-error`, refreshes balance and feed, and money has moved exactly once. Unknown outcomes are never shown as rejections. | Browser: abort the response of `POST /payments` after forwarding it, then retry |

## M. Existing clients after an upgrade

| Row | Requirement | Check |
|---|---|---|
| M1 | Stage-2 `POST /_test/import` accepts an unchanged export of this team's stage-1 service (accepted revision) and its own exports; missing stage-2 parts default (no authorisations, ttl 600). Stage-1 I-rows hold for stage-2 exports incl. authorisations, captures and the two new idempotent paths. | Harness (`previous_api`); Own: stage-1 container → export → stage-2 container |
| M2 | A browser signed in before the export/import upgrade stays signed in afterwards (tokens in the export keep working; the UI keeps no server-side session that import would drop). | Browser: page API calls routed to a stage-1 container, export, import into stage-2, unroute, continue without reload |
| M3 | Existing pending requests remain payable through the request screen after import. | Browser |
| M4 | A payment whose response was lost before export stays retryable after import with the same key and body, without page reload: the UI recovers the original payment (200 replay, same `payment_id`), clears uncertainty, and shows the imported balance. Form and pending retry identity survive the upgrade. | Browser |

## P. Authorisation invariants

| Row | Requirement | Check |
|---|---|---|
| P1 | Sum of all wallet `total` always equals the seeded total. A hold moves no money. | Own: conservation after bursts |
| P2 | `available = total − held` is never negative at any read. Held funds cannot fund payments, request pays, new authorisations or settlement net debits; captures spend their own reserved money. | Own: 50-way bursts mixing payments, authorisations, captures, settlements |
| P3 | Cumulative captures never exceed the authorised amount; each idempotent capture moves money once; a closed hold cannot be captured again. | Own: 50 concurrent captures (distinct keys / same key) |
| P4 | Concurrent requests give the same result as some serial order; every read is consistent (`balance == total`, `held` = sum of open unexpired remainders). | Own |

## Q. API changes and authorisation API

| Row | Requirement | Check |
|---|---|---|
| Q1 | `GET /me` adds `total`, `available`, `held`; `balance == total` always; with no open holds all three agree and `held` is 0. | Harness |
| Q2 | `POST /payments` stays an immediate transfer (no hold, no capture). Every stage-1 `409 insufficient_funds` (payments, request pay, settlements) is evaluated against `available`. `POST /splits` unchanged. | Own |
| Q3 | Fixture: `authorization_ttl_seconds` (default 600; if supplied a positive integer, else 422) and `authorizations[]` (`id, from_user_id, to_user_id, amount, note, visibility, status, expires_at`), omitted = empty. Seeded `status` ∈ open/captured/voided/expired; only `open` (and unexpired) holds. Seeded `balance` is `total`; `available` derived. Sum of seeded unexpired open holds > that user's balance → 422, nothing changes. Invalid authorisation records (unknown user, bad status, bad `expires_at`, bad amount, duplicate id) → 422. | Harness (partly); Own |
| Q4 | Expiry is by the clock: an authorisation whose `expires_at` ≤ now is `expired` and holds nothing, in every read and write even when no request happened at the deadline (`GET /authorizations` shows `expired`, `/me` `available` includes the released remainder, capture refused). | Own: ttl 1–2 s, then read without any intermediate request |
| Q5 | `POST /authorizations` (key required, caller is payer) `{to_handle, amount, note?, visibility?}` → 201 with `authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount:0, remaining_amount, currency, note, visibility, status:"open", expires_at, payment_id:null, payment_ids:[], created_at`; `expires_at = created_at + ttl` exactly. | Harness; Own |
| Q6 | Authorisation errors: `available` < amount → 409 `insufficient_funds`; amount <1, >1000000000, non-integer → 422; own handle → 422 `self_payment`; note > 200 or bad visibility → 422; unknown handle → 404. Authorising exactly `available` succeeds. | Own |
| Q7 | An open authorisation is not a feed item and never appears in `GET /activity`. | Own |
| Q8 | `POST /authorizations/{id}/capture` (key required; only the receiver): body `{amount?, final?}`; `amount` defaults to the remaining amount; `final` boolean default true. → 201 with the created payment in exactly the `POST /payments` shape, `authorization_id` set, `request_id: null`, `settlement_id: null`; amount = captured amount; note and visibility copied from the authorisation; appears in the feed by the ordinary rule. All other payments carry `authorization_id: null`. | Own |
| Q9 | Default (final) capture: authorisation becomes `captured`, has `captured_amount`, `payment_id`; the uncaptured remainder is released to the payer's `available` in the same step. A second capture → 409 `authorization_not_open`. | Own |
| Q10 | Extended mode `final:false`: with a remainder left the status stays `open` and the remainder stays held; further captures allowed up to the remainder; capturing the whole remainder closes it (`captured`) even with `final:false`; a later final capture closes and releases. `captured_amount` cumulative; `payment_id` = latest capture; `payment_ids` = every capture in order; `remaining_amount` = amount still held (0 when closed) on every authorisation response. | Own |
| Q11 | Capture errors: not open → 409 `authorization_not_open`; `expires_at` ≤ now → 409 `authorization_expired`; amount above the remaining amount → 422 `capture_exceeds_authorization`; amount < 1 or not an integer → 422 `validation_failed`; caller not the receiver (payer or third party) → 403 `forbidden`; unknown → 404. | Own |
| Q12 | Capture idempotency: replay of the identical body → 200 original payment, no second movement; `{}` vs `{"amount":2000}` (or with/without `final`) on one key → 409 `idempotency_key_reuse`; all stage-1 F-rows apply to both new paths independently (seven paths in total). | Own |
| Q13 | `POST /authorizations/{id}/void`: only the payer, no key; 200 with the authorisation `status:"voided"`, hold released; already voided → 200 current state; `captured` or `expired` → 409 `authorization_not_open`; caller not the payer (receiver or third party) → 403; unknown → 404. Void (and expiry) of a partially captured authorisation releases only the remainder and keeps `captured_amount`, `payment_id`, `payment_ids`. | Own |
| Q14 | `GET /authorizations`: only those where the caller is payer or receiver; newest first by `created_at`; `direction` outgoing (payer) / incoming (receiver) / absent; `status` one of four or absent (clock-expired matches `expired`, never `open`); unknown values → 422; `limit`/`offset`/`has_more` exactly as `GET /requests`. `{authorizations:[...], has_more}`. | Own |
| Q15 | Races: capture vs void vs expiry vs second capture → exactly one consistent outcome; totals conserved; never negative available. | Own |
| Q16 | Export/import/reset preserve authorisations (status, captured amounts, capture payments, `expires_at`), ttl, and idempotency records of the two new paths; reset clears them. | Own |

## R. Authorisation UI

| Row | Requirement | Check |
|---|---|---|
| R1 | Wallet: `wallet-balance` = formatted `total` (+`data-amount`); `wallet-available` = formatted `available` with `data-amount`, presented as the headline number; `wallet-held` = formatted `held` with `data-amount`, absent when `held` is zero. Correct immediately after reset with seeded open holds; refresh rules C1-C3 apply to all three. | Harness-style Browser |
| R2 | Authorise form: `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit`, same input rules as the pay form (X4, X6); `authorize-error` when refused incl. insufficient available funds. | Browser |
| R3 | `/authorizations`: `authorization-list` (children newest first), `authorization-item-{id}` with `data-status` (clock-expired shows `expired`), `authorization-amount-{id}` exactly the formatted authorised amount, `authorization-captured-{id}` formatted captured amount present only when status is `captured`, `authorization-expires-{id}` text is the RFC 3339 `expires_at` as the API returns it. | Browser |
| R4 | `authorization-capture-amount-{id}` (decimal input pre-filled with the remaining amount, e.g. `20.00`) and `authorization-capture-{id}` only on an incoming open authorisation; `authorization-void-{id}` only on an outgoing open one; `authorization-error` when a capture or void is refused; `empty-authorizations` when the list is empty. | Browser |
| R5 | Capturing/voiding/authorising through the UI updates list and wallet numbers without reload; seeded and newly created holds are reflected. | Browser |

## Decisions on points the specification leaves open (change only via the Architect)

- E-1 UI architecture: the pages are static shells plus scripts served by the stage-2 service; all data and actions go through the documented JSON API of the same origin with `Authorization: Bearer <token>` (relative URLs, the documented paths and methods, `Accept: application/json`, `Idempotency-Key` on the seven write paths). The token from `/auth/login` / `/auth/signup` is kept in browser storage (`localStorage`) so it survives navigation; there is no server-side browser session, no cookie-only auth and no private UI-only endpoint for data. Reason: rows M2/M4 require a signed-in page, its form and its pending key to survive an import of a stage-1 export without reload, and graded browser checks can only intercept or lose documented API calls. Logout discards the token in the browser (no new API endpoint).
- E-2 Content negotiation (U2): HTML iff the request is `GET` and its `Accept` header contains `text/html`; UI-only routes `/`, `/split`, `/signup`, `/login` always answer HTML to GET. HTML shells need no token; a signed-out visitor to a protected screen is taken to `/login`. `/login` and `/signup` render their forms even when signed in (with `current-user` shown).
- E-3 Idempotency keys in the UI: every form/action keeps one key for its current values. A key is minted when the values first differ from those the last key was minted for; submitting unchanged values reuses key and body (replay). Editing to another value and back counts as a change. This applies to pay, request, authorise, split, request-pay buttons and capture. Keys live in page memory (no recovery across reloads required).
- E-4 Outcome classes in the UI: a 4xx with the error body is a confirmed refusal (`*-error`); a network failure, timeout, aborted or unparseable response, or 5xx on `POST /payments` is uncertain (`pay-uncertain`). While uncertain, the form stays filled and the submit button retries with the same key/body.
- E-5 Decimal input grammar: after trimming, `^[0-9]+(\.[0-9]{1,minor_units})?$` (no sign, no exponent, no grouping; with `minor_units` 0 no decimal point). Anything else, or an empty field, shows the form's error and sends nothing. A syntactically valid amount the server refuses (0, above the maximum) shows the form's error from the server's answer.
- E-6 Lists in the UI load all pages (`limit=200` until `has_more` is false) so that every visible payment/request/authorisation has its element.
- E-7 The authorise form and the three wallet numbers are on `/` and also on `/authorizations` (the specification names the test ids but not the page for the form).
- E-8 Authorisation object fields in every response: `authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount, remaining_amount, currency, note, visibility, status, expires_at, payment_id, payment_ids, created_at`. Every payment object adds `authorization_id` (null unless created by a capture), also payments imported from stage 1.
- E-9 Capture/void check order (extends D-1): auth 401 → key present/length → body parse → claimed key (replay/409) → field validation (`amount` not an integer or < 1 → 422 `validation_failed`; `final` not a boolean → 400 `malformed_request`) → 404 → 403 → status: effective `expired` → 409 `authorization_expired`; `captured`/`voided` → 409 `authorization_not_open` → amount above the remainder (any magnitude) → 422 `capture_exceeds_authorization`. Void: 404 → 403 → already voided 200 → `captured`/`expired` → 409 `authorization_not_open`.
- E-10 "Idempotency body equality" stays whole-body JSON value equality (D-7): `{}`, `{"amount":2000}`, `{"final":true}` are three different bodies.
- E-11 Seeded authorisations: `expires_at` must be RFC 3339 with offset (`Z` accepted) and is returned exactly as given; `created_at` is assigned at reset in fixture order (D-9); a seeded `captured` one has `captured_amount = amount`, `remaining_amount 0`, `payment_id null`, `payment_ids []` (no payment is invented; balances are already final); others have `captured_amount 0`. A seeded `open` one whose `expires_at` is past is `expired` and is not counted in the over-hold check. `from_user_id == to_user_id`, amount outside 1..1000000000 → 422.
- E-12 Settlement affordability with holds: for every wallet, `total` after all transfers minus `held` must be ≥ 0.
- E-13 `authorization_ttl_seconds` so large that `expires_at` cannot be represented → 422 on reset.
- E-14 Expiry is evaluated lazily against the clock on every read and write (no timer needed); the stored status may be materialised at any time provided every response is as if it had been at the deadline.
