# Pocketful stage 4 — run instructions

Stage 3 (statements, historical balances, corrections) plus refunds and operator batch
corrections. The UI is unchanged from stage 2 (no new screen).
Pure Python 3.12 standard library on the server; the UI is plain ES modules and CSS
with system fonts. Nothing is fetched from another origin, and no network is
needed at run time.

## Build and start

    docker build -t pocketful-stage-4 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-4

`PORT` defaults to `8080`; the service listens on `0.0.0.0:$PORT`. Open
`http://localhost:8080/` for the UI (`/`, `/requests`, `/split`, `/authorizations`,
`/signup`, `/login`). The API is on the same origin; `/requests` and
`/authorizations` return the UI for `Accept: text/html` and JSON otherwise.

## Tests

    python3 -m unittest discover -s tests -t . -v          # API tests (in-process server)
    python3 tests/load_check.py http://127.0.0.1:8080 [second-url]   # limits, 50-way bursts, export -> import
    <python with playwright> tests/ui_check.py CURRENT_URL [STAGE1_URL] [screenshot-dir]   # browser checks (stage-2 UI)
    python3 tests/upgrade_check.py CURRENT_URL STAGE2_URL STAGE1_URL [STAGE3_URL]   # exports of stage-1/2 services import into stage 3
    python3 tests/perf_check.py CURRENT_URL                 # 5000 payments, 50 mixed history requests

