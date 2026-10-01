@vibhor15/nightshift-implementer STAGE 2 HANDOFF — part 5 of 9: stage-2 acceptance map, sections T–X (end of the stage-2 map). Do not start until part 9 (FINAL).

## T. Authorizations — model and fixture

| # | Requirement | Check |
|---|---|---|
| T1 | Fixture `authorization_ttl_seconds`: default 600 when omitted; when supplied must be a positive integer, else reset 422 changing nothing (CHOICE: integral-valued number > 0; `0`, negative, fraction, string, boolean, null → 422) | S + O |
| T2 | Fixture `authorizations` (omitted = empty): `id, from_user_id, to_user_id, amount, note, visibility, status, expires_at`; status ∈ `open`,`captured`,`voided`,`expired`; only `open` and unexpired holds anything | S + O |
| T3 | Seeded `balance` is `total`; `available` derived = total − open unexpired holds | S |
| T4 | Sum of a user's seeded unexpired open holds > that user's balance → reset 422, nothing changes | O |
| T5 | CHOICE: seeded authorization defaults — `note` `""`, `visibility` `public`, `created_at` = reset time unless supplied; `captured_amount` = supplied value, else `amount` when status is `captured`, else 0; `payment_id` supplied or null; `payment_ids` supplied or `[payment_id]`/`[]`; invalid entries (unknown user, from = to, bad amount/status/visibility/`expires_at`) → reset 422. A seeded `open` authorization whose `expires_at` is already past is simply `expired`. Seeded `expires_at` accepts any RFC 3339 form (fractional seconds of any length, `Z` or any numeric offset — Python `isoformat()` emits microseconds) and is returned VERBATIM as seeded, by the API and in `authorization-expires-{id}`; API-created ones use the service's own format | O |
| T6 | Expiry is by the clock, compared against the exact instant the returned `expires_at` denotes (`expires_at` ≤ now ⇒ expired; one instant earlier ⇒ still open): an authorization with `expires_at` ≤ now is `expired`, holds nothing, on every read and write, even if no request happened at the deadline; `GET /authorizations` shows `status:"expired"`; `/me.available` includes the released remainder | O: reset with `authorization_ttl_seconds: 1`, create, wait, read |
| T7 | Invariants: Σ `total` = seeded total always; a hold moves no money; `available = total − held ≥ 0` always, also under concurrency; cumulative captures ≤ authorized amount; each idempotent capture moves money once; a closed hold cannot be captured | O: concurrency tests |
| T8 | `GET /me` → adds `total`, `available`, `held` beside `balance`; `balance == total` always; `held` = sum of remaining amounts of open unexpired holds where the caller is the payer | S |
| T9 | Every stage-1 `409 insufficient_funds` (payments, request pay, settlement net debit) is now evaluated against `available`; held funds cannot fund payments, authorizations or settlement net debits | S + O: all three paths with a hold in place |
| T10 | `POST /payments` stays an immediate transfer — no intermediate authorization appears in `GET /authorizations`; paying a request stays immediate; `/splits` unchanged | O |
| T11 | Seven idempotent write paths; §7 rules apply independently to `POST /authorizations` and `POST /authorizations/{id}/capture` (201/200 replay/409 reuse/400 missing key/422 long key/failed key reusable/concurrent identical → one 201) | O |
| T12 | Every payment object now carries `authorization_id` (null unless a capture), alongside `request_id` and `settlement_id` — including payments imported from a stage-1 export and original idempotent responses' later reads (stored original responses are replayed unchanged) | O |

## U. Authorizations — API

