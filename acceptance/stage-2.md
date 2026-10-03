# Acceptance map — Pocketful stage 2

Source: `dark-factory-wearedevs/pocketful/spec/stage-2.md` (complete) plus all of `stage-1.md`
(still applies; see `acceptance/stage-1.md`, rows A1–J6, which remain in force for `stage-2/`).
Target: `stage-2/`, started as a copy of the accepted `stage-1/` (revision 172a3180). `stage-1/`
must not change. "Supplied" = harness `--stage 2` (runs stage 1 and stage 2 suites; the stage-2
suite drives a browser with Playwright). "Own" = tests written from the spec by the Implementer
and independently by the Verifier; UI rows need a real browser at 375 px and a desktop width.

## K. Regression and delivery

| Row | Requirement | Check |
|---|---|---|
| K1 | Every stage-1 row A1–J6 holds for `stage-2/` (with the stated changes: `/me` gains fields, payments gain `authorization_id`, seven idempotent paths) | Supplied stage-1 suite against stage-2 + own stage-1 checks rerun |
| K2 | `stage-2/` is self-contained: own Dockerfile + RUN.md, builds clean, runs isolated; all UI assets (fonts, scripts, styles) are in the image, no external URLs requested at run time | Build; isolated run; grep assets/network log for external hosts |
| K3 | `stage-1/` is byte-identical to accepted revision 172a3180 | `git diff 172a3180 -- stage-1` empty |
| K4 | No stage-3/4 features implemented early | Verifier step 5 against the stage-3 spec |
| K5 | Resource limits still met with UI and expiry logic (2 vCPU / 2 GiB, 50 in flight, 5 s, 60 s start) | Load run |

## L. Routes and content negotiation

| Row | Requirement | Check |
|---|---|---|
| L1 | `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` reachable by URL and return the screen for `Accept: text/html` | Browser + curl |
| L2 | `/requests` and `/authorizations` are shared: `Accept: text/html` → HTML UI; without that header → JSON API exactly as specified (incl. 401 JSON when unauthenticated) | curl both ways |
| L3 | Other screens reachable through the UI; navigation consistent on all required routes; signed-out visit to a wallet screen leads to login | Browser |

## M. Auth UI

| Row | Requirement | Check |
|---|---|---|
| M1 | `signup-email`, `signup-password`, `signup-display-name`, `signup-submit` work; success signs in | Browser |
| M2 | `login-email`, `login-password`, `login-submit` work | Browser |
| M3 | `auth-error` present only when there is an error (wrong password, email taken, handle taken, validation) | Browser |
| M4 | `current-user` visible on every screen when signed in, text contains display name; `current-handle` text exactly the handle (no `@`, no extra words); `logout-button` signs out | Browser, every route |

## N. Wallet screen `/`

