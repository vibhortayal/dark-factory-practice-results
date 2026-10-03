# Pocketful — stage 1 (payments and settlements)

A dependency-free Python 3.12 HTTP service (standard library only). State is held in memory.

## Build and start

From this folder:

    docker build -t pocketful-stage-1 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-1

`PORT` defaults to 8080; the service listens on `0.0.0.0`. No compose file, no network at run
time. Check: `curl localhost:8080/health` → `{"status":"ok"}`.

## Tests

Run from this folder with a local Python 3.12 (no packages needed):

    python3 -m unittest discover -s tests -t .

The tests start the service in-process on a free port and talk to it over HTTP.

## Where things live

| Path | Job |
|---|---|
| `app/server.py`, `app/__main__.py` | socket/HTTP plumbing, body reading, JSON responses, entry point |
| `app/router.py` | route table and the request pipeline (auth → body → idempotency key → handler) |
| `app/idempotency.py` | key validation, replay / reuse detection, recording of 2xx outcomes |
| `app/store.py` | in-memory `State`, the single global lock (`Holder`), id generation |
| `app/ledger.py` | money movement (debit+credit), payment/request record builders, equal split |
| `app/fixture.py` | build state from a `/_test/reset` fixture |
| `app/snapshot.py` | `/_test/export` document and validated `/_test/import` |
| `app/validation.py`, `app/jsonutil.py`, `app/errors.py`, `app/clock.py`, `app/passwords.py` | field rules, exact JSON parsing + canonical form, error type, timestamps, scrypt hashing |
| `app/handlers/` | one module per resource: `auth`, `me`, `payments`, `requests`, `splits`, `activity`, `settlements`, `testctl` |
| `tests/` | own tests written from the specification |

## Design notes

- One global lock serialises every state access, so balances never go negative, the total is
  conserved, a request pays once and idempotent writes take effect once. Password hashing runs
  outside the lock.
- Idempotency claims are keyed by (user, method, path, key); the stored body is a canonical
  JSON string, so key order and whitespace do not matter. Only 2xx outcomes are recorded.
- Passwords are scrypt-hashed; tokens are random and never expire.
- Export dumps the whole state (users with hashes, tokens, payments, requests, splits,
  settlements, idempotency records, operators); import validates then swaps it in atomically.
- A zero split share creates a request for `0`, which can be paid as a zero-amount payment.