| # | Requirement | Check |
|---|---|---|
| U1 | `POST /authorizations` body `to_handle`, `amount`, optional `note`/`visibility` (payment defaults); 201 with `authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount:0, remaining_amount, currency, note, visibility, status:"open", expires_at, payment_id:null, payment_ids:[], created_at`; caller is payer; `expires_at = created_at + ttl` | S + O |
| U2 | Rejections: `available` < amount → 409 `insufficient_funds`; amount <1, >1e9, non-integer → 422; own handle → 422 `self_payment`; note > 200 or bad visibility → 422; unknown handle → 404; wrong types per §5 | O |
| U3 | An open authorization is not a feed item; nothing in `/activity` until a capture | O |
| U4 | `POST /authorizations/{id}/capture`: receiver only; body `amount` optional (default = remaining), `final` optional boolean default true; 201 with a payment in exactly the `POST /payments` shape, `authorization_id` set, `request_id:null`, `settlement_id:null`, `amount` = captured amount, `note`/`visibility` copied from the authorization; appears in the feed by the ordinary rule | S + O |
| U5 | Final capture (default): status → `captured`, `captured_amount` cumulative, `payment_id` = this capture, remainder released to the payer's `available` in the same step (`remaining_amount` 0) | O |
| U6 | `final:false` with remainder left: status stays `open`, remainder stays held, more captures allowed up to the remainder; capturing the whole remainder closes it (`captured`) even with `final:false`; `payment_ids` lists every capture in order; `payment_id` is the latest | O |
| U7 | Capture rejections: unknown id 404; caller not receiver 403 (payer and third parties alike); not open (captured/voided) 409 `authorization_not_open`; `expires_at` ≤ now 409 `authorization_expired`; amount > remaining 422 `capture_exceeds_authorization`; amount < 1 or non-integer (incl. string/boolean/null) 422 `validation_failed`; `final` not a boolean → 400 `malformed_request` (wrong JSON type, §5) | O |
| U8 | CHOICE — capture precedence after key resolution: field validation (400/422 on `amount`/`final` shape) → 404 → 403 → 409 `authorization_not_open` (captured/voided) → 409 `authorization_expired` (open but past deadline, also for a seeded status `expired`) → 422 `capture_exceeds_authorization`. Reason: same ordering as stage-1 map D10; an authorization expired by the clock reports the specific expired code | O |
| U9 | Capture replay: `{}` and `{"amount":N}` are different bodies → 409 reuse across them; a successful replay returns the original payment with 200 even after the authorization closed; `final` participates in body equality only when sent ("new fields do not change idempotency body equality": `{"amount":700}` replays `{"amount":700}`, and is a different body from `{"amount":700,"final":true}`) | O |
| U10 | Captures spend the money reserved for them: a capture succeeds even when the payer's `available` is 0; payer `total` falls and receiver `total` rises by the captured amount; conservation holds | O |
| U11 | Concurrent captures on one authorization with different keys: serialisable — final/final → exactly one 201, other 409 `authorization_not_open`; partial captures never exceed the authorized amount | O |
| U12 | `POST /authorizations/{id}/void`: payer only, no idempotency key; 200 with the authorization `voided`, hold released; repeat → 200; `captured` or `expired` → 409 `authorization_not_open`; not the payer (receiver or third party) → 403; unknown → 404. Voiding a partially captured open authorization releases only the remainder and keeps capture records | O |
| U13 | Expiry of a partially captured authorization: status `expired`, remainder released, `captured_amount`/`payment_ids` preserved | O |
| U14 | `GET /authorizations`: only where caller is payer or receiver; newest first; `direction` `outgoing` (caller is payer) / `incoming` (caller is receiver) / absent; `status` one of four / absent; clock-expired matches `expired`, never `open`; unknown values 422; `limit`/`offset`/`has_more` as `GET /requests` | O |
| U15 | Every authorization response (create, list, void) includes `remaining_amount` (held amount; 0 when closed), `captured_amount`, `payment_id`, `payment_ids` | O |
| U16 | Export/import (stage-2 → stage-2) preserves authorizations with ids, timestamps, status, captures, ttl, holds, and the two new paths' idempotency records; reset clears them | O |
| U17 | Operators get no extra rights over authorizations | O |