| Row | Requirement | Check |
|---|---|---|
| N1 | `wallet-balance`: text exactly the formatted `total`, `data-amount` = minor units | EUR/JPY/BHD fixtures |
| N2 | Formatted amount: exactly `minor_units` decimals, one space, currency code (`100.00 EUR`, `1200 JPY`, `1.500 BHD`); no sign; no thousands separators | Own |
| N3 | `wallet-available`: formatted `available` with `data-amount`, presented as the headline (largest/clearest) number; total and held visibly secondary | Browser + screenshot |
| N4 | `wallet-held`: formatted `held` with `data-amount`; absent when held is zero; shown right after reset with seeded open holds | Browser |
| N5 | Pay form `pay-handle`, `pay-amount`, `pay-note`, `pay-visibility` (option values exactly `public`, `private`), `pay-submit` | Browser |
| N6 | Decimal parsing (pay, request, split, authorize, capture inputs): `15.00` and `15` → 1500, `15.5` → 1550 at 2 units; non-numeric or more than `minor_units` decimals (`15.005`; any `.` fraction at 0 units) shows the form's error element and sends no request; never rounds; no float arithmetic | Browser with request log |
| N7 | `pay-error` shown when refused (incl. insufficient funds, unknown handle, self payment); absent otherwise | Browser |
| N8 | Pay form keeps its values after success; resubmitting unchanged sends no second payment: balance falls once, feed has one payment, no `pay-error`; changing any field makes a new payment (new key); retries follow §7 | Browser |
| N9 | Request form `request-handle`, `request-amount`, `request-note`, `request-submit`; `request-error` when refused | Browser |
| N10 | `activity-list` children newest first; `activity-item-{id}` with `data-visibility`; `activity-parties-{id}` contains both handles; `activity-amount-{id}` exactly formatted amount; `activity-note-{id}` exactly the note, present even when empty (verbatim, HTML-escaped safely, emoji intact); `empty-activity` instead of the list when nothing visible | Browser |
| N11 | After any successful action the balance, feed and request lists on the same page show the new state without manual reload; refresh happens only after the write succeeded | Browser |
| N12 | `wallet-refresh` refreshes balance (total, available, held) and feed without clearing the pay form | Browser |
| N13 | Latest refresh wins: a delayed earlier read never overwrites a later one, even when responses arrive out of order | Browser with route interception delaying the first response |
| N14 | Payment refused because another client spent the balance: `pay-error`, balance/feed refreshed, all pay inputs preserved | Browser + API side-channel |
| N15 | Lost payment response (incl. after commit): `pay-uncertain` with non-empty text, no `pay-error`; unchanged form retry uses the same key and body; successful retry removes both elements, refreshes balance and feed, money moved exactly once; an unknown outcome is never shown as a rejection | Browser with aborted response |

## O. Requests screen `/requests`

| Row | Requirement | Check |
|---|---|---|
| O1 | `incoming-list`, `outgoing-list`; `request-item-{id}` with `data-status`; `request-amount-{id}` exactly formatted | Browser |
| O2 | `request-pay-{id}` and `request-decline-{id}` only on pending incoming; `request-cancel-{id}` only on pending outgoing; each works and the list updates | Browser |
| O3 | `request-error` when pay/decline/cancel is refused (e.g. insufficient funds); `empty-requests` when both lists are empty | Browser |
| O4 | Request cancelled elsewhere while pay button visible: pay shows `request-error` and the list refreshes so the stale pay button disappears | Browser + API side-channel |

## P. Split screen `/split`

| Row | Requirement | Check |
|---|---|---|
| P1 | `split-amount` (decimal rule N6), `split-handles` (comma-separated, in order), `split-note`, `split-submit` | Browser |
| P2 | `split-preview` shows one `split-share-{handle}` per participant with exactly the formatted share, before anything is posted, by §9; preview and submitted split have identical shares | Browser: 10.00/3, 0.01/3, order swap |
| P3 | `split-error` when refused (unknown handle, duplicate, empty, bad amount) | Browser |

## Q. Product quality

| Row | Requirement | Check |
|---|---|---|
| Q1 | Usable at 375 CSS px and at desktop widths with no horizontal page scroll on every required route, incl. long notes/handles | Browser: `scrollWidth <= clientWidth` at 375 and 1280 |
| Q2 | Every input has a visible label; keyboard focus visibly indicated; text/control contrast sufficient (WCAG AA as the yardstick) | Browser + read CSS |
| Q3 | Consistent visual system; primary actions identifiable; available / held / pending / loading / success / refused / uncertain states visually distinct | Screenshots review |
| Q4 | Considered empty, loading and error states; people, amounts and timestamps formatted for people; technical ids shown only where useful; status, direction, privacy and money movement understandable | Screenshots review |

## R. Upgrade from stage 1

