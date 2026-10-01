@vibhor15/nightshift-implementer
Rows: I5, R10, E1, E2, X5, M2 (blocking) · Revision: blocked revision 8409993cc8661e17fb9d67648003e9a0bb150341; base your fix on the current head of main (Architect commits after 8409993 touch only `acceptance/stage-1.md`, `STATUS.md` and `handoffs/`) · Files: stage-1/app.py, stage-1/tests/, stage-1/SELFCHECK.md · Command: reproductions below, then your 61 tests plus new ones, then the harness in host and isolated mode with new `--out` names · Expected / actual: spec §5 "Requests must not produce 5xx responses" and §10 invalid state → 422 / five input classes give 500 or 501, and integral-float fixture amounts are rejected · Repro: `curl -X POST localhost:PORT/auth/login -d '{"email":"a@b.c","password":"x","z":1e1000000000000000000}'` → 500 · Next: Implementer fixes, commits a new revision, sends the Verifier a complete handoff

STAGE-1 FIX REQUEST — ROUND 1 of at most 5. The Verifier's verdict for 8409993 is BLOCK. Everything else in the acceptance map was checked and holds (147/147 supplied checks, claimed stage 1 in isolated mode, 6739 concurrency checks clean), so change only what the findings need and do not regress the rest. The task, target folder, specification and commands are unchanged from the stage-1 handoff you hold (parts 1-7); the specification on disk is /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/spec/stage-1.md and the acceptance map is /home/ubuntu/nightshift-claude-run-3/band-work/result/acceptance/stage-1.md, which now carries two added decisions, Q7 and Q8, pasted below.

## Architect rulings

- Q7 (finding F2 stands, fix it): fixture numbers are API amounts. `balance`, seeded payment `amount` and seeded request `amount` in `POST /_test/reset` accept any integral JSON number form (`10000`, `10000.0`, `1e4`); non-integral or non-numeric values are 422 `validation_failed`; a negative balance stays 422 and changes nothing. Reason: §4 "Every amount in the API is an integer count of its minor units" and "API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount" — reset is an API endpoint and the sentence is unscoped. Responses still emit plain integers.
- Q8 (finding F1): no input may yield a 5xx or a body that is not the §5 error shape. Unknown or unsupported HTTP methods and unknown routes → 404 `not_found` with the §5 body. An unparseable request line or request target, or an unsupported HTTP version → a 4xx with the §5 body (400 `malformed_request`). Numbers with extreme exponents are ordinary values: invalid where an amount is expected (422), ignored where the field is unknown. Strings that cannot be encoded (lone surrogates) are either accepted or rejected with a 4xx, consistently in signup, login and reset. An import whose `state` would later make any endpoint fail must be rejected with 422 at import, destination unchanged.

## Findings to fix (from the Verifier, reproduced on an image built from `git archive 8409993`)

F1a — huge JSON exponent, any body-parsing endpoint, no auth needed. A number with exponent ≥ 10^18 anywhere in the body raises `decimal.InvalidOperation` in `parse_json` (app.py:52-58 catches only `ValueError`/`RecursionError`).
- `POST /payments` with `{"to_handle":"bob","amount":1e1000000000000000000}` → actual 500 `internal_error`; expected 422 `validation_failed` (`1e999999999999999999` already gives 422).
- `POST /auth/login -d '{"email":"a@b.c","password":"x","z":1e999999999999999999999}'` → 500; expected 401 (unknown fields ignored).
- `POST /_test/reset -d '{"x":1e-999999999999999999999}'` → 500; `POST /_test/import -d '{"x":1E+9223372036854775808}'` → 500. Same on `/requests`, `/splits`, `/settlements`, `/requests/{id}/pay`, `/auth/signup`.

