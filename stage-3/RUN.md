# Pocketful — stage 3 (statements and payment corrections)

A dependency-free Python 3.12 HTTP service (standard library only) that serves the JSON API and a
browser UI written in plain JavaScript (ES modules, no build step, no CDN, no web fonts). State is
held in memory. Stage 3 extends stage 2 (and 1) with a temporal ledger; `stage-1/` and `stage-2/` are unchanged. The UI is the stage-2 UI, unchanged.

## Build and start

From this folder:

    docker build -t pocketful-stage-3 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-3

`PORT` defaults to 8080; the service listens on `0.0.0.0`. No compose file, no network at run
time. Check: `curl localhost:8080/health` → `{"status":"ok"}`, then open <http://localhost:8080/>.

`/requests` and `/authorizations` are shared between the UI and the API: `Accept: text/html` (a
browser navigation) returns the screen, any other request returns JSON.

## Tests

API tests, from this folder with a local Python 3.12 (no packages needed):

    python3 -m unittest discover -s tests -t .

Browser tests (Playwright; use the interpreter that has it, e.g. the kickoff checkout's `.venv`).
They also write screenshots of every route at 375 px and 1280 px to `$SHOT_DIR` (default `/tmp/pf-shots`):

    /path/to/.venv/bin/python -m unittest discover -s tests/browser -t . -v

Both start the service in-process on a free port and talk to it over HTTP.

## Where things live

| Path | Job |
|---|---|
| `app/server.py`, `app/__main__.py` | socket/HTTP plumbing, body reading, JSON and static responses, entry point |
| `app/router.py` | route table and the request pipeline (auth → body → idempotency key → handler); serves UI pages by content negotiation |
| `app/web.py` | UI page shell, static assets under `app/ui/`, `Accept: text/html` negotiation |
| `app/idempotency.py` | key validation, replay / reuse detection, recording of 2xx outcomes |
| `app/store.py` | in-memory `State`, the single global lock (`Holder`), id generation |
| `app/ledger.py` | money movement (debit+credit), payment/request record builders, equal split |
| `app/history.py` | the temporal ledger: selected revision under `known_at`, balance/holds as of an instant, statement window arithmetic, historical-overdraft sweep |
| `app/holds.py` | authorization holds: held/available per wallet, clock expiry, record builder |
| `app/fixture.py` | build state from a `/_test/reset` fixture (incl. `authorization_ttl_seconds`, `authorizations`) |
| `app/snapshot.py` | `/_test/export` document and validated `/_test/import` (accepts stage-1 exports) |
| `app/validation.py`, `app/jsonutil.py`, `app/errors.py`, `app/clock.py`, `app/passwords.py` | field rules, exact JSON parsing + canonical form, error type, timestamps, scrypt hashing |
| `app/handlers/` | one module per resource: `auth`, `me` (incl. `as_of`/`known_at`), `payments`, `corrections` (+ revisions), `statement` (+ snapshots), `requests`, `splits`, `activity`, `settlements`, `authorizations`, `testctl` |
| `app/ui/index.html`, `app/ui/css/app.css` | the single HTML shell and the design system (colours, spacing, controls, states) |
| `app/ui/js/main.js`, `layout.js`, `session.js`, `api.js`, `money.js`, `dom.js` | entry/routing by URL, page frame, sign-in state, fetch wrapper with idempotency keys, decimal<->minor units, DOM helpers |
| `app/ui/js/pages/` | one module per screen: `wallet` (`/`), `requests`, `split`, `authorizations`, `auth` (`/login`, `/signup`) |
| `app/ui/js/components/` | `moneyform` (pay/request/authorise form with retry identity), `feed`, `wallet` (balance block), `badges` |
| `tests/` | own API tests (`test_history.py`: timestamps, `as_of`, statements, snapshots; `test_corrections.py`: corrections, overdraft, hold history, cross-stage import); `tests/browser/` own Playwright tests of the stage-2 UI |

## Design notes

- One global lock serialises every state access, so balances never go negative, the total is
  conserved, a request pays once, a hold is captured at most up to its amount and idempotent
  writes take effect once. Password hashing runs outside the lock.
- Holds: `available = total - held`; held is the sum of `remaining_amount` of open authorizations.
  Expiry is evaluated lazily under the lock before every authenticated request, export and
  reset, so reads are clock-correct without a background timer. `balance` equals `total`.
- Idempotency claims are keyed by (user, method, path, key); the stored body is a canonical
  JSON string, so key order and whitespace do not matter. Only 2xx outcomes are recorded.
- Passwords are scrypt-hashed; tokens are random and never expire.
- Export dumps the whole state (users with hashes, tokens, payments, requests, splits,
  settlements, authorizations, idempotency records, operators, ttl); import validates then swaps
  it in atomically and defaults the stage-2 fields when given a stage-1 export.
- A zero split share creates a request for `0`, which can be paid as a zero-amount payment.
- UI: client-rendered by ES modules, one full page load per route. The session token lives in
  `localStorage`. Every money-moving form keeps an *attempt* (exact body + idempotency key): the
  same body reuses the key, a confirmed success makes an unchanged resubmit a no-op, a lost
  response shows "uncertain" and the retry replays with the same key, any changed field mints a
  new key. Data refreshes go through a latest-wins guard so a slow earlier read never overwrites a
  later one. The authorise form is on both `/` and `/authorizations`; the capture button
  performs a final capture of the typed amount (extended `final:false` captures are API-only).
- Stage 3 ledger: every payment keeps an append-only revision list (revision 1 = original amount,
  effective = recorded = `created_at`). A balance at (T = `as_of`, K = `known_at`) is the wallet's
  opening balance plus, for each of its payments, the latest revision recorded at or before K, applied
  if effective at or before T. Current balances are maintained incrementally (a correction moves the
  difference between the same two wallets) and equal the (now, now) view. Opening balances are fixed
  at reset (seeded ending balance minus the net of the original seeded payments), 0 at signup, derived
  on import of an earlier-stage export.
- Holds keep a lifecycle (`start`, captures, `end`) so a hold can be reconstructed at any instant under
  any K: creation and captures are known at their time, a void/final capture from its time, the expiry
  deadline as soon as creation is known. `closed_at` is exposed on authorizations.
- A correction is rejected `historical_overdraft` if, under the latest revisions, total or available
  (total - held) is negative at any past boundary of either party; same-instant events are combined.
  `insufficient_funds` (current `available`) is checked first. Order: field validation, linked payment
  (settlement member / capture), stale revision, insufficient funds, historical overdraft.
- `now()` is strictly increasing and carries microseconds, so timestamps are exact instants. Statement
  snapshots are frozen results (compact rows) held in memory until reset and are part of the exported
  state: a token issued before `GET /_test/export` pages the same result after `POST /_test/import`;
  tokens absent from the imported state are 404. Memory/export bounds (50 000 snapshots, 600 000
  rows) only drop the oldest tokens far beyond ordinary use; 400 000 rows export in under 1 s.
- A raw `+` in an `as_of`/`known_at` query value (decoded to a space) is repaired to `+`.
