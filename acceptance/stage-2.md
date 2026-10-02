# Acceptance map: stage 2

Sources: `pocketful/spec/stage-2.md` (called "S2" below) and `pocketful/spec/stage-1.md`
(§ numbers) in the kickoff checkout. Target folder: `stage-2/`, created by copying the accepted
`stage-1/` (revision 77409dda43334b784ca1125d2d990ba51478abf6) and extending that code.
Every row of `acceptance/stage-1.md` (A1..K10, including A12, A13) continues to apply to
`stage-2/` except where a row here says it changes; row L1 is replaced by Z1.
"Check": `H` = supplied harness run, `P` = the Verifier's own HTTP probe, `B` = the Verifier's
own browser probe (Playwright, Chromium), `I` = inspection of source, image or screenshots.
Rows marked **[D]** are the Architect's resolution of an open choice, with the reason.

## M. Carry-over and upgrade

| Row | Requirement | Check |
|---|---|---|
| M1 | `stage-2/` is a complete, buildable folder of its own (source, `Dockerfile`, `RUN.md`), copied from `stage-1/` and extended; `stage-1/` itself is not modified. No `.git`, symlink or submodule inside. All UI assets (scripts, styles, fonts, icons) are in the image; nothing is fetched from another origin at run time. | I; H isolated; B with the network otherwise blocked |
| M2 | Every stage-1 row still holds on `stage-2/`: the stage-1 suite passes and the stage-1 probes pass, with the changes stated in N-rows (`/me` fields, `authorization_id` on payments, funds judged on `available`). | H, P |
| M3 | A stage-2 service accepts an unchanged export produced by the stage-1 service (`format_version: 1`, no authorisations, no lifetime setting): accounts, password login, bearer tokens, balances, payments, requests, settlements, operator grants and idempotency records are preserved; `authorization_ttl_seconds` is 600; `held` is 0. The stage-2 export keeps `track: "pocketful"`, `format_version: 1`; the service tells the two state layouts apart inside `state`. | H, P: export from a stage-1 container, import into stage-2 |
| M4 | Stage-2 export/import (§10) also preserves authorisations with status, `expires_at`, captured amounts, capture payments in order, the lifetime setting, and the idempotency records of all seven write paths. Import of a tampered or inconsistent state is 422 with the destination unchanged. | P |
| M5 | Carry-over correction from the stage-1 verdict: a body that is not valid JSON is 400 `malformed_request` whatever its nesting depth; only a body that is valid JSON but deeper than the service handles is 422. No input makes the parser crash or 5xx. | P |
| M6 | **[D]** Timestamps the service generates from stage 2 on carry millisecond precision (`2026-09-24T13:10:00.123+00:00`), still RFC 3339 with an explicit offset. Reason: `expires_at` must equal `created_at` plus the lifetime exactly, and expiry is judged "at or before now"; with whole seconds a 1-second hold could expire up to a second early. Imported and seeded timestamps are returned exactly as they were given. Ordering "newest first" stays correct across both precisions. | P |

## N. Holds: model and existing API (S2 "Authorizations and captures", "Model", "GET /me")

