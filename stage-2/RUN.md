# Tablekeeper — stage 2 (online booking and combined tables)

## Build and start (one command)

```sh
docker build -t tablekeeper-stage-2 . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-2
```

Run it from this folder (`stage-1/`). No manual setup, no network at run time (the only
dependency, `tzdata`, is installed into the image at build time). `PORT` defaults to 8080.
State is in memory and is lost when the container stops.

Check: `curl localhost:8080/health` -> `{"status": "ok"}`.

## Layout (`app/`)

| Module | Job |
|---|---|
| `web.py`, `web/` | The browser UI: `layout.html` + one HTML file per screen (`/`, `/signup`, `/login`, `/lookup`), `app.css`, and JS — `common.js` (API client, session, header), `search.js` (grid + booking form), `auth.js`, `lookup.js`. Served from the image, no external resources |
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
  `party_exceeds_capacity` -> `table_unavailable` (409). PATCH order: unparseable body (400) ->
  404 (not the caller's) -> `reservation_cancelled` -> `cutoff_passed` -> field validation ->
  semantic checks -> occupancy. `POST /reservation-moves`: batch shape (422) -> 404 / mixed
  restaurants (422) -> per booking in input order (cancelled, cutoff, field validation,
  semantic checks) -> occupancy over the whole batch.
- Reset fixtures: wrong JSON type of a field -> 400 `malformed_request`; right type but invalid
  value -> 422; import state problems are always 422.
- Closing time and durations are compared on absolute instants.

## Tests

`python3 -m unittest discover -s tests` (API; starts the app in-process on a free port; needs
Python 3.12 and `tzdata` or system zoneinfo).

Browser checks (Chromium via Playwright, e.g. from the kickoff checkout's venv):
`<kickoff>/.venv/bin/python tests/browser_checks.py [screenshot-dir]`.

## Stage 2 additions

- **Combined tables.** Fixture `combinable` is an optional list of table-id pairs (pairs only, not
  transitive). `table_ids` is accepted on `POST /reservations`, `PATCH` and moves; `table_id` still
  means a set of one. Responses always carry `table_ids` and carry `table_id` only for one table.
  A pair is stored and returned in `combinable` order. Reservations are stored as a table list;
  stage-1 exports (`table_id` only, no `combinable`) import unchanged and their stored receipts replay
  verbatim. `GET /restaurants/{id}` echoes `combinable` only if the fixture had it.
- **Booking error precedence** (adds `combination_not_allowed`): shape (400/422: both table keys, empty or
  duplicate set) -> 404 unknown restaurant/table -> `combination_not_allowed` -> time checks -> capacity
  (sum over the set) -> `table_unavailable`.
- **UI.** The token is kept in `localStorage`. A booking form keeps one Idempotency-Key per distinct body
  in page memory; a failed or lost request never changes it. Single-table bookings send `table_id`,
  pairs send `table_ids`. Only the latest search may render (sequence number). A lost response or 5xx
  shows `booking-uncertain`; a confirmed 4xx shows `booking-error`. Error/uncertain/confirmation
  elements exist in the DOM only while applicable.
