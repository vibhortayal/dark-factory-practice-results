# Pocketful stage 2: build and run

Standard-library Python 3.12 service with a plain-JavaScript web client served from the same
image (`static/`: HTML shell, one stylesheet, one script; no CDN, external font or image).

    docker build -t pocketful-stage-2 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-2

The service listens on `0.0.0.0:$PORT` (default `8080`). Open `http://localhost:8080/` in a
browser (routes `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`), or call the
JSON API (`Accept` without `text/html`). State is in memory and replaced by `POST /_test/reset`.

## Own tests

API and concurrency tests (stdlib `unittest`) against a running container:

    BASE_URL=http://localhost:8080 python3 -m unittest test_api test_concurrency test_stage2_api

Browser tests (Playwright for Python with Chromium, e.g. the harness virtualenv):

    BASE_URL=http://localhost:8080 SHOTS=/tmp/shots <playwright python> -m unittest test_browser

Run both from `stage-2/tests`.