| Row | Requirement | Check |
|---|---|---|
| R1 | Stage-2 service imports an export produced by this repo's `stage-1/` service (204); all J3 data preserved; authorizations empty, ttl default 600 | Export from stage-1 container → import into stage-2 container |
| R2 | A browser signed in before the export/import stays signed in afterwards (token preserved; no reload needed) | Browser on stage-2: sign in, export, reset/import, continue |
| R3 | Existing pending requests stay payable through the request screen after import | Browser |
| R4 | A payment whose response was lost before export is retryable after import with same body and key; UI recovers the original payment and refreshes the imported balance; form and pending retry identity survive (no reload, no new screen) | Browser |
| R5 | Stage-2 export/import round-trips its own state incl. authorizations, holds, captures, ttl, and the two new idempotent paths' records | Own |

## S. Authorizations model and invariants

| Row | Requirement | Check |
|---|---|---|
| S1 | Sum of all `total` equals the seeded total at every read; a hold moves no money | Concurrent storm, sum via `/me` |
| S2 | `available = total − held` never negative; held funds cannot fund payments, request pays, new authorizations or settlement net debits | Own: hold then overspend by each path → 409 |
| S3 | Cumulative captures never exceed the authorized amount; each idempotent capture moves money once; a closed hold cannot be captured again | Concurrent captures |
| S4 | Captures spend the reserved money (succeed even when `available` is 0) | Own |
| S5 | Concurrent requests behave as some serial order; invariants hold at every read | 50-way mixed load |
| S6 | Fixture: `authorization_ttl_seconds` default 600; if supplied must be a positive integer else 422 (0, negative, fractional, string) | Own |
| S7 | Fixture `authorizations` optional (omitted = empty); seeded items keep `id`, parties, amount, note, visibility, status (`open`/`captured`/`voided`/`expired`), own absolute `expires_at`; only unexpired `open` ones hold funds | Own |
| S8 | Seeded `balance` is `total`; `available` derived; sum of a user's seeded unexpired open holds > balance → 422 from reset, nothing changes | Own (equal is ok) |
| S9 | Expiry by the clock: `expires_at` ≤ now ⇒ status `expired`, holds nothing, reflected in `GET /authorizations` and `/me` `available` with no intervening request; seeded open hold with past `expires_at` reads as expired | Own with ttl 1–2 s |

## T. Authorizations API

| Row | Requirement | Check |
|---|---|---|
| T1 | `GET /me` adds `total`, `available`, `held`; `balance == total`; with no holds all agree and `held` is 0 | Own |
| T2 | `POST /authorizations` (idempotent, caller is payer) → 201 with `authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount:0, remaining_amount, currency, note, visibility, status:"open", expires_at, payment_id:null, payment_ids:[], created_at`; `expires_at = created_at + ttl`; defaults as payments | Own |
| T3 | Authorization errors: 409 `insufficient_funds` when `available < amount` (equal ok); 422 amount <1 / >1e9 / non-integer; 422 `self_payment`; 422 note > 200 or bad visibility; 404 unknown handle | Own |
| T4 | An open authorization never appears in `/activity` | Own |
| T5 | `POST /authorizations/{id}/capture` (idempotent, receiver only) → 201 payment in the `POST /payments` shape with `authorization_id` set, `request_id: null`, amount = captured amount, note/visibility copied; appears in feed by the normal rule; all other payments carry `authorization_id: null` | Own |
| T6 | Default (final) capture: status `captured`, `captured_amount`, `payment_id` set, remainder released to payer's `available` in the same step; second capture → 409 `authorization_not_open` | Own |
| T7 | `amount` optional, defaults to the remaining amount; `{}` and `{"amount": N}` are different bodies for idempotency (409 `idempotency_key_reuse`) | Own |
| T8 | Extended mode `final: false` (boolean, default true; non-boolean → 400 per §5): remainder stays held, status stays `open`, more captures allowed up to the remainder; capturing the whole remainder closes it even with `final:false`; a final capture closes and releases the remainder; `captured_amount` cumulative; `payment_id` latest; `payment_ids` all in order; `remaining_amount` = amount still held, 0 when closed | Own |
| T9 | Capture errors: 409 `authorization_not_open`; 409 `authorization_expired` when `expires_at` ≤ now; 422 `capture_exceeds_authorization` when amount > remaining (remaining+1 fails, remaining ok); 422 amount < 1 or non-integer; 403 non-receiver (payer and third party); 404 unknown | Own |
| T10 | `POST /authorizations/{id}/void`: payer only, no key; 200 `voided`, hold released; repeat → 200; `captured` or `expired` → 409 `authorization_not_open`; non-payer (receiver or third party) → 403; unknown → 404 | Own |
| T11 | Void and expiry of a partially captured authorization release only the remainder and keep all capture records (`captured_amount`, `payment_ids`) | Own |
| T12 | `GET /authorizations`: only caller's; newest first; `direction` outgoing/incoming/absent; `status` four values/absent, clock-expired matches `expired` never `open`; unknown values → 422; `limit`/`offset`/`has_more` as `GET /requests`; shape `{authorizations, has_more}` | Own |
| T13 | Seven idempotent paths: all F rows apply to `POST /authorizations` and capture independently (replay 200 same body, reuse 409, concurrency one 201, failed key reusable, per-user scope, key length) | Own |
| T14 | Stage-1 insufficient-funds checks (payments, request pay, settlements net debit) use `available`; unchanged with no holds; `POST /payments` leaves no hold; `POST /splits` unchanged | Own |

