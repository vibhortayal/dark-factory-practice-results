@vibhor15/nightshift-implementer
Rows: all stage-2 rows + stage-1 regression · Revision: stage-1 accepted at 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb; base = head of main · Files: stage-2/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-2 HANDOFF PART 4/9 — ACCEPTANCE MAP acceptance/stage-2.md (verbatim)

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
