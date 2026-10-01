# Pocketful — stage 1 (payments and settlements)

A single-process HTTP service. State is held in memory only and does not survive a restart.
No runtime dependencies and no outbound network access are needed.

## Build and start (one command)

From this folder (`stage-1/`):

```sh
docker build -t pocketful-stage-1 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-1
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` with
`{"status":"ok"}` within a second of start. Seed or clear state with `POST /_test/reset`.

## Tests

Node.js 18+ is enough (no `npm install` is needed; there are no dependencies):

```sh
npm test            # unit + HTTP tests, starts its own server on a free port
```

Inside the image, without Node on the host:

```sh
docker run --rm --entrypoint node pocketful-stage-1 --test test/*.test.js
```

Two containers with no network, moving state with export/import:

```sh
bash test/docker-smoke.sh
```

Point the tests at an already running instance with `TEST_BASE_URL=http://127.0.0.1:8080`
(the tests reset state, so use a scratch instance).

## Layout

| Path | Role |
|---|---|
| `src/server.js` | routing and request pipeline (auth, idempotency, error envelope) |
| `src/ledger.js` | payments, requests, splits, settlements (synchronous, single writer) |
| `src/state.js` | in-memory state and public record shapes |
| `src/validate.js`, `src/json.js` | field validation, strict JSON parsing, canonical bodies |
| `src/fixture.js` | `POST /_test/reset` validation and state construction |
| `src/snapshot.js` | `GET /_test/export` / `POST /_test/import` (state has its own `schema_version`) |
| `src/passwords.js` | scrypt hashing on the thread pool |

## Design notes

- All money movement happens in one synchronous step on a single thread, so every request is
  serialisable, balances are never transiently negative, and concurrent identical requests
  produce exactly one `201` without locks.
- Password hashing (scrypt) is asynchronous and never blocks the event loop.
- Idempotency records are keyed by user + method + path + key and store the canonical request
  body and the original response text; they are part of the exported state.
