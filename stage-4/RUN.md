# Pocketful, stage 4: refunds and batch corrections

A containerised HTTP service (Node.js 20, standard library only, no npm dependencies) with the
stage-1 JSON API, the stage-2 authorization (hold and capture) API and browser UI, the stage-3
historical ledger (balances as of an instant, statements, payment corrections, stable statement
paging) and the stage-4 refunds and operator correction batches. Every script, stylesheet and icon of the UI is in the image; nothing is fetched
from another origin.

## Build and start

```sh
docker build -t pocketful-stage4 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage4
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` within a
second of start. It needs no network at run time and no manual setup; seed data comes from
`POST /_test/reset`. Open http://localhost:8080/login in a browser for the UI (`/`, `/requests`,
`/split`, `/authorizations`, `/signup`, `/login`).

## Tests

Node 20 or newer on the host, no installs:

```sh
npm test        # node --test test/
```

API tests start the service in-process and cover validation, precedence of errors, idempotency
(ten write paths), requests, splits, settlements, holds and captures, expiry by the clock,
export/import (including a stage-1 layout) and 50-way concurrency bursts. `test/frontend.test.mjs`
unit-tests money formatting, decimal parsing, the split rule, retry identity and latest-refresh-wins.

Browser tests (Playwright, Chromium) run against a running service:

```sh
POCKETFUL_URL=http://localhost:8080 <python-with-playwright> -m pytest browser-tests
```

They cover the lost-response retry, latest refresh wins, a request cancelled elsewhere, the hold
screens, split previews in EUR/JPY/BHD, text-not-markup rendering, sign-out on an unknown token and
the export/import upgrade without a page reload.

## Where things live

| Path | Job |
|---|---|
| `src/server.js` | HTTP bootstrap, body reading, JSON response writing |
| `src/ui.js` | Serves the UI shell (for `Accept: text/html` on UI routes) and `/assets/*` from `public/` |
| `src/pipeline.js` | Per-request order of checks: expiry sweep, auth, operator, idempotency key, body parse, replay, handler |
| `src/routes.js` | Route table: endpoints, body mode, idempotency, operator flags |
| `src/validation.js` | The one place for field rules (amount, note, visibility, paging) |
| `src/ledger.js` | The one place balances change for payments and settlements; shares of a split |
| `src/holds.js` | Authorizations: hold accounting, capture, void and clock-driven expiry |
| `src/instant.js` | The one parser and one exact comparison for RFC 3339 instants (sub-millisecond precision kept) |
| `src/history.js` | The historical ledger as pure functions: revision selection, views (total/held/available at an instant as known at another), statements, the boundary walk for corrections |
| `src/corrections.js` | The one validation, eligibility check and commit path for payment corrections: used by the single endpoint and by the operator batch |
| `src/handlers/refunds.js`, `src/handlers/batches.js` | `POST /payments/{id}/refunds`; `POST /correction-batches` |
| `src/handlers/statement.js`, `src/handlers/corrections.js` | `GET /statement` with snapshots; `POST /payments/{id}/corrections`, `GET /payments/{id}/revisions` |
| `src/state.js`, `src/idempotency.js`, `src/fixture.js`, `src/snapshot.js` | State, idempotency records, reset fixtures, export/import |
| `src/handlers/` | One module per endpoint family (`authorizations.js` is new in stage 2) |
| `public/index.html`, `public/css/app.css` | UI shell and the single stylesheet holding all design tokens |
| `public/js/api.js` | The only module that talks to the service (bearer token in localStorage) |
| `public/js/money.js` | Formatting, decimal parsing and split shares (integers only) |
| `public/js/model.js`, `latest.js`, `retry.js` | Page data with latest-refresh-wins; retry identity for idempotent writes |
| `public/js/components/` | Shell, forms, feed and shared parts |
| `public/js/screens/` | One module per screen |
| `test/`, `browser-tests/` | API, unit and browser tests |

## Historical ledger (stage 3)

- Every user has an `opening_balance` (seeded balance minus the effect of the seeded payments;
  zero for signups). Every payment has an append-only list of revisions (`amount`,
  `effective_at`, `recorded_at`, `reason`, a global `seq`); revision 1 is the original, with
  `effective_at = recorded_at = created_at`. A correction appends a revision and moves the
  difference between the same two wallets in the same synchronous step.
- A view (`GET /me?as_of&known_at`, statements) selects, per payment, the latest revision
  recorded at or before `known_at` and applies it at its effective time. Holds are replayed from
  the authorization's creation, captures and release (`closed_at`, or the `expires_at` deadline).
  Nothing historical is cached; views are computed from the revisions.