`ui_check.py` needs Chromium through Playwright (the kickoff checkout's `.venv` has it);
the optional stage-1 URL enables the upgrade scenario (a browser signed in against a
stage-1 service keeps working after export -> import into stage 2).

## Where things are

| Path | Job |
|---|---|
| `pocketful/server.py`, `__main__.py` | HTTP plumbing: phase 1 decoding, JSON/HTML/asset responses, `PORT` |
| `pocketful/router.py` | route table, UI-or-API decision, auth, clock expiry sweep |
| `pocketful/request.py`, `errors.py`, `validation.py`, `timefmt.py`, `passwords.py` | request object, errors, field rules, timestamps, scrypt |
| `pocketful/store.py` | the one JSON-shaped state dict, its lock, lookup indexes |
| `pocketful/clock.py`, `operation.py` | monotonic clock; start of every locked operation (one clock read + expiry) |
| `pocketful/holds.py` | holds: `held`, `available = total - held`, closing, clock expiry, and the hold history (`held_at`, `hold_steps`) |
| `pocketful/history.py` | the one function behind `/me?as_of`, `/statement` and the overdraft check: a user's movements in a view (T, K) from revisions |
| `pocketful/ledger.py` | moving money; payment and request records (funds checks use `available`) |
| `pocketful/idempotency.py` | the seven idempotent write paths |
| `pocketful/fixture.py` | reset fixture -> state (users, payments, requests, authorizations, TTL) |
| `pocketful/statecheck.py`, `statebase.py` | validation of exported/imported state |
| `pocketful/stateupgrade.py` | brings a stage-1 / stage-2 export up to the current shape (revision 1 of every payment, opening balances, `closed_at`) |
| `pocketful/handlers/` | one module per API area: `auth`, `me`, `payments`, `requests`, `splits`, `settlements`, `activity`, `authorizations`, `statement`, `corrections`, `refunds`, `batches`, `testctl`, `ui` |
| `pocketful/ui/index.html`, `styles.css` | the page shell and the visual system |
| `pocketful/ui/js/app.js` | client router and bootstrap; `header.js` navigation and current user |
| `pocketful/ui/js/api.js` | the only network code: bearer token, result kinds (ok / refused / uncertain), idempotency keys |
| `pocketful/ui/js/money.js` | exact decimal <-> minor units, equal-split preview |
| `pocketful/ui/js/components.js`, `feed.js`, `session.js`, `dom.js` | wallet card, send forms, feed, session state, element builder |
| `pocketful/ui/js/pages/` | one module per screen: `home`, `requests`, `split`, `authorizations`, `auth` |
| `tests/` | own tests |

## Design notes

* One process-wide lock serialises every state change; `available` is derived from
  open holds on every read. `store.locked()` begins every operation itself (one clock read,
  clock expiry), so a handler cannot forget; `auth.py` and the settlement permission check
  use the raw lock because they read no time.
* History: every payment has revisions (`state.revisions`), revision 1 = original with
  effective = recorded = created_at. A view (T, K) takes each payment's latest revision recorded
  at or before K and counts it at its effective time <= T. Opening balances are fixed at
  reset/import (ending balance minus the seeded payments' net effect); new accounts open at 0.
  A correction moves the difference between the same two wallets in one step and is refused
  (`stale_revision`, `insufficient_funds`, `historical_overdraft`, in that order) before anything changes;
  `historical_overdraft` is a sweep over every past boundary (payment effective times and hold
  events, all movements of one instant applied together).
* Snapshots (`state.snapshots`) store only their parameters (user, window, resolved `to`,
  `known_at` clamped to the read instant); a view with K at or before the read never changes later,
  so pages are recomputed and stay frozen. Tokens last until reset and are part of export/import.
* Imports of older exports: revision 1 for every payment; opening = balance minus net payments;
  a hold closed by a final capture closes at that capture, an expired one at `expires_at`, a voided one
  at its last capture or (none) its creation.
* Time: each locked operation reads a monotonic clock once (`clock.py`, `operation.begin`);
  every server-assigned timestamp is a fixed-width microsecond instant
  (`2026-09-24T13:10:00.123456+00:00`), `expires_at = created_at + ttl` exactly, and a hold is open
  strictly before `expires_at`. Fixture/import timestamps are kept as given.
* Authorizations: a capture moves money
  from the payer's total and shrinks the hold; a final capture releases the rest.
* The UI is a client-rendered app over the documented JSON API (bearer token in
  `localStorage`; no cookie session and no UI-only endpoints). Because the page holds
  everything it needs, a service swapped by export -> import underneath it keeps working.
  It also tolerates a stage-1 shaped service (`/me` without `available`/`held`, no `/authorizations`).
* Idempotency in the UI: each form keeps one key while its content is unchanged
  (any input renews it), so a double click or a retry after a lost response replays.
  A confirmed rejection is a 4xx with the error body; a network failure, timeout, 5xx
  or unreadable response is an unknown outcome and shows the "uncertain" message.
* Idle connections: the server closes a keep-alive connection after 120 s idle and
  advertises `Keep-Alive: timeout=110`, so a browser does not normally reuse a socket the
  server is about to close. If it ever does, the write fails as an unknown outcome and the
  retry carries the same idempotency key, so it can never act twice.
* Limits: request line and header lines 64 KiB, at most 100 headers, body 64 MiB, 120 s
  to receive a request; each excess answers a JSON error body.
* Passwords: scrypt (N=4096, r=8, p=1, per-user salt).

## Error precedence (one list per endpoint)

* Every idempotent write: 401 -> (settlement / batch endpoints: 403 non-operator) -> missing key 400, over-long key 422
  -> body parse 400 -> claimed key (replay 200 / reuse 409) -> endpoint rules below.
* `POST /payments/{id}/refunds`: amount 422 -> 404 -> 403 (not the receiver) -> `invalid_refund_target` ->
  `refund_exceeds_payment` -> `insufficient_funds` (receiver's *available* funds).
* `POST /payments/{id}/corrections`: field validation 422 -> 404 -> 403 (not the sender) ->
  `linked_payment_immutable` (capture, refund, settlement member) -> `stale_revision` ->
  `refund_exceeds_payment` -> `insufficient_funds` -> `historical_overdraft`.
* `POST /correction-batches`: batch shape 422 (1..32 objects, distinct payment ids) -> per item in input order:
  validation 422, 404, `linked_payment_immutable` (capture, refund), `stale_revision`, `refund_exceeds_payment`
  -> `incomplete_settlement` -> identical effective instants within a settlement (422) -> `insufficient_funds`
  (combined effect of all proposals on current available funds) -> `historical_overdraft` (all proposals together).
  Accepted batches write every revision in one locked step with one `recorded_at` and a shared `correction_batch_id`.

## Refunds and snapshots

A refund is a normal payment (receiver -> sender, `refund_of` = target, same note and visibility,
`settlement_id` null, never a request/authorization link); its cap is the target's latest revision amount minus
earlier refunds. Snapshots taken by a stage-3 service keep their original payment shape (no `refund_of`) after import.
