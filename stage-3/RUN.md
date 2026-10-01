# Pocketful stage 3: build and run

Standard-library Python 3.12 service with a plain-JavaScript web client served from the same
image (`static/`: no CDN, external font or image). Stage 3 adds the bitemporal ledger: payment
instants, `GET /me` with `as_of`/`known_at`, `GET /statement` with stable snapshots, payment
corrections and revision history, historical holds.

    docker build -t pocketful-stage-3 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-3

The service listens on `0.0.0.0:$PORT` (default `8080`). State is in memory and is replaced by
`POST /_test/reset` (or `POST /_test/import`, which also accepts stage-1 and stage-2 exports).

## Own tests

From `stage-3/tests`, against a running container:

    BASE_URL=http://localhost:8080 python3 -m unittest test_api test_concurrency test_stage2_api test_stage3_api

Browser regression (Playwright for Python with Chromium, e.g. the harness virtualenv):

    BASE_URL=http://localhost:8080 SHOTS=/tmp/shots <playwright python> -m unittest test_browser
