# Pocketful stage 1 — run instructions

Build and start (no manual setup, no network needed at run time):

```sh
docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

Run from this folder (`stage-1/`). `PORT` defaults to 8080 when unset. Health check:
`curl http://localhost:8080/health` → `{"status":"ok"}`.

The service is pure Python 3.12 standard library (no third-party packages), keeps all state in
memory and listens on `0.0.0.0:$PORT`. Passwords are hashed with scrypt.

## Own tests

`tests/test_stage1.py` is a stdlib-only script that runs against a running container:

```sh
BASE_URL=http://localhost:8080 python3 tests/test_stage1.py
```

## Implementation limits

Ordinary API endpoints (everything except `/_test/reset` and `/_test/import`):

- request body at most 512 KiB, else 413 `payload_too_large` (excess drained, never buffered);
- at most 16 KiB of JSON structure (everything left after removing string literals and whitespace:
  numbers, brackets, commas, colons), else 413 `payload_too_large`; this bounds the number of
  numbers/keys in any accepted body;
- JSON nesting at most 128 levels, else 400 `malformed_request`.

`/_test/reset` and `/_test/import` accept up to 512 MiB (a memory guard only) so any export this
service produces can be imported again; they are parsed with the standard decoder (too deep -> 400).

Idempotency body equality ("same JSON value"): two bodies are equal iff a fingerprint (all numbers
read as floats, keys sorted) is equal and the exactly-parsed values (ints, Decimal floats) compare
equal. So key order/whitespace are irrelevant, `1000 == 1000.0 == 1e3`, `1.5 == 1.50 == 15e-1`,
`1 != true != "1" != null`, array order matters. Known and accepted: `-0.0` and `0` in an unknown
field count as different bodies, as do two exponent literals too large for a float to tell apart.
The stored body text of a claimed key is re-parsed under the lock for the comparison (bounded by the
limits above to a few milliseconds).

Parsing, validation of the body and password hashing run outside the global lock; the lock covers only
authenticate / replay lookup / validate against state / mutate and the state swap. Bodies over 32 KiB
are processed one at a time so small requests stay responsive.