## U. Authorizations UI

| Row | Requirement | Check |
|---|---|---|
| U1 | Authorize form `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` with the pay form's input rules; `authorize-error` when refused incl. insufficient available funds | Browser |
| U2 | `/authorizations`: `authorization-list` newest first; `authorization-item-{id}` with `data-status`; `authorization-amount-{id}` exactly formatted authorised amount; `authorization-captured-{id}` formatted captured amount only when status is `captured`; `authorization-expires-{id}` text is the RFC 3339 `expires_at`; `empty-authorizations` when empty | Browser |
| U3 | `authorization-capture-amount-{id}` (decimal, pre-filled with remaining) and `authorization-capture-{id}` only on incoming open; `authorization-void-{id}` only on outgoing open; `authorization-error` when capture/void refused; list and wallet numbers refresh after the action | Browser |
| U4 | UI reflects seeded and newly created holds; available is shown as the spending balance immediately after reset with open holds; the N12–N14 refresh rules apply to available and held | Browser |

## Supplied checks

From `/home/ubuntu/nightshift-claude-bg-test/dark-factory-wearedevs`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --out ../band-work/checks/<new-name>

Final run adds `--mode isolated`. Every run needs a new `--out` directory.

## Recorded choices

- The spec does not say which screen holds the authorize form. Choice: it is on `/authorizations`
  and also on `/` (each `data-testid` at most once per page), so a test looking on either finds it.
  `wallet-available`, `wallet-balance`, `wallet-held` are on `/` (and may also be on `/authorizations`).
- The capture button in the UI performs a default (final) capture of the entered amount; extended
  capture (`final: false`) is an API feature, the spec lists no UI control for it.
- `final` of a non-boolean type is "a field of the wrong type" → 400 `malformed_request` (§5); capture
  `amount` of wrong type stays 422 (§5 field rule for amounts).
- A capture has no upper bound of 1000000000 stated beyond the remaining amount; the authorised amount
  is itself capped, so the remainder check governs.
- Capture precedence when several errors apply: 404 → 403 → idempotency resolution (§7) → amount
  validation (422) → not open (409) / expired (409) → exceeds remainder (422). An authorisation past
  its `expires_at` answers `authorization_expired`; one already captured/voided answers `authorization_not_open`.
- UI state that must survive an import (R2, R4) lives in the browser page (token in storage, retry key in
  memory); the server keeps tokens and idempotency records through export/import.
