# Pocketful stage 1 — run instructions

Single container, Python 3.12 standard library only (no dependencies to install),
in-memory state. No outbound network is used at build (beyond pulling the base
image) or at run time.

## Build and start

```sh
docker build -t pocketful-stage-1 stage-1 && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-1
```

The service listens on `0.0.0.0:$PORT` (default `8080`). `GET /health` returns
`200 {"status":"ok"}` within a second or so of start.

With the resource limits from the specification:

```sh
docker run --rm --cpus 2 --memory 2g -p 8080:8080 -e PORT=8080 pocketful-stage-1
```

## Seed data

`POST /_test/reset` with the fixture replaces all state (no auth). A fresh
container starts empty (no users) until reset is called or state is imported
(`POST /_test/import`). `GET /_test/export` returns a restorable snapshot.

## Own tests

With a service running on `http://127.0.0.1:8080`:

```sh
python3 stage-1/tests/test_service.py            # unittest, standard library
python3 stage-1/tests/load.py                    # 50-in-flight concurrency checks
python3 stage-1/tests/fuzz.py                    # hostile input: never 5xx
```
(set `BASE_URL` to use another address).

## Notes

- Passwords: scrypt (n=2048, r=8, p=1, per-user random salt), stored as
  `scrypt$n$r$p$salt$hash`; never stored or exported in plaintext.
- All state changes happen under one lock, so balances never go negative and
  money moves at most once per request, even with 50 requests in flight.
