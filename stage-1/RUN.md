# Pocketful stage 1 — payments and settlements

HTTP service (Python 3.12, standard library only, in-memory state). Spec: `pocketful/spec/stage-1.md`.

## Build and run

```sh
docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

Run it from this folder (`stage-1/`). No volume, compose file, second container or network is
needed at run time; the image has no third-party dependencies. `PORT` defaults to `8080`; the
service listens on `0.0.0.0` and answers `GET /health` within about a second of start.

State is ephemeral and lives in the process: `POST /_test/reset` replaces it from a fixture,
`GET /_test/export` and `POST /_test/import` move it between containers.

## Tests

```sh
cd tests && PYTHONPATH=..:. python3 -m unittest test_core test_flows     # spec-derived suites
python3 tests/container_check.py <portA> <portB>                          # load/cross-container, two running containers
```

## Where each part lives (`app/`)

| Module | Job |
|---|---|
| `main.py` | entry point, reads `PORT` |
| `server.py` | HTTP transport: body reading, JSON error bodies for framework errors, 5xx guard |
| `routes.py` | route table and dispatch (unknown route/method → 404 `not_found`) |
| `request.py` | request object and bearer authentication |
| `errors.py` | `ApiError` and constructors for the error codes |
| `jsonutil.py` | JSON parse/serialise, integral-number rule, JSON-value equality |
| `fields.py` | field validation (amount, note, visibility, handles, `limit`/`offset`) |
| `store.py` | in-memory state, global lock, state dump/load (export/import validation) |
| `fixture.py` | reset-fixture validation and Store construction |
| `ledger.py` | the only writer of balances, payments and requests |
| `idempotency.py` | the five idempotent write paths' key logic |
| `passwords.py` | scrypt hashing (cost tuned for 200 seeded users inside 10 s) |
| `money.py` | equal-split shares |
| `views.py`, `clock.py` | public payment/request shapes; RFC 3339 timestamps |
| `handlers_*.py` | endpoints: auth, payments (+`/me`, `/activity`), requests, splits, settlements, test control |

## Design notes

- One global lock serialises every state change; each handler validates first and mutates last, so
  failures leave no trace and balances never go negative or out of sum, even transiently.
- Idempotency records are keyed by (user, method, path, key) and stored only after success, so a
  key that failed with 4xx is a first use again, and the same key on another path is independent.
- Handles are matched exactly (no case folding or trimming); "characters" are Unicode code points.
- Seeded payments/requests are stamped with the reset time; creation order breaks ties.
- Export holds users with scrypt hashes (never plaintext), tokens, payments, requests, splits,
  settlements, operators and all idempotency records; import rebuilds the state atomically.
