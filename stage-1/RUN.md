# Tablekeeper — stage 1 (reservations)

## Build and start (one command)

```sh
docker build -t tablekeeper-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-1
```

Run it from this folder (`stage-1/`). No manual setup, no network at run time (the only
dependency, `tzdata`, is installed into the image at build time). `PORT` defaults to 8080.
State is in memory and is lost when the container stops.

Check: `curl localhost:8080/health` -> `{"status": "ok"}`.

## Layout (`app/`)

| Module | Job |
|---|---|
| `server.py`, `__main__.py` | Threaded stdlib HTTP server, JSON in/out, uniform error body |
| `router.py` | Route table, `Request`, bearer authentication, dispatch under the global lock |
| `state.py` | In-memory `Data` plus the single global lock; id/reference generators |
| `snapshot.py` | Build state from a reset fixture or an export; produce an export |
| `admin.py` | `POST /_test/reset`, `GET /_test/export`, `POST /_test/import` |
| `accounts.py`, `auth.py` | Signup/login; scrypt hashing and token creation |
| `catalog.py` | `GET /restaurants`, `/restaurants/{id}`, `/availability` |
| `scheduling.py` | Opening hours, slot grid, DST-aware slot checks, occupancy overlap |
| `bookings.py` | Create, list, get, cancel, amend, and `POST /reservation-moves` |
| `idempotency.py` | `Idempotency-Key` handling shared by the two write paths |
| `timeutil.py`, `validate.py`, `jsonutil.py`, `errors.py` | Small shared helpers |

## Design notes

- All state access happens under one global lock, so double booking and exactly-once
  idempotency hold under concurrent requests. Password hashing (scrypt) runs outside it.
- Emails are case-insensitive for signup uniqueness and login.
- Booking error precedence: body shape (400/422) -> unknown restaurant/table (404) ->
  `invalid_local_time` -> `not_on_slot_grid` -> `outside_opening_hours` ->
  `party_exceeds_capacity` -> `table_unavailable` (409). Amend/moves put
  `reservation_cancelled` and `cutoff_passed` before the semantic checks.
- Closing time and durations are compared on absolute instants.

## Tests

`python3 -m unittest discover -s tests` (starts the app in-process on a free port; needs
Python 3.12 and `tzdata` or system zoneinfo).
