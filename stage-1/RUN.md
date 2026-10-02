# Pocketful stage 1 — run instructions

Pure Python 3.12 standard library; no dependencies, no network needed at run time.

## Build and start

    docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1

`PORT` defaults to `8080`; the service listens on `0.0.0.0:$PORT`.
Check it: `curl localhost:8080/health` -> `{"status": "ok"}`.

## Tests (own, black-box over HTTP against an in-process server)

    python3 -m unittest discover -s tests -t . -v

## Where things live

| Path | Job |
|---|---|
| `pocketful/server.py`, `__main__.py` | HTTP plumbing, JSON responses, `PORT` |
| `pocketful/router.py` | route table, auth-or-not, 404/405 |
| `pocketful/request.py` | request object, strict JSON object parsing |
| `pocketful/errors.py` | `ApiError` and the error constructors |
| `pocketful/validation.py` | amount, note, visibility, handle lists, `limit`/`offset` |
| `pocketful/store.py` | the one JSON-shaped state dict, its lock, lookup indexes |
| `pocketful/statecodec.py` | reset-fixture and import validation -> state |
| `pocketful/idempotency.py` | the five idempotent write paths (§7) |
| `pocketful/ledger.py` | moving money; building payment and request records |
| `pocketful/passwords.py` | salted scrypt hashing |
| `pocketful/timefmt.py` | RFC 3339 timestamps with numeric offset |
| `pocketful/handlers/auth.py` | signup, login, bearer authentication |
| `pocketful/handlers/me.py`, `payments.py`, `requests.py`, `splits.py`, `settlements.py`, `activity.py` | one module per API area |
| `pocketful/handlers/testctl.py` | `/_test/reset`, `/_test/export`, `/_test/import` |
| `tests/` | own unittest suite |

## Design notes

* One process-wide lock serialises every state change, so balances never go
  negative, money is conserved, and a request pays at most once.
* Every state change is made only after all validation and the funds check.
* Idempotency records are keyed by (user, path, key) and hold the canonical body
  and the original response; they are part of the exported state.
* Passwords: scrypt (N=4096, r=8, p=1, per-user salt) so 50 concurrent logins and
  a few hundred seeded users stay well within 5 s / 10 s on 2 vCPU.
