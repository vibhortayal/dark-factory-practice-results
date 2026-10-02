@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: C2, C11, D4, D7, A11 (blocking); A9, D7, E9, J3 (notes) · Revision: 03b5470f8967245daf840465472e91b6328c7e4f · Files: stage-1/pocketful/validation.py, request.py, server.py, statecodec.py, idempotency.py (read only) · Command: `band-work/verifier/stage-1/run.sh 03b5470f8967245daf840465472e91b6328c7e4f <out>` and the harness `--stage 1 --mode isolated --out ../band-work/checks/s1-ver-01` · Expected / actual: four inputs the specification names give 400/431/500 where it requires 422 or "no 5xx" · Repro: see B1-B4 · Next: Implementer

# VERDICT: BLOCK — stage 1, revision 03b5470f8967245daf840465472e91b6328c7e4f

Everything on my list derived before the run passes (86 of 86, plus the fresh-container import). The
block rests on four findings found by the code read and confirmed against the running container.
Each contradicts a statement of the specification; none is covered by the supplied checks.

## Blocking findings

**B1 — reset answers 500 on a fixture with a wrong-typed id.** Map rows C11, A11.
Specification §5: "Requests must not produce 5xx responses, including under concurrent load." and
"400 `malformed_request` | Unparseable body, or a field of the wrong JSON type".
Repro (any running container):
`curl -s -X POST $B/_test/reset -H 'Content-Type: application/json' -d '{"currency":"EUR","minor_units":2,"users":[{"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":1}],"settlement_operator_ids":[["u_ada"]]}'`
Actual: `500 {"error":{"code":"internal_error",...}}`; container log `internal error: TypeError("unhashable type: 'list'")`.
Expected: a 4xx with the §5 body (400 `malformed_request`, or 422 `validation_failed` under map row C11) and state unchanged.
Same 500 for: `settlement_operator_ids: [{"id":"u_ada"}]`; a payment whose `from_user_id` or `to_user_id` is an array or object; a request whose `requester_id` or `payer_id` is an array or object. (State is left unchanged in every case; only the status is wrong.) Cause: `statecodec.py` uses these values as dict keys (`o in users`, `users.get(...)`) before checking they are strings.

**B2 — `limit` far beyond its range gives 400, not 422.** Map row D7.
Specification §5: "`limit` | integer 1 to 200 | 422 `validation_failed`", and §8: "Outside either range is 422 `validation_failed`."
Repro: `curl -s -H "Authorization: Bearer $T" "$B/requests?limit=$(printf '9%.0s' $(seq 4301))"` (same on `/activity`).
Actual: `400 {"error":{"code":"malformed_request","message":"unreadable request"}}`. Expected: 422 `validation_failed`.
A limit of 4300 digits is answered 422; 4301 digits is the first that is not. Cause: `int(raw)` in `validation.query_int` raises ValueError above Python's 4300-digit limit and `server.py` maps every ValueError to 400.

**B3 — `amount` far above 1000000000 gives 400 "body is not valid JSON", not 422.** Map row C2.
Specification §8 (payments, requests, splits) and §11: "`amount` below 1, above 1000000000, or not an integer | 422 `validation_failed`".
Repro: `curl -s -X POST $B/payments -H "Authorization: Bearer $T" -H 'Idempotency-Key: k1' -H 'Content-Type: application/json' -d "{\"to_handle\":\"bob\",\"amount\":$(printf '9%.0s' $(seq 4301))}"`
Actual: `400 {"error":{"code":"malformed_request","message":"body is not valid JSON"}}`. Expected: 422 `validation_failed` (the body is valid JSON; the amount is above the maximum).
Same on `POST /requests`, `POST /splits` and inside a `POST /settlements` transfer. 4300 digits is answered 422; 4301 is the first that is not. Cause: `json.loads` raises ValueError for integers over 4300 digits and `request.json_body` reports it as unparseable.

**B4 — an `Idempotency-Key` far beyond 255 characters gives 431 with an HTML body.** Map rows D4, A7.
Specification §5: "`Idempotency-Key` | 1 to 255 characters | 422 `validation_failed`" and "Every 4xx and 5xx response carries this body: `{ "error": { "code": ..., "message": ... } }`".
Repro: `curl -s -i -X POST $B/payments -H "Authorization: Bearer $T" -H "Idempotency-Key: $(printf 'k%.0s' $(seq 65520))" -H 'Content-Type: application/json' -d '{"to_handle":"bob","amount":1}'`
Actual: `431`, `Content-Type: text/html;charset=utf-8`, body `<!DOCTYPE HTML>... Error code: 431 ... Line too long`. Expected: 422 `validation_failed` with the JSON error body.
Keys of 256, 1000, 10000, 60000 and 65510 characters are answered 422 correctly; 65520 is the first length that is not (the header line passes 65536 bytes and `http.server` answers before the handler runs).

B2-B4 are values beyond a limit the specification states for that value, so they block however far beyond the limit they are. All four have a reproduction in my scripts as LM-01 to LM-04.

## What I ran

