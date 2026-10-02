# Pocketful stage 2 — run instructions

Wallet screens in the browser plus payment authorizations (holds and captures).
Pure Python 3.12 standard library on the server; the UI is plain ES modules and CSS
with system fonts. Nothing is fetched from another origin, and no network is
needed at run time.

## Build and start

    docker build -t pocketful-stage-2 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-2

`PORT` defaults to `8080`; the service listens on `0.0.0.0:$PORT`. Open
`http://localhost:8080/` for the UI (`/`, `/requests`, `/split`, `/authorizations`,
`/signup`, `/login`). The API is on the same origin; `/requests` and
`/authorizations` return the UI for `Accept: text/html` and JSON otherwise.

## Tests

    python3 -m unittest discover -s tests -t . -v          # API tests (in-process server)
    python3 tests/load_check.py http://127.0.0.1:8080 [second-url]   # limits, 50-way bursts, export -> import
    <python with playwright> tests/ui_check.py STAGE2_URL [STAGE1_URL] [screenshot-dir]   # browser checks

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
| `pocketful/holds.py` | holds: `held`, `available = total - held`, closing and clock expiry |
| `pocketful/ledger.py` | moving money; payment and request records (funds checks use `available`) |
| `pocketful/idempotency.py` | the seven idempotent write paths |
| `pocketful/fixture.py` | reset fixture -> state (users, payments, requests, authorizations, TTL) |
| `pocketful/statecheck.py`, `statebase.py` | validation of exported/imported state (stage-1 exports are upgraded with defaults) |
| `pocketful/handlers/` | one module per API area: `auth`, `me`, `payments`, `requests`, `splits`, `settlements`, `activity`, `authorizations`, `testctl`, `ui` |
| `pocketful/ui/index.html`, `styles.css` | the page shell and the visual system |
| `pocketful/ui/js/app.js` | client router and bootstrap; `header.js` navigation and current user |
| `pocketful/ui/js/api.js` | the only network code: bearer token, result kinds (ok / refused / uncertain), idempotency keys |
| `pocketful/ui/js/money.js` | exact decimal <-> minor units, equal-split preview |
| `pocketful/ui/js/components.js`, `feed.js`, `session.js`, `dom.js` | wallet card, send forms, feed, session state, element builder |
| `pocketful/ui/js/pages/` | one module per screen: `home`, `requests`, `split`, `authorizations`, `auth` |
| `tests/` | own tests |

## Design notes

* One process-wide lock serialises every state change; `available` is derived from
  open holds on every read, and clock expiry is applied at the start of every request.
* Authorizations: `expires_at = created_at + ttl` where `created_at` is rounded up to
  a whole second, so a hold never lives shorter than its TTL. A capture moves money
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
* Limits: request line and header lines 64 KiB, at most 100 headers, body 64 MiB, 30 s
  to receive a request; each excess answers a JSON error body.
* Passwords: scrypt (N=4096, r=8, p=1, per-user salt).