## V. Authorizations — UI

| # | Requirement | Check |
|---|---|---|
| V1 | `/` wallet: `wallet-available` formatted `available` with `data-amount`, presented as the headline number (largest, first); `wallet-balance` (total) and `wallet-held` visibly secondary; `wallet-held` formatted `held` with `data-amount`, ABSENT from the DOM when held is zero | O |
| V2 | Authorise form on BOTH `/` and `/authorizations` (CHOICE; reason: the spec does not say which screen carries it, and a check may look on either; one form per page so no testid is duplicated in a DOM): `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility` (option values `public`/`private`), `authorize-submit`; same input rules as the pay form; `authorize-error` when refused incl. insufficient available funds; success refreshes available/held | O |
| V3 | `/authorizations`: `authorization-list` children newest first; `authorization-item-{id}` with `data-status`; `authorization-amount-{id}` exactly the formatted authorised amount; `authorization-captured-{id}` formatted captured amount, present ONLY when status is `captured`; `authorization-expires-{id}` text is the RFC 3339 `expires_at` exactly as the API returns it | O |
| V4 | `authorization-capture-amount-{id}` (decimal input pre-filled with the remaining amount as a plain decimal, e.g. `20.00`) and `authorization-capture-{id}` ONLY on incoming `open`; `authorization-void-{id}` ONLY on outgoing `open`; none on closed or clock-expired ones | O |
| V5 | Capture and void work from the screen and refresh the list; `authorization-error` when refused (expired, exceeds, not open, bad decimal input) and the list refreshes so stale controls disappear | O |
| V6 | `empty-authorizations` shown when the list is empty. CHOICE: `authorization-list` itself is ALWAYS in the DOM once the screen has loaded (same pattern as `incoming-list`), with no children when empty | O |
| V9 | CHOICE: `/authorizations` also shows the wallet summary (`wallet-available` headline, `wallet-balance`, `wallet-held` with the same rules as V1) and refreshes it after authorise/capture/void. Reason: "the same balance refresh rules apply to the available and held amounts"; the user needs to see what a hold did | O |
| V7 | UI reflects seeded and new holds; available shown as spending balance immediately after a reset with open holds; refresh rules (R1–R3) also apply to available and held | O |
| V8 | CHOICE: a "keep the rest on hold" checkbox next to the capture button sends `final:false`; unchecked by default. Reason: extended capture mode must be usable by a person; default behaviour unchanged | O |

## W. Product quality (judged by review)

| # | Requirement | Check |
|---|---|---|
| W1 | One consistent visual system: typography scale, spacing, colour tokens, control and feedback styles shared by all six screens; calm, trustworthy consumer-finance character; primary action obvious on each screen | O: screenshots of every screen |
| W2 | At a 375 CSS-px viewport and at desktop widths: all required flows usable, no horizontal page scrolling (`scrollWidth <= clientWidth`), long notes/handles wrap | O: automated overflow check at 375 and 1280 on every route with long-content fixtures |
| W3 | Every input has a visible label; keyboard focus is clearly visible; text/control contrast ≥ WCAG AA; forms submit with Enter; errors are announced (`role="alert"`) | O |
| W4 | Considered empty, loading and error states on every list and form | O |
| W5 | People, amounts and timestamps formatted for people (display name + @handle, formatted money, readable local time); technical ids only where they help | O |
| W6 | Code another developer could maintain: UI assets as separate files with clear modules; money parsing/formatting and split computation unit-tested and shared with nothing duplicated | O: review |

## X. Concurrency (spec "Concurrent operations")

| # | Requirement | Check |
|---|---|---|
| X1 | Concurrent requests give the same results as some serial order and the invariants hold at every read: mixed bursts of payments, authorizations, captures, voids, settlements over the same wallets keep Σ total constant, `available ≥ 0`, `held` = Σ open remainders, no 5xx | O: 50-way mixed burst with invariant reads interleaved |