1. Tree clean at 03b5470f8967245daf840465472e91b6328c7e4f before and after (`git status --porcelain` empty apart from my `verification/` folder).
2. Clean build: `git archive` of the revision, `docker build --no-cache` -> exit 0.
3. Runtime: no `PORT` with `-p 127.0.0.1:18080:8080` -> healthy after 0.34 s; `-e PORT=9123` with a mapping to 9123 -> healthy after 0.34 s; on an `--internal` network (no outbound) with `--cpus 2 --memory 2g` -> healthy after 0.12 s. Memory after the whole run 18 MiB, no restart, no OOM.
4. RUN.md command exactly as written (`docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1`) from the clean export -> `/health` 200 after about 2 s.
5. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/s1-ver-01` -> `stage 1: pass` (147 passed, none skipped or deselected), `stage 2: fail`, `claimed stage: 1 on the shipped checks`.
6. My list, three full runs (`runs/r1`, `r2`, `r3` under `band-work/verifier/stage-1/`), against the image on the internal network under the limits, 3,864 HTTP requests in the last run:
   - 86 checks derived from the specification before the run: **86 pass, 0 fail, 0 error, 0 notes** (run r2 and r3). In r1 one check (AR-01) failed through my own mistake (it paid 1000000001); corrected and re-run.
   - EX-07 (export, remove both source containers, import into a fresh third container, verify): pass.
   - 6 checks added after the code read: LM-01..LM-04 **fail** (B2, B3, B4, B1), NT-01 and NT-02 pass with notes N1, N2.
   - Totals of the final run r3: 93 checks, 89 pass, 4 fail, 0 error, 0 skipped.
   - Cross-cutting over every response of the 86-check list: no 5xx, no request over 5 s (10 s for `/_test/*`), every 4xx carries the error body, every body is `application/json; charset=utf-8`, every id is a string of at most 64 characters, every timestamp is RFC 3339 with a numeric offset.
   - Covered: reset/fixture, currencies, auth and handle derivation, every row of every error table with the last allowed and first refused value (amount 1 / 1000000000 / 0 / 1000000001, note 200 / 201, key 1 / 255 / 256, limit 1 / 200 / 0 / 201, offset 0 / -1, transfers 1 / 32 / 0 / 33, password 7 / 8, balance 0 / -1 in a fixture, 2^53), the request state matrix, idempotency on all five paths (replay, reuse, 4xx then reuse, user scope, path scope, 50 concurrent identical, replay after change), splits and the §9 table, the feed contract for four viewers including seeded and settlement members, settlements (precedence in both orders, net affordability, atomicity), export/import (replace, repeat, errors, second container, export during a write burst), and concurrency at 48-50 in flight (overdraft race exactly 10 of 49, one of 50 pays, pay/decline/cancel race, settlements against payments, mixed burst).
7. Implementer's own tests, from the clean export: `python3 -m unittest discover -s tests -t .` -> Ran 40 tests, OK.
8. Stage boundary: the stage-2 supplied checks fail at the first test (`GET /` is 404; no web pages exist in `stage-1/`). Stage 1 is the first unit, so there are no earlier checks to repeat.

## Notes (do not block)

- **N1** An unknown body field nested 990 or more levels deep gives `500 internal_error` (RecursionError in `idempotency.canonical`); 985 levels is accepted (201). Size no ordinary user sends: 990 levels of nesting. Tested on `POST /payments`; 2000 levels also 500.
- **N2** `offset` of 4301 or more digits gives 400 `malformed_request`, although any integer of 0 or more is valid (expected 200 with no items). Size: 4301 digits. Same cause as B2, so one fix covers both.
- **N3** scrypt cost is N=4096, r=8, p=1. It is a password-hashing function, so §6 is met; the cost is low by current guidance. No plaintext password appears in an export.
- **N4** With 20,000 stored payments: `GET /activity` 7 ms, export 0.33 s (14.4 MB), import 0.47 s, memory 143 MiB. One global lock and list scans; no weakness seen at that figure.
- **N5** Reset timing: a 50-user reset followed by a 300-user reset took 1.8 s together (limit 10 s each).
- **N6** Every Architect [reading] row I probed is met (numeric offset, unknown route 404 `not_found`, fixture without optional keys, structurally invalid fixtures 422, caller omitted from a split, non-object body 400, pay with no body, split request note).
- **N7** Maintainability: modules are small with one job each and RUN.md's table matches the code. `statecodec.py` (230 lines) holds both fixture building and import validation and is the natural place to split in stage 2. Feed and request order rely on insertion order, not on sorting by `created_at`; the two agree while the clock does not go backwards. `server.py` maps every ValueError to 400, which is what hides B2.
- **N8** `HEAD` on any path gives 405 with an empty body; the specification does not speak to HEAD.

## Remaining risk I could not test

- The judged test set is larger than the shipped checks; I can only test what the specification states.
- CPU contention: my client ran on the same 4-core host as the 2-vCPU container, so latencies under a slower judge host are not measured.
- Behaviour after an abrupt container restart was not tested (the specification says state need not survive).

## Where things are

- Check list: `verification/stage-1/CHECKLIST.md` (this commit). Scripts and run logs, outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-1/` (`run.sh`, `main.py`, `vlib.py`, `checks_a.py`, `checks_b.py`, `probes.py`, `probes2.py`, `runs/`).
- Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s1-ver-01/`.
