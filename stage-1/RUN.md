# Pocketful — stage 1 (payments and settlements)

Single-process Python 3.12 service, standard library only (no packages to install).
State is held in memory inside the container; all writes go through one lock in
`app/service.py`.

## Build and start (no manual setup)

    docker build -t pocketful-s1 . && docker run -d --rm --name pocketful-s1 -e PORT=8080 -p 8080:8080 pocketful-s1

Listens on `0.0.0.0:$PORT` (default `8080`). Health: `curl localhost:8080/health`.
Stop: `docker stop pocketful-s1`.

## Tests

From this folder, with Python 3.12 on the host (no dependencies):

    python3 -m unittest discover -s tests

## Layout

- `app/server.py` — HTTP layer, routing, auth and idempotency preconditions
- `app/service.py` — domain logic and state (users, payments, requests, splits, settlements, export/import)
- `app/validation.py` — field validation, canonical JSON comparison, error type
- Passwords are stored with scrypt (per-user salt); `state` in `GET /_test/export` carries hashes only.