| Row | Requirement | Check |
|---|---|---|
| N1 | Invariant 1: the sum of all wallet `total` values equals the seeded total at every read. A hold moves no money; payments, settlements and captures move it. | P after every burst |
| N2 | Invariant 2: `available = total − held` is never negative, at any read. Held funds cannot fund a payment, a request payment, an authorisation or a settlement net debit. A capture spends the money reserved for it. | P: bursts mixing payments, authorisations, captures, settlements over one wallet |
| N3 | Invariant 3: cumulative captures never exceed the authorised amount; each idempotent capture moves money once; a closed hold cannot be captured again. | P: 50-way capture bursts with distinct and with identical keys |
| N4 | `GET /me` returns `user_id, display_name, handle, balance, total, available, held, currency, minor_units`. `balance` equals `total` always. `held` is the sum of the remaining amounts of the caller's open, unexpired outgoing authorisations. With no open holds `balance = total = available` and `held = 0`, and every stage-1 behaviour is unchanged. | H, P |
| N5 | `POST /payments` stays an immediate transfer: no intermediate hold, no capture step. | P |
| N6 | Every stage-1 `409 insufficient_funds` (`POST /payments`, `POST /requests/{id}/pay`, `POST /settlements`) is now judged against `available`. For a settlement: affordable iff every wallet's `available` after all its transfers is >= 0. | P |
| N7 | Paying a request stays immediate; requests cannot be authorised. `POST /splits` is unchanged. | P |
| N8 | Every payment object, on every endpoint and in every stored replay created from stage 2 on, carries `authorization_id` (null unless created by a capture) next to `request_id` and `settlement_id`. A replay of a response recorded before an upgrade returns the body as originally recorded. | P |
| N9 | Fixture: `authorization_ttl_seconds` optional, default 600; if supplied it must be a positive integer, else reset is 422 and changes nothing. It applies to every authorisation created through the API. | P: omitted, 1, 0, -5, 1.5, "600", true |
| N10 | Fixture: `authorizations` optional, default empty; entries `id, from_user_id, to_user_id, amount, note, visibility, status, expires_at`; `status` is `open`, `captured`, `voided` or `expired`; only `open` holds anything. Seeded `balance` is still `total`; `available` is derived by subtracting seeded unexpired open holds. **[D]** An entry naming an unknown user, a status outside the four, an invalid amount or an unparseable `expires_at` makes reset 422. Seeded `id` and `expires_at` are returned exactly as given. `captured_amount` is taken from the entry if present, else it is `amount` for a `captured` entry and 0 otherwise; `payment_id` null and `payment_ids` empty unless given; `created_at` from the entry if present, else reset time. Reason: the fixture format shows no capture fields, and reset must be all or nothing. | H, P |
| N11 | A sum of seeded unexpired open holds above that user's `balance` is a reset error: 422 `validation_failed`, nothing changes. Expired or closed seeded holds do not count. | P |
| N12 | Expiry is by the clock: an authorisation whose `expires_at` is at or before now is `expired` and holds nothing, whether or not any request happened at the deadline. `GET /authorizations` shows `status: "expired"` and `remaining_amount: 0`; `GET /me` includes the released remainder in `available`; the released funds can be spent at once. A seeded `open` entry whose `expires_at` is already past is `expired`. | P: lifetime of 1 to 2 s, then read without any write in between |
| N13 | An open authorisation is not a feed item and never appears in `GET /activity`; capture payments appear by the ordinary visibility rule. | P |
| N14 | Seven idempotent write paths: stage 1's five plus `POST /authorizations` and `POST /authorizations/{id}/capture`; all §7 rules (scope by user, method, path; replay 200; reuse 409; failed keys free; claimed key resolved before validation; concurrent identical requests one 201) hold independently on each. Void needs no key. | P |
| N15 | Concurrent requests give the same results as some one-at-a-time order, and every row here holds at every read. | P at 50 in flight |

## O. Authorisation API (S2 "API")

