# Pocketful, stage 2: wallet screens and payment authorizations

A containerised HTTP service (Node.js 20, standard library only, no npm dependencies) with the
stage-1 JSON API, the stage-2 authorization (hold and capture) API, and a browser UI served by the
same process. Every script, stylesheet and icon of the UI is in the image; nothing is fetched
from another origin.

## Build and start

```sh
docker build -t pocketful-stage2 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage2
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
(seven write paths), requests, splits, settlements, holds and captures, expiry by the clock,
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
| `src/state.js`, `src/idempotency.js`, `src/fixture.js`, `src/snapshot.js` | State, idempotency records, reset fixtures, export/import |
| `src/handlers/` | One module per endpoint family (`authorizations.js` is new in stage 2) |
| `public/index.html`, `public/css/app.css` | UI shell and the single stylesheet holding all design tokens |
| `public/js/api.js` | The only module that talks to the service (bearer token in localStorage) |
| `public/js/money.js` | Formatting, decimal parsing and split shares (integers only) |
| `public/js/model.js`, `latest.js`, `retry.js` | Page data with latest-refresh-wins; retry identity for idempotent writes |
| `public/js/components/` | Shell, forms, feed and shared parts |
| `public/js/screens/` | One module per screen |
| `test/`, `browser-tests/` | API, unit and browser tests |

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
- **Timestamps**: whole seconds with `+00:00`, non-decreasing across the process.
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
- **Timestamps** now carry milliseconds (`...:00.123+00:00`) so `expires_at` is exactly `created_at`
  plus the lifetime; seeded and imported timestamps are returned as given.
- **UI**: plain ES modules and one stylesheet, routed by URL with real navigation. The browser is a
  client of the documented JSON API only. An idempotency key belongs to the content of a form:
  submitting unchanged content re-sends the same key, changing a field makes a new key. A result
  that is not a 4xx with the error body (lost connection, 5xx, unreadable answer) is shown as
  uncertain, never as a refusal.
