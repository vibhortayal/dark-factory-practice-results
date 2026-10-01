# Pocketful — stage 4 (refunds and batch corrections)

One process, state in memory only (it does not survive a restart), no runtime dependencies and no
outbound network access. It serves the JSON API (payments, requests, splits, settlements, authorizations, statements, corrections, refunds, correction batches) **and** the browser UI (static files read from
`public/` at start-up; no CDN, web fonts or external URLs).

## Build and start (one command)

From this folder (`stage-4/`):

```sh
docker build -t pocketful-stage-4 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-4
```

Then open <http://localhost:8080/>. The service listens on `0.0.0.0:$PORT` (default `8080`);
`GET /health` answers `{"status":"ok"}`. Seed or clear state with `POST /_test/reset`.

Screens: `/` (balance, pay / request / hold forms, activity feed), `/requests`, `/split`,
`/authorizations`, `/signup`, `/login`. `/requests` and `/authorizations` are shared with the API:
`Accept: text/html` gets the screen, anything else gets JSON.

## What stage 4 adds

- `POST /payments/{id}/refunds` (idempotent): the original receiver refunds a payment, a request payment, a capture or a settlement member, cumulatively up to the payment's current corrected amount; a refund is an ordinary payment in the opposite direction carrying `refund_of`.
- `POST /correction-batches` (idempotent, settlement operators only): 1 to 32 corrections applied as one atomic step with one shared `recorded_at`; settlement members only as a complete set with one effective instant.
- Every payment carries `refund_of`; every revision carries `correction_batch_id`; state `schema_version` is 4 and import accepts 1 to 4.
- Stage-3 behaviour is unchanged (statements, `as_of`/`known_at`, snapshots, single-payment corrections).

## What stage 3 added (still in force)

- `GET /me?as_of=&known_at=` and `GET /statement?from=&to=&known_at=&limit=&offset=` / `?snapshot=` over an append-only history.
- `POST /payments/{id}/corrections` (an idempotent write path, `expected_revision` checked) and `GET /payments/{id}/revisions`.
- `closed_at` on authorizations; historical holds in every view; generated payment ids are fixed width.
- `POST /_test/import` accepts exports from the stage-1, stage-2, stage-3 and stage-4 services (state `schema_version` 1 to 4).

## Tests

API, unit and module tests (Node.js 18+, no `npm install` needed; no dependencies):

```sh
npm test            # starts its own server on a free port
```

Inside the image, without Node on the host:

```sh
docker run --rm --entrypoint node pocketful-stage-4 --test test/*.test.js
```

Browser tests (Python Playwright; the kickoff virtualenv already has it; the stage-2 screens are unchanged). Start the image detached, run
the tests against it, and stop it:

```sh
docker run -d --name pf4 -p 18080:8080 pocketful-stage-4
cd test/ui && BASE_URL=http://127.0.0.1:18080 <kickoff>/.venv/bin/python -m pytest -q
docker rm -f pf4
# screenshots of every screen at 375 px and 1280 px:
BASE_URL=http://127.0.0.1:18080 <kickoff>/.venv/bin/python shots.py /tmp/pocketful-shots
```

The upgrade tests start real stage-1, stage-2 and stage-3 services from the sibling folders with `node`
(skipped inside the image, where those folders are absent). Two containers, no network, state moved by
export/import:

```sh
bash test/docker-smoke.sh        # stage 4 -> stage 4
bash test/docker-upgrade.sh      # stage-1, then stage-2, then stage-3 image -> stage-4 image
```

## Layout

| Path | Role |
|---|---|
| `src/server.js` | routing, auth, idempotency pipeline, content negotiation |
| `src/ledger.js` | payments, requests, splits, settlements, authorizations, corrections (synchronous, single writer) |
| `src/corrections.js` | single-payment corrections and operator batches: one plan / check / commit path |
| `src/history.js` | pure views over the history: selected revisions, hold timelines, statements, historical-overdraft check |
| `src/queries.js` | `GET /me` with `as_of`/`known_at`, `GET /statement`, statement snapshots |
| `src/instants.js` | exact RFC 3339 parsing (BigInt nanoseconds), raw query parsing |
| `src/state.js` | in-memory state, holds (`heldOf`/`availableOf`), clock-derived expiry (`sweep`) |
| `src/fixture.js`, `src/snapshot.js` | reset validation; export/import (state `schema_version` 4; accepts versions 1 to 3 too) |
| `src/json.js` | strict parsing; amount literals judged on their exact decimal value |
| `src/ui.js` | serves `public/` |
| `public/assets/js/money.js`, `split.js` | decimal parse/format and the equal-split rule; `split.js` is imported by the server too |
| `public/assets/js/views/*`, `lib/*` | one module per screen; API client, retry identity, feedback |
| `public/assets/style.css` | the design system (tokens, components) |

## Design notes

- Money moves in one synchronous step on a single thread, so every request is serialisable and
  `available = total − held` can never be observed negative.
- Expiry is derived from the clock on every request (`sweep`), never from a timer.
- A hold's remaining amount is `amount − captured_amount` while it is open; `held` is the sum of
  those for the payer's open holds. Every `insufficient_funds` test uses `available`.
- Timestamps created by this service are real-clock readings with six fractional digits (`…:03.123000+00:00`); records created in the same tick share an instant and are ordered by sequence (fixed-width payment ids, `kseq`). Only a correction's `recorded_at` is bumped (by one microsecond past that payment's previous one).
- The pay forms' idempotency key follows the form content (`lib/retry.js`); a response that is a 4xx
  envelope is a refusal, anything else that is not a clean 2xx is "uncertain" and keeps the form retryable.
- Every refresh carries a sequence number; a late response never overwrites a later one.
- A refund is created by the same ledger step as a payment (debit the receiver's available funds, credit the sender) and
  keeps a running refunded total on its target, which bounds later refunds and corrections against the latest revision.
- A batch is planned against current state without mutating anything: shape, items in input order, settlement
  completeness and instants, combined current available funds, historical total/available with every proposal applied
  together; only then are all revisions appended in one synchronous step (one `recorded_at`, one knowledge position).
- Two ledgers of truth, one writer: current balances are maintained incrementally (every earlier path is untouched);
  beside them an append-only history (payment revisions, authorization events) feeds the temporal views. With no
  parameters the view at "now" equals the maintained balance (a property test compares them against a brute-force replay).
- "Known" is decided by a knowledge sequence number, never by comparing clock readings; `recorded_at` strictly increases per
  payment (bumped by 1 µs when needed), nothing else is ever bumped.
- Client instants are parsed to exact BigInt nanoseconds; a raw `+` in an instant query parameter is a plus sign.
- A statement snapshot is a token over (caller, window, `known_at`, knowledge position); the frozen result is recomputed from
  immutable history, so a token costs constant memory and survives export/import.