| Row | Requirement | Check |
|---|---|---|
| O1 | `POST /authorizations` `{to_handle, amount, note?, visibility?}`: caller is the payer; 201 with `authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount (0), remaining_amount (= amount), currency, note, visibility, status "open", expires_at, payment_id (null), payment_ids ([]), created_at`. `expires_at` = `created_at` + `authorization_ttl_seconds` exactly. Defaults for `note` and `visibility` as on payments. | H, P |
| O2 | Errors: `available` below `amount` -> 409 `insufficient_funds`; amount rules C3 -> 422; own handle -> 422 `self_payment`; note over 200 or bad visibility -> 422; unknown handle -> 404. Precedence as row E5. | P |
| O3 | `POST /authorizations/{id}/capture` body `{amount?, final?}`: only the receiver; 201 with the created payment in exactly the `POST /payments` shape, `authorization_id` set, `request_id: null`, `settlement_id: null`, `amount` = captured amount, `note` and `visibility` copied from the authorisation, sender = the payer, receiver = the caller. Money moves payer -> receiver atomically with the hold change. | P |
| O4 | `amount` omitted = the remaining amount. `final` is a boolean, default `true`. Final capture: status `captured`, the uncaptured remainder returns to the payer's `available` in the same step. `final: false` with a remainder left: status stays `open`, the remainder stays held, further captures allowed up to it. Capturing the whole remainder closes it (`captured`) even with `final: false`. | P |
| O5 | Every authorisation response carries `captured_amount` (cumulative), `remaining_amount` (still held; 0 when closed), `payment_id` (latest capture or null) and `payment_ids` (every capture, in order). | P |
| O6 | Capture errors: unknown -> 404; caller is not the receiver (payer or third party alike) -> 403 `forbidden`; not open (`captured`, `voided`) -> 409 `authorization_not_open`; `expires_at` at or before now, or seeded `expired` -> 409 `authorization_expired`; `amount` above the remaining amount -> 422 `capture_exceeds_authorization`; `amount` below 1 or not an integer (C3 forms) -> 422 `validation_failed`. **[D]** `final` of a non-boolean type -> 400 `malformed_request` (§5 general rule). **[D]** Precedence: field validation (400/422) -> 404 -> 403 -> closed by capture or void (`authorization_not_open`) -> expired (`authorization_expired`) -> `capture_exceeds_authorization`. An amount above 1000000000 is necessarily above the remainder and is `capture_exceeds_authorization`. Reason: same order as row F5; expiry is named separately from "not open" so an expired hold reports the more specific code. | P |
| O7 | Capture idempotency: `{}` and `{"amount": 2000}` are different bodies (409 `idempotency_key_reuse` under one key); so are `{"amount":700}` and `{"amount":700,"final":true}`. A replay returns the original payment with 200 even after the authorisation closed, was voided or expired. A second capture with a new key after a final capture is 409 `authorization_not_open`. | P |
| O8 | `POST /authorizations/{id}/void`: only the payer, no key. 200 with the authorisation, `status: "voided"`, hold released. Voiding again is 200 with the current state. `captured` or `expired` -> 409 `authorization_not_open`. Not the payer (receiver or third party) -> 403; unknown -> 404. A partially captured open authorisation can be voided: only the remainder is released, `captured_amount`, `payment_id` and `payment_ids` are kept. Expiry of a partially captured one likewise keeps its capture records. | P |
| O9 | `GET /authorizations` (JSON): only authorisations where the caller is payer or receiver; newest first by `created_at`; `direction` = `outgoing` (caller is payer) / `incoming` (caller is receiver) / absent; `status` one of the four or absent, where clock-expired matches `expired` and never `open`; unknown values 422; `limit`/`offset`/`has_more` exactly as `GET /requests`; body `{"authorizations":[…], "has_more": bool}`. A settlement operator gets no extra access. | P |
| O10 | Races: capture vs void vs expiry vs a second capture resolve to one consistent outcome; money moved equals the sum of recorded captures; `held` equals the sum of remaining amounts. | P bursts |

## Q. Browser: routes, session, shared rules (S2 intro, "Signup and login")

