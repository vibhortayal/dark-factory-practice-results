# Tablekeeper stage 1 — run instructions

## Build and start (no manual setup)

```sh
docker build -t tablekeeper-stage1 .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage1
```

`PORT` defaults to 8080. The service listens on `0.0.0.0:$PORT`, is healthy
within about a second (`GET /health`) and needs no network at run time.
State is in memory only (ephemeral by design). `docker-compose.yml` is not used.

## Technology and reasons

Python 3.12, standard library only (`http.server.ThreadingHTTPServer`, `hashlib.scrypt`,
`zoneinfo`) plus the `tzdata` package installed at image build time, so IANA rules ship in the
image. In-memory storage behind one global lock makes every mutation (occupancy check + write +
idempotency record) atomic; the workload is tiny so the lock is not a bottleneck.
Passwords: scrypt (N=2^13, r=8, p=1), random salt. Bearer tokens are random and stored
only as SHA-256 digests (so exports contain no plaintext passwords or raw tokens, yet existing
tokens stay valid after import).

## Where each part lives (`app/`)

| Module | Job |
|---|---|
| `server.py` | HTTP transport, body reading, error envelope, `PORT` |
| `router.py` | Route table, per-endpoint glue, auth/key ordering |
| `errors.py` | `ApiError` and helpers for the error codes |
| `jsonutil.py` | JSON parsing, JSON-value canonical form for idempotency |
| `timeutil.py` | Time zones, DST resolution (gap/fold), RFC 3339 rendering |
| `store.py` | In-memory state, lock, indexes |
| `accounts.py` | Signup, login, password hashing, bearer auth |
| `idempotency.py` | `Idempotency-Key` header rules and records |
| `scheduling.py` | Opening hours, slot grid, capacity, overlap checks |
| `catalog.py` | `GET /restaurants`, `/restaurants/{id}`, `/availability` |
| `bookings.py` | Create, list, get, cancel, PATCH |
| `moves.py` | `POST /reservation-moves` |
| `fixture.py` | `POST /_test/reset` validation and state building |
| `snapshot.py` | `GET /_test/export`, `POST /_test/import` |
| `views.py` | Response shapes |

## Tests

`tests/test_api.py` is a black-box suite against a running service:

```sh
docker run -d --rm --name tk -e PORT=8080 -p 18080:8080 tablekeeper-stage1
BASE_URL=http://localhost:18080 python3 -m unittest discover -s tests -v
docker stop tk
```

## Design choices

Validation order follows the acceptance map decisions X1–X10 (auth, idempotency key, JSON object,
idempotency resolution, field types 400, required/format 422, 404, then
`invalid_local_time`, `not_on_slot_grid`, `outside_opening_hours`, `party_exceeds_capacity`,
`table_unavailable`). Only 201 responses are recorded for idempotency, keyed by
(user, method, path, key). `party_size` JSON floats (even `4.0`) are rejected as not integers.
