# Pocketful, stage 1: payments and settlements

A containerised HTTP service (Node.js 20, standard library only, no npm dependencies).

## Build and start

```sh
docker build -t pocketful-stage1 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage1
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` within a
second of start. It needs no network at run time and no manual setup; seed data comes from
`POST /_test/reset`.

## Tests

Need Node 20 or newer on the host, no installs:

```sh
npm test        # node --test test/
```

The tests start the service in-process and cover validation, precedence of errors,
idempotency, requests, splits, settlements, export/import and 50-way concurrency bursts.

## Where things live

| Path | Job |
|---|---|
| `src/server.js` | HTTP bootstrap, body reading, JSON response writing |
| `src/pipeline.js` | Per-request order of checks: auth, operator, idempotency key, body parse, replay, handler |
| `src/routes.js` | Route table: which endpoints exist, body mode, idempotency, operator flags |
| `src/validation.js` | The one place for field rules (amount, note, visibility, paging) |
| `src/ledger.js` | The one place balances change: payments, net settlements, equal-split shares |
| `src/state.js` | The complete in-memory state and id generation |
| `src/idempotency.js` | Idempotency records and replay/conflict decisions |
| `src/fixture.js` | Reset fixture validation and state construction |
| `src/snapshot.js` | `GET /_test/export` / `POST /_test/import` document, with consistency checks |
| `src/passwords.js`, `src/handles.js`, `src/json.js`, `src/clock.js`, `src/errors.js`, `src/serializers.js` | Small helpers |
| `src/handlers/` | One module per endpoint family |
| `test/` | Automated tests (`node:test`) |

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
- **Limits**: request bodies over 2 MiB (128 MiB for reset/import) and JSON nested deeper than
  200 levels answer `400 malformed_request`.
- **Unknown routes and wrong methods** answer `404 not_found` (after authentication for the
  authenticated endpoint families).