| Row | Requirement | Check |
|---|---|---|
| Q1 | `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` are each reachable directly by URL and through consistent navigation present on every screen. | H, B |
| Q2 | `/requests` and `/authorizations` are shared with the API: a GET whose `Accept` contains `text/html` gets the UI (200 HTML, no token needed to load the page); any other request gets the JSON API with all stage-1 rules (401 without a token, etc.). Query parameters do not change this. | H, B, P with curl both ways |
| Q3 | **[D]** The UI is a client of the documented JSON API only: it signs in with `POST /auth/login` / `POST /auth/signup`, keeps the returned bearer token in the browser, and reads and writes through the documented endpoints at their documented paths with `Authorization: Bearer` and, on the seven write paths, `Idempotency-Key`. No server-side session, no UI-only endpoints for data. Reason: the upgrade and lost-response requirements are stated in terms of the API calls the browser makes, and a session that lives only in the token survives an export/import. | I, B: record the requests the page makes |
| Q4 | Every element listed in S2 carries exactly its `data-testid`; no test id appears twice on one page. Error and state elements that S2 says are present only in a condition (`auth-error`, `pay-error`, `pay-uncertain`, `request-error`, `split-error`, `authorize-error`, `authorization-error`, `wallet-held`, `empty-*`, per-item buttons) are absent from the DOM otherwise, not merely hidden. | B |
| Q5 | Signup: `signup-email`, `signup-password`, `signup-display-name`, `signup-submit`; login: `login-email`, `login-password`, `login-submit`; `auth-error` appears on a refused signup or login (wrong password, taken email or handle, short password, bad email) and only then. After success the user is signed in and taken to the wallet. `/login` and `/signup` render their forms when opened directly, also while signed in. | H, B |
| Q6 | When signed in, every screen shows `current-user` (text contains the display name), `current-handle` (text exactly the handle, no `@`, no other words inside that element) and `logout-button`. Logout removes the token and `current-user` disappears. A signed-out visitor to a wallet screen is led to login. A token the service no longer knows (401) signs the browser out cleanly. | H, B |
| Q7 | Formatted amount everywhere: decimal with exactly `minor_units` places, one space, the currency code (`100.00 EUR`, `0.05 EUR`, `1200 JPY`, `1.000 BHD`); no sign, no grouping separators inside the test-id element; exact for values up to 2^53 (no floating-point arithmetic). | H, B for EUR, JPY, BHD |
| Q8 | Decimal amount inputs (`pay-amount`, `request-amount`, `split-amount`, `authorize-amount`, `authorization-capture-amount-{id}`): a decimal string as a person types it becomes minor units exactly: with 2 places `15.00` and `15` -> 1500, `15.5` -> 1550. Non-numeric input, or more than `minor_units` decimal places (`15.005`; `15.5` in JPY), shows that form's error element and sends no request. Never rounded. **[D]** Accepted form: digits, optionally a point followed by 1..`minor_units` digits, surrounding spaces ignored; everything else (sign, exponent, comma, empty) is refused in the form. | H, B |
| Q9 | Text from users (notes, display names, handles) is rendered as text, never as markup: a note `<b>&amp;</b>` shows literally. | B |
| Q10 | After any successful action the balance, feed and lists on the same page show the new state without a manual reload, and only after the write succeeded. No background polling is required. | H, B |
| Q11 | (added after stage-2 BLOCK 1) Any element or test id the UI adds beyond S2 must not fall inside a specified test-id family for any possible resource id (ids are opaque strings, seeded ids are arbitrary): nothing added may match `activity-item-*`, `activity-parties-*`, `activity-amount-*`, `activity-note-*`, `request-item-*`, `request-amount-*`, `request-pay-*`, `request-decline-*`, `request-cancel-*`, `split-share-*`, `authorization-item-*`, `authorization-amount-*`, `authorization-captured-*`, `authorization-expires-*`, `authorization-capture-amount-*`, `authorization-capture-*`, `authorization-void-*`, or equal a fixed specified id. Each specified id names exactly the element S2 describes, whatever the resource id is. | B: seeded resources whose ids are the suffix words the UI uses (`visibility`, `amount`, `keep-open`, `error`) |

## R. Browser: wallet screen `/` (S2 "Balance and pay", "Activity feed", "Competing clients")