- A correction is judged by walking every past boundary of both parties before and after the
  proposed revision: a boundary that would end below zero, and lower than it already was, is
  `historical_overdraft`.
- A statement read stores only its parameters (owner, window, `known_at`, resolved default `to`
  and the revision sequence reached) under an unguessable token; paging recomputes exactly that
  result, which stays frozen because revisions are append-only. Snapshots are exported and imported.
- Instants keep any fractional precision and are compared exactly; the service's own clock
  has millisecond precision and is frozen once per request. After a reset or an import the clock
  never reports an instant earlier than the state already holds.
- Import accepts the stage-1, stage-2 and stage-3 layouts (`state.layout: 3` for this one) and
  upgrades the older ones: revision 1 for every payment, opening balances, `closed_at`.

## Refunds and batch corrections (stage 4)

- A refund is a new payment (revision 1) from the target's receiver to its sender with
  `refund_of` set, funded from the receiver's available money; the sum of a payment's refunds may
  not exceed its current corrected amount, and a correction may not reduce a payment below what has
  been refunded. Refunds change no request, authorization, hold or settlement membership.
- Single corrections and batches share `src/corrections.js`: fields, eligibility (captures and
  refunds are immutable; settlement members only in a batch), net current-funds check, one shared
  `recorded_at`, the historical boundary walk over all proposed revisions together, one commit.
  A batch adds item order, settlement completeness (every member, one effective instant) and
  the operator permission. Batch revisions carry `correction_batch_id`.
- A saved statement snapshot remembers the payment layout it was taken under (`layout` 3 or 4) and
  pages in that layout, so a stage-3 token pages exactly the entries and fields it did before the
  upgrade; recorded idempotent responses are returned as recorded.
- Import accepts all four layouts; layout 4 adds refunds, `batches` and snapshot layouts, validated per leaf.

## Design choices

- **Storage**: one in-memory state object, replaced wholesale by reset and import. Node runs
  every request handler synchronously on a single event loop, so a handler that checks and
  changes balances without awaiting is atomic: debit and credit land together, no reader can see
  a negative balance, and idempotency claims, pay/decline/cancel races and settlements cannot
  interleave. State is ephemeral, as allowed by the specification.
- **Passwords**: scrypt with a random 16-byte salt per user (N=4096, r=8, p=1), verified with a
  constant-time comparison. The cost is modest so that resetting a fixture of a few hundred users
  stays well inside 10 s on 2 vCPU. Plaintext passwords are never stored or exported.
- **Idempotency**: records are keyed by user, method, path and key and hold the parsed request
  body and original response; only 201 responses are recorded, so a key whose request failed stays
  free. Bodies compare as JSON values.
- **Export**: the `state` holds users (with password hashes), tokens, payments, requests,
  settlements, operator grants, idempotency records and id counters, plus opening balances so that
  import can verify every balance against history. Tampered state is rejected with 422.
- **Limits**: heads up to 1 MiB, bodies up to 8 MiB (128 MiB for reset/import) and JSON nested up
  to 1000 levels are processed. Beyond a cap the answer is `422 validation_failed` with the standard
  error body (after authentication where the route needs it); `400 malformed_request` is only for
  bytes that are not valid JSON and wrong JSON types. Path parameters are percent-decoded before use.
- **Unknown routes and wrong methods** answer `404 not_found` (after authentication for the
  authenticated endpoint families).
- **Holds**: `user.held` is the sum of the remaining amounts of open authorizations; `available =
  total - held`. Every funds check (payments, request payments, settlements, new holds) uses
  `available`; a capture spends the money reserved for it. Expiry is derived from the clock: every
  request first closes open authorizations whose deadline has passed, so no timer is involved.
  Idempotent handlers stay synchronous so lookup, effect and record are one uninterrupted step.
- **Timestamps** carry milliseconds (`...:00.123+00:00`) so `expires_at` is exactly `created_at`
  plus the lifetime; seeded and imported timestamps are returned as given.
- **UI**: plain ES modules and one stylesheet, routed by URL with real navigation. The browser is a
  client of the documented JSON API only. An idempotency key belongs to the content of a form:
  submitting unchanged content re-sends the same key, changing a field makes a new key. A result
  that is not a 4xx with the error body (lost connection, 5xx, unreadable answer) is shown as
  uncertain, never as a refusal.
