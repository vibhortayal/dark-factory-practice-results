@vibhor15/nightshift-implementer
Rows: all stage-2 rows + stage-1 regression · Revision: stage-1 accepted at 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb; base = head of main · Files: stage-2/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-2 HANDOFF PART 5/9 — ACCEPTANCE MAP acceptance/stage-2.md (verbatim)

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
