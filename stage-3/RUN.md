# Pocketful — stage 2 (wallet screens and payment authorizations)

One process, state in memory only (it does not survive a restart), no runtime dependencies and no
outbound network access. It serves the JSON API **and** the browser UI (static files read from
`public/` at start-up; no CDN, web fonts or external URLs).

## Build and start (one command)

From this folder (`stage-2/`):

```sh
docker build -t pocketful-stage-2 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-2
```

Then open <http://localhost:8080/>. The service listens on `0.0.0.0:$PORT` (default `8080`);
`GET /health` answers `{"status":"ok"}`. Seed or clear state with `POST /_test/reset`.

Screens: `/` (balance, pay / request / hold forms, activity feed), `/requests`, `/split`,
`/authorizations`, `/signup`, `/login`. `/requests` and `/authorizations` are shared with the API:
`Accept: text/html` gets the screen, anything else gets JSON.

## Tests

API, unit and module tests (Node.js 18+, no `npm install` needed; no dependencies):

```sh
npm test            # starts its own server on a free port
```

Inside the image, without Node on the host:

```sh
docker run --rm --entrypoint node pocketful-stage-2 --test test/*.test.js
```

Browser tests (Python Playwright; the kickoff virtualenv already has it). Start the image detached, run
the tests against it, and stop it:

```sh
docker run -d --name pf2 -p 18080:8080 pocketful-stage-2
cd test/ui && BASE_URL=http://127.0.0.1:18080 <kickoff>/.venv/bin/python -m pytest -q
docker rm -f pf2
# screenshots of every screen at 375 px and 1280 px:
BASE_URL=http://127.0.0.1:18080 <kickoff>/.venv/bin/python shots.py /tmp/pocketful-shots
```

The upgrade tests start a real stage-1 service from `../stage-1` with `node`. Two containers, no
network, state moved by export/import:

```sh
bash test/docker-smoke.sh      # stage 2 -> stage 2
bash test/docker-upgrade.sh    # stage-1 image -> stage-2 image
```

## Layout

| Path | Role |
|---|---|
| `src/server.js` | routing, auth, idempotency pipeline, content negotiation |
| `src/ledger.js` | payments, requests, splits, settlements, authorizations (synchronous, single writer) |
| `src/state.js` | in-memory state, holds (`heldOf`/`availableOf`), clock-derived expiry (`sweep`) |
| `src/fixture.js`, `src/snapshot.js` | reset validation; export/import (state `schema_version` 2; accepts stage-1's version 1) |
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
- Timestamps created by this service carry millisecond precision (`…:03.123+00:00`).
- The pay forms' idempotency key follows the form content (`lib/retry.js`); a response that is a 4xx
  envelope is a refusal, anything else that is not a clean 2xx is "uncertain" and keeps the form retryable.
- Every refresh carries a sequence number; a late response never overwrites a later one.
