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

Load/envelope measurements against a running container (started with
`--cpus 2 --memory 2g --memory-swap 2g`):

    python3 tests/load/load_envelope.py http://127.0.0.1:8080 <container-name>

## Layout

- `app/server.py` — HTTP layer, routing, auth and idempotency preconditions, body limits
- `app/service.py` — domain logic and state (users, payments, requests, splits, settlements, export/import)
- `app/validation.py` — field validation, exact JSON-number handling, canonical bodies, error type
- `app/passwords.py` — two-level password hashing (scrypt + HMAC), see below

## Operating envelope

The service has 2 vCPU, 2 GiB and a 5 s per-request limit (10 s for `/_test/*`) and must survive 50
requests in flight. A finite service can only promise that inside a stated envelope, so the
envelope is explicit and enforced by *fast* rejections with the usual error body
(`{"error": {"code", "message"}}`). Nothing the specification defines as valid is refused inside it.

1. **API request bodies** (every endpoint except `POST /_test/reset` and `POST /_test/import`):
   at most **128 KiB** and at most **16,384 JSON separators** (commas + `[` + `{`, counted at C
   speed before parsing). Larger bodies get `413 payload_too_large` without being parsed.
   Rationale: a 1000-handle split is about 10-25 KB with about 1000 commas; the bound keeps the
   Python work for 50 simultaneous bodies at about one second of one core. `Content-Length` values
   that are not plain digits or are absurdly long are `400 malformed_request`.
2. **State capacity budget: 40 MiB** (`POCKETFUL_STATE_BUDGET`, bytes). The service keeps a running
   upper-bound estimate of the serialised size of everything it stores (users, tokens, payments,
   requests, splits, settlements and idempotency records with their stored responses). A write
   that would exceed the budget is refused *before any change* with `429 capacity_exceeded`: no
   idempotency key is claimed and nothing is created (a split's requests, a settlement's members,
   a login/signup token are counted up front). Replays of earlier keys, reads, decline/cancel and
   `/_test/*` keep working at capacity. The estimate is measured to be 1.03-3.4x the real size per
   operation, so the real export stays below the budget plus margin (asserted <= 48 MiB; measured
   34.4 MiB when the estimate reached 40 MiB). A reset fixture or an import whose state is over
   the budget is `422 validation_failed` with the state unchanged.
3. **Export** is an atomic read-only snapshot; the serialised bytes are cached per state version
   (any mutation bumps the version), so concurrent exports of an unchanged state reuse one
   serialisation. **Reset/import** bodies may be up to 64 MiB (an export is never larger than
   about 48 MiB), are bounded to 3,000,000 JSON values when over 1 MiB (`422`), and only one large
   document is parsed/validated/built at a time (the others queue). Import validates a closed schema
   and does a trial export before swapping, so an imported state always exports and replays.
4. **Passwords** are stored as `{alg: "scrypt+hmac-sha256", n, r, p, load_salt, user_salt, hash}`:
   one random `load_salt` per reset/signup, `K = scrypt(password, load_salt, n=4096, r=8, p=1)`
   computed once per *distinct* password in a fixture, and `hash = HMAC-SHA256(K, user_salt)` with a
   random per-user salt (equal passwords still store different hashes; every guess costs one scrypt).
   Measured per scrypt: about 9 ms on one core (n=2**14 would be about 59 ms and 2**13 about 28 ms;
   2**12 was chosen so that 500 distinct passwords reset in about 2.5 s and 50 concurrent logins finish
   in about 0.4 s on 2 vCPU). A fixture with more than 800 distinct passwords is `422`. Hashing never
   runs under the state lock (except the final-pass fallback of a login that raced a reset/import) and
   at most 4 scrypt calls run at once (4 MiB each).
5. **Idempotency records** keep a SHA-256 digest of the canonical request body plus the original
   response, never the request body itself.

Measured in a container with `--cpus 2 --memory 2g --memory-swap 2g` (see
`tests/load/load_envelope.py`): 50 concurrent worst-shape 128 KiB bodies finish in <= 1.5 s with
`GET /me` <= 0.7 s and peak memory under 100 MiB; reset of 20,000 users sharing a password 0.2 s;
a state filled to the budget exports in 0.3 s (34.4 MiB), 10 concurrent exports all answer
within 0.5 s, import 1.3 s, 4 concurrent imports of it all finish within 5 s.