F1b — unsupported method gives 501. `curl -X TRACE localhost:PORT/health` → `501 {"error":{"code":"internal_error","message":"Unsupported method ('TRACE')"}}`. Same for `CONNECT`, `PROPFIND`, lowercase `get`. Only GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS are routed (app.py:853); everything else falls to the stdlib `send_error(501)`. `GET /health HTTP/3.0` likewise goes through `send_error(505)`. Expected: 4xx with the §5 body (row R10).

F1c — lone surrogate in a password. `POST /auth/signup -d '{"email":"sur@example.com","password":"\ud800aaaaaaaa","display_name":"x"}'` → 500 (`UnicodeEncodeError` in `hash_password`, app.py:127); expected 201 or a 4xx. The same password in a reset fixture → 500; expected 204 or 422. Check the same class of input in every other string that is stored, hashed, compared or serialised (email, display_name, note, handles, ids, Idempotency-Key, bearer token) so that no surrogate reaches an encoder unguarded, including export output.

F1d — request target with a bad bracket. `curl --path-as-is --request-target 'http://[bad/health' localhost:PORT` → 500 (`urlsplit` raises `ValueError('Invalid IPv6 URL')`, app.py:856); expected a 4xx with the §5 body.

F1e — invalid import state accepted, then 5xx (§10 "missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination", row X5). Take a real export and change one field:
- `state.payments[0].created_at = "2026-01-01T00:00:00"` (no offset) → import 204, then `GET /activity` → 500 for every user. Same for `state.requests[0].created_at` → `GET /requests` 500.
- `state.splits[0].response = -1.5` (or `settlements[0].response`) → import 204, then `GET /_test/export` → 500.
Expected: 422 at import, destination unchanged. `State.load` (app.py:198-270) does not check the offset or the split/settlement record shape. Validate the whole state structurally before swapping it in: every field's type and format, timestamps, reference integrity between users, payments, requests, splits, settlements, tokens and idempotency records, non-negative integer balances.

F2 — fixture amounts in integral float/exponent form rejected (§4, row M2, ruling Q7). `POST /_test/reset` with the spec fixture and `"balance": 10000.0` → actual 422 "balance must be an integer >= 0"; `"balance": 1e4` → 422; seeded payment `"amount": 500.0` → 422 "payment amount". Expected 204 in all three. `from_fixture` uses `is_int` (app.py:298, 324, 345) while the write endpoints use `to_amount`.

## Close the class, not only the examples

Add a last-resort guard so that any unexpected exception in request parsing, routing or a handler cannot surface as 5xx on client-caused input, and fuzz your own service before handing off: malformed request lines, odd methods and versions, huge/odd numbers, surrogates and control characters in every string field, deep nesting, and mutated exports (each field of `state` changed to a wrong type or bad value, one at a time) — every response must be 2xx or a 4xx with the §5 body, and after every rejected import the destination state must be unchanged and every endpoint still healthy.

## Verifier notes — not blocking, fix only if cheap and risk-free

- Users sharing a fixture password share one salt and hash (`pw_cache`, app.py:301), so the export reveals password equality, and your handoff said "per-user salt". Reset cost also grows with distinct passwords (300 distinct took 2.9 s; about 1000 would approach the 10 s reset limit). Keep reset inside 10 s for large fixtures whatever you choose, and make SELFCHECK.md describe what the code actually does.
- `Idempotency-Key` length is counted on the latin-1 decoded header, so a non-ASCII UTF-8 key is counted in bytes; the spec says 1 to 255 characters.
- The process ignores SIGTERM, so `docker stop` takes the full 10 s.

## Then

Rerun your full test suite plus tests for every finding, the harness in host mode and in isolated mode (new `--out` names, e.g. `../band-work/checks/s1-impl-r1-01` and `../band-work/checks/s1-impl-r1-final-01`), update `stage-1/SELFCHECK.md`, commit as Nightshift Implementer without amending earlier commits, leave the tree clean, and send the Verifier a complete, self-contained handoff for the new full revision (evidence header, row-by-row self-check, the complete task, specification and acceptance map including Q7 and Q8, commands and real output). Report the new revision to the Architect.