| Row | Requirement | Check |
|---|---|---|
| R1 | `wallet-balance`: text exactly the formatted `total`, `data-amount` = minor units. `wallet-available`: formatted `available` with `data-amount`, presented as the headline number. `wallet-held`: formatted `held` with `data-amount`, absent when `held` is 0. Correct immediately after a reset with seeded open holds, and after expiry on the next read. | H, B |
| R2 | Pay form: `pay-handle`, `pay-amount`, `pay-note`, `pay-visibility` (a select whose option values are exactly `public` and `private`), `pay-submit`; `pay-error` when refused (insufficient funds, unknown handle, self payment, invalid input), absent otherwise. | H, B |
| R3 | The pay form keeps its values after success. Submitting again without changing a field sends no new payment: the balance falls once, the feed has one payment, `pay-error` is absent. Changing any field makes the next submission a new payment (new key). The key belongs to the unchanged form content, not to the click. | H, B |
| R4 | Request form: `request-handle`, `request-amount`, `request-note`, `request-submit`; `request-error` when refused. Same retry rule: an unchanged form resubmitted creates no second request. | B |
| R5 | Feed: `activity-list` whose direct children are the items, newest first; `activity-item-{payment_id}` with `data-visibility`; `activity-parties-{payment_id}` containing both handles; `activity-amount-{payment_id}` exactly the formatted amount; `activity-note-{payment_id}` exactly the note and present even when empty; `empty-activity` shown instead of the list when nothing is visible. Feed content equals `GET /activity` for the user (private items of others never shown). | H, B |
| R6 | `wallet-refresh` re-reads balance and feed without clearing or changing the pay form. Latest refresh wins: when two refreshes overlap and the earlier response arrives last, the screen keeps the later refresh's data. The same holds for refreshes triggered by the page's own actions, and for `wallet-available` / `wallet-held`. | H, B: delay the first read's response past the second |
| R7 | A payment refused because another client spent the money shows `pay-error`, refreshes balance and feed, and keeps every pay input. | B |
| R8 | Lost response: if the response to `POST /payments` never arrives (connection aborted, including after the service committed), or the outcome is otherwise unknown (network error, 5xx, unreadable response), the page shows `pay-uncertain` with non-empty text and no `pay-error`. The unchanged form retries with the same key and the same body. A successful retry (201 or 200) removes `pay-uncertain` and `pay-error`, refreshes balance and feed, and money has moved exactly once. Only a 4xx with the error body counts as a refusal. | B: abort the response after the server handled it; then retry |
| R9 | Authorise form on `/`: `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit`, `authorize-error` when refused (including insufficient available funds); same input and retry rules as the pay form. After success `wallet-available` falls, `wallet-held` appears, `wallet-balance` is unchanged. **[D]** The same form is also on `/authorizations` together with the three wallet numbers, so a hold can be placed and seen on one screen. Reason: S2 lists the form without naming its screen. | B on both screens |

## T. Browser: requests, split, authorisations screens

| Row | Requirement | Check |
|---|---|---|
| T1 | `/requests`: `incoming-list` and `outgoing-list` are always present; `request-item-{id}` with `data-status`; `request-amount-{id}` exactly the formatted amount; `request-pay-{id}` and `request-decline-{id}` only on a pending incoming request; `request-cancel-{id}` only on a pending outgoing request; `empty-requests` when both lists are empty. Paid, declined and cancelled requests stay listed with their status. | H, B |
| T2 | Pay, decline and cancel act through the API and then refresh the lists: the item's `data-status` changes and its buttons disappear. A refusal shows `request-error` (insufficient funds; request no longer pending) and refreshes the list, so a request cancelled elsewhere loses its stale pay button. Pay uses a key that stays the same for retries of that request. | H, B |
| T3 | `/split`: `split-amount`, `split-handles` (comma-separated, order kept, spaces around handles ignored), `split-note`, `split-submit`; `split-preview` with one `split-share-{handle}` per participant, text exactly the formatted share, computed by the §9 rule before anything is posted and identical to the submitted split's shares, for every order and remainder, in EUR, JPY and BHD. `split-error` when refused (unknown handle, duplicate, empty, invalid amount). An unchanged form resubmitted creates no second split. | H, B |
| T4 | `/authorizations`: `authorization-list` always present, direct children are the items, newest first; `authorization-item-{id}` with `data-status` (clock-expired shows `expired`); `authorization-amount-{id}` exactly the formatted authorised amount; `authorization-captured-{id}` formatted captured amount, present only when status is `captured`; `authorization-expires-{id}` text is the RFC 3339 `expires_at` exactly as the API returns it; `empty-authorizations` when the list is empty. Seeded and newly created holds both appear. | B |
| T5 | `authorization-capture-amount-{id}` (decimal input pre-filled with the remaining amount in typed form, e.g. `20.00`) and `authorization-capture-{id}` only on an incoming open authorisation; `authorization-void-{id}` only on an outgoing open one. Capture sends the typed amount; the list and wallet numbers refresh. A refused capture or void (exceeds, expired, not open, invalid amount) shows `authorization-error` and refreshes the list so stale controls disappear. | B |

