# Pocketful stage 4: build and run

Standard-library Python 3.12 service with a plain-JavaScript web client served from the same
image (`static/`: no CDN, external font or image). Stage 4 adds refunds
(`POST /payments/{id}/refunds`, `refund_of` on every payment) and atomic operator correction
batches (`POST /correction-batches`, `correction_batch_id` on revisions) on top of the stage-3
bitemporal ledger.

    docker build -t pocketful-stage-4 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-4

The service listens on `0.0.0.0:$PORT` (default `8080`). State is in memory and is replaced by
`POST /_test/reset` (or `POST /_test/import`, which also accepts stage-1, stage-2 and stage-3 exports).

## Own tests

From `stage-4/tests`, against a running container:

    BASE_URL=http://localhost:8080 python3 -m unittest test_api test_concurrency test_stage2_api test_stage3_api test_stage4_api

Browser regression (Playwright for Python with Chromium, e.g. the harness virtualenv):

    BASE_URL=http://localhost:8080 SHOTS=/tmp/shots <playwright python> -m unittest test_browser
