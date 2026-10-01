# Pocketful stage 1 — run instructions

HTTP API only (payments, requests, splits, activity feed, settlements, export/import).
Node.js 20, no runtime dependencies (`node:20-alpine`, standard library only). State is in memory.

## Build and start (one command, no manual setup)

From the repository root:

    docker build -t pocketful-s1 stage-1 && docker run -d --name pocketful-s1 --cpus 2 --memory 2g -e PORT=8080 -p 127.0.0.1:18080:8080 pocketful-s1

or, from inside `stage-1/`:

    docker build -t pocketful-s1 . && docker run -d --name pocketful-s1 --cpus 2 --memory 2g -e PORT=8080 -p 127.0.0.1:18080:8080 pocketful-s1

The service listens on `0.0.0.0:$PORT` (default `8080` when `PORT` is unset) and answers
`GET /health` with `200 {"status":"ok"}` within about a second. It needs no network at run time.

    curl http://127.0.0.1:18080/health
    docker rm -f pocketful-s1        # stop and remove

## Own tests

`tests/test_stage1.py` (Python 3 standard library only) is written from the specification and covers the
acceptance map: validation, auth, idempotency, requests, splits, feed, settlements, export/import
(including import into a second container), and concurrency with 50 requests in flight.

    tests/run.sh                      # builds, starts containers A (:18080) and B (:18081), runs everything, removes them

Against an already running service:

    BASE_URL=http://127.0.0.1:18080 python3 -m unittest discover -s tests -v
    # add BASE_URL_B=http://127.0.0.1:18081 (second container) to include the cross-container import test

The tests call `POST /_test/reset` and replace the service state; run them against a disposable container.

## Notes

- Passwords are stored as per-user salted scrypt hashes (N=4096, r=8, p=1) and never exported in plaintext.
- All state changes run synchronously in one event-loop turn, so each money movement is atomic and
  idempotency claims cannot race. `POST /_test/export` returns a consistent snapshot of the whole state
  (including hashes, tokens and idempotency records); `POST /_test/import` replaces state atomically.
