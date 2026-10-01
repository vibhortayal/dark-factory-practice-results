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
- the body is parsed first (not valid JSON -> 400 `malformed_request`); then at most 16,384 bytes of
  JSON structure (everything left after removing string literals and whitespace), else 413
  `payload_too_large`; this bounds the number of numbers/keys in any accepted body;
- JSON nesting at most 128 levels, else 400 `malformed_request`;
- signup: `email` <= 320, `display_name` <= 1,000, `password` <= 1,024 characters, else 422
  (login with longer values is simply 401); `note` <= 200 characters, `Idempotency-Key` <= 255.

`/_test/reset` and `/_test/import` accept up to 512 MiB (a memory guard only) so any export this
service produces can be imported again; they are parsed with the standard decoder (too deep -> 400).

Idempotency body equality ("same JSON value"): each body is reduced to a SHA-256 digest of
(fingerprint + exact numbers). The fingerprint (numbers read as floats, keys sorted) fixes
structure, strings and the kind of every scalar; the exact-number text reads every number as a
Decimal and prints it canonically, so `1000 == 1000.0 == 1e3 == 10E2` and `1.5 == 1.50 == 15e-1`,
but `1.5 != 1.6`, `1 != true != "1" != null`, `"1e3" != 1000`, array order matters and key order
and whitespace do not. A record keeps only the 64-character digest, status and response, so memory
per accepted request is independent of body size. Known and accepted: `-0.0` and `0` in an
unknown field count as different bodies.

Parsing, body validation and password hashing run outside the global lock; the lock covers only
authenticate / replay lookup (a digest string comparison) / validate against state / mutate and the
state swap. Bodies over 32 KiB are processed one at a time so small requests stay responsive.
Ordinary handlers validate from the Decimal parse (every number is a Decimal; `1000`, `1000.0`,
`1e3` are the same integral amount, `1.5` is rejected).