## U. Browser: upgrade without reload (S2 "Existing clients after an upgrade")

| Row | Requirement | Check |
|---|---|---|
| U1 | A browser signed in before an export/import stays signed in afterwards without a reload: its next action or refresh works with the same token. | B: sign in, export, import, click refresh |
| U2 | A pending request that existed before the import is payable through the request screen afterwards. | B |
| U3 | A payment whose response was lost before the export stays retryable after the import with the same key and body: the retry returns the original payment, the page clears `pay-uncertain` and shows the imported balance; money moved once. The form content and its retry key survive the upgrade in the open page. | B |
| U4 | **[D]** The UI tolerates reading from a service state that came from stage 1: `GET /me` fields `available` and `held` missing are treated as `balance` and 0; payments without `authorization_id` render normally. Reason: robustness of open pages across the upgrade. | I, B with stubbed responses |

## V. Product quality (S2 "Product and visual direction")

| Row | Requirement | Check |
|---|---|---|
| V1 | One coherent visual system across all six screens: shared typography scale, spacing scale, colour roles, control styles and feedback styles defined once (design tokens / one stylesheet); calm, trustworthy consumer-finance character; consistent header and navigation with the current screen marked. | I: screenshots of every screen at 375 px and 1280 px, attached to the verdict |
| V2 | Available funds is the clearest monetary value on the wallet; total and held are visibly secondary. | I |
| V3 | Payments, requests, splits and authorisations are easy to scan: direction (sent / received / between others), counterparty, amount, privacy (public / private), status and time are understandable without reading raw API data. People are shown by display name where known and handle; timestamps are formatted for people (the raw RFC 3339 value stays where S2 requires it); technical identifiers are not shown unless they help. | I, B |
| V4 | Primary actions are easy to identify. Available, held, pending, loading, successful, refused and uncertain states are visually distinct (not by colour alone). Considered empty, loading and error states on every screen. | I, B |
| V5 | Usable at a 375 CSS-pixel viewport and at desktop widths with no horizontal page scrolling (`document.documentElement.scrollWidth <= clientWidth` on every screen, with long notes, long handles and large amounts). | B at 375, 768, 1280 |
| V6 | Accessibility: every input has a visible label bound to it; keyboard focus is clearly visible; all flows work by keyboard; text and controls meet WCAG AA contrast; errors are announced (`role="alert"` or a live region); buttons are real buttons, forms submit with Enter. | I, B |
| V7 | Maintainable UI code: separated modules for API access, formatting/parsing of money, each screen, and shared components; no framework fetched at run time; unit tests for money formatting, decimal parsing and the split preview. The server side keeps the stage-1 structure (one place for validation, one for the ledger). | I |

## Z. Stage boundary

| Row | Requirement | Check |
|---|---|---|
| Z1 | `stage-2/` implements stages 1 and 2 only: nothing from a later stage. The harness run for stage 2 ends `claimed stage: 2 on the shipped checks` with stages 1 and 2 `pass` and the stage-3 overshoot line `fail`. | H, I |
| Z2 | Written to the specification, not to the supplied checks: no behaviour keyed to fixture names, test ids of the checks, or check-specific values. | I |

## Commands

From `/home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs`:

```sh
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --out ../band-work/checks/<new-name>
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/<new-name>
```

Every run needs a new `--out` directory. The final check of the stage is the isolated one.
