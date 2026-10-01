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
   upper bound of the bytes the export serialisation (`json.dumps`, `ensure_ascii=True`) can contain.
   Every write is charged *before* any change from prototype objects serialised with the same options,
   filled with the maximum size of each server-controlled field (`app/capacity.py`), plus the exact
   JSON-escaped length of every client-controlled string at every place it is stored (an emoji is 12
   bytes, a control character 6: idempotency key, note, ids, email, display name). Fields that can
   change later (request status, `payment_id`) are charged at creation. Reset and import measure the
   real serialisation and add 24 bytes per stored request. A write that would exceed the budget is
   refused with `429 capacity_exceeded`: no idempotency key is claimed and nothing is created (a split's
   requests, a settlement's members, a login/signup token are counted up front). Replays of earlier
   keys, reads, decline/cancel and `/_test/*` keep working at capacity. Tests fill the service to the
   budget with ASCII, emoji and control-character keys/notes/ids, 100 KiB emails and display names,
   3000-participant splits and 32-member settlements and assert `len(export) <= budget`,
   `len(export) <= accounted size`, and that the export re-imports byte-identically. A fixture or
   import over the budget is `422 validation_failed` with the state unchanged. The currency code of a
   fixture is limited to 1-16 ASCII characters (it is repeated in every stored receipt).
3. **Export** is an atomic read-only snapshot; the serialised bytes are cached per state version
   (any mutation bumps the version), so concurrent exports of an unchanged state reuse one
   serialisation. **Reset/import** bodies may be up to 64 MiB (an export is never larger than
   about 48 MiB), are bounded to 3,000,000 JSON values when over 1 MiB (`422`), and only one large
   document is parsed/validated/built at a time (the others queue). Import validates a closed schema
   and does a trial export before swapping, so an imported state always exports and replays.
4. **Passwords** are stored as `{alg: "scrypt+hmac-sha256", n, r: 8, p: 1, load_salt, user_salt, hash}`:
   one random `load_salt` per reset/signup, `K = scrypt(password, load_salt, n)` computed once per
   *distinct* password, and `hash = HMAC-SHA256(K, user_salt)` with a random per-user salt (equal
   passwords still store different hashes; every guess against a record costs one scrypt; users of one
   reset share the load salt, so one scrypt evaluation tests a guess against all users with that
   password at once). A signup uses `n = 2**14`. A reset fixture steps `n` down with the number of
   distinct passwords so the hashing phase stays near 5 s on 2 vCPU: `n = 2**14` up to 150 distinct
   passwords, `2**13` up to 350, `2**12` up to 700, `2**11` up to 1400, `2**10` (the floor) beyond; more
   than 4000 distinct passwords is `422` (4000 x 1.6 ms = 6.5 s at the floor). Measured per hash with two
   threads in a `--cpus 2` container: 26.9 / 12.1 / 6.3 / 3.1 / 1.6 ms for n = 2**14 .. 2**10 (see the load
   script for the measured reset times). Hashing never runs under the state lock (except the final-pass
   fallback of a login that raced a reset/import); at most 4 scrypt calls run at once (16 MiB each at
   `2**14`). Import accepts only these `n` values.
5. **Idempotency records** keep a SHA-256 digest of the canonical request body plus the original
   response, never the request body itself. The canonical text is compact JSON with sorted keys, in
   which numbers are written by exact value (1, 1.0 and 1e0 agree; 0.1 and
   0.1000000000000000055511151231257827 differ) and the only non-JSON syntax is an unquoted `~...~`
   token for a number that is not a plain integer; every client string is quoted, so no body can forge
   it. It is deterministic across processes, so replays keep working after export/import (a change of
   this text would break them; `tests/test_api.py` pins it with literal samples). Nothing derived
   from a request is retained after it (no caches): memory depends only on the stored state.
6. **Reset/import value bound.** Documents over 1 MiB may contain at most 3,000,000 JSON separators
   (`,` `[` `{`). This cannot refuse any document whose state fits the 40 MiB budget: a stored
   payment or request costs at least 250 bytes of budget and appears with at most 12 separators in a
   fixture or export, so a state at the budget has at most about 2,000,000 separators.

Responses go out in a single write with `TCP_NODELAY` set, so keep-alive requests take well under
1 ms. Measured numbers: run `tests/load/load_envelope.py` (see Tests); its output for the delivered
revision is part of the verification handoff.
