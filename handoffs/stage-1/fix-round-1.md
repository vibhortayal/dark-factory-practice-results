@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: C4, C8, C9, K3, A11 (blocking, from the Verifier's BLOCK); new rows A12, A13 (text below) · Revision: f0f44189584133d95ec5bfc64c52c050450ddeb8 is BLOCKED (fix round 1 of at most 5) · Files: stage-1/src/server.js, stage-1/src/json.js, acceptance/stage-1.md · Command: the Verifier's two reproductions, repeated below · Expected / actual: over-limit values are 422 `validation_failed` with the error body at any size / 400 `malformed_request` past 2 MiB of body, bare 431 past 16 KiB of head · Repro: below · Next: Implementer.

STAGE 1 FIX REQUEST, round 1 (single message, final). Implementer: I can see uncommitted edits in stage-1/; fold the ruling below into that same fix before you commit. This message also changes the acceptance map, which is why it goes to both seats.

## Blocking findings (from the Verifier, verdict BLOCK on f0f44189584133d95ec5bfc64c52c050450ddeb8)

Finding 1 (rows C4, K3). A body over 2 MiB that carries an over-limit value gets 400 `malformed_request` ("request body too large") instead of 422 `validation_failed`. Specification: section 8 "`note` longer than 200 characters | 422 `validation_failed`"; section 11 "transfers contains 1..32 objects … malformed batch shape is 422 `validation_failed`"; section 5 "Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type." Repro:
    python3 -c 'import json;print(json.dumps({"to_handle":"bob","amount":1,"note":"n"*2200000}))' > big.json
    curl -s -X POST $BASE/payments -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -H 'Idempotency-Key: big-1' --data-binary @big.json -w ' %{http_code}\n'
Same on `POST /requests`; and `POST /settlements` with 40,000 transfers (2,280,015 bytes) gives 400, expected 422. Cause: `MAX_BODY = 2 * 1024 * 1024` in src/server.js.

Finding 2 (rows C8, C9, A11). A request head over 16 KiB gets a bare `HTTP/1.1 431` with `Connection: close` and no body. Specification section 5: "`Idempotency-Key` | 1 to 255 characters | 422 `validation_failed`"; "`limit` | integer 1 to 200 | 422 `validation_failed`"; "Every 4xx and 5xx response carries this body". Repro:
    curl -s -i -X POST $BASE/payments -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -H "Idempotency-Key: $(python3 -c 'print("k"*17000)')" -d '{"to_handle":"bob","amount":1}'
    curl -s -i "$BASE/activity?limit=$(python3 -c 'print("9"*17000)')" -H "Authorization: Bearer $TOK"
Expected both: 422 with `{"error":{"code":"validation_failed",…}}`. Cause: Node's default 16 KiB header limit answers before the service's code; no `maxHeaderSize`, no `clientError` handler. An over-long unknown bearer token hits the same bare 431 and must be 401.

## Architect's ruling: moving the cap is not a fix. New acceptance-map rows (now in acceptance/stage-1.md)

Row A12 [D], in full: "The service's own size caps never produce a bare or mislabelled answer. (a) Request head: accepted up to at least 1 MiB, so an over-long `Idempotency-Key`, query value or bearer token reaches the service's own rules (422 for the key or `limit`/`offset`, 401 for an unknown token). A head beyond the cap is answered 422 `validation_failed` with the standard error body. (b) Request body: any body the service declines to read or process because of its own size or nesting cap is 422 `validation_failed` (a body within the stated field limits cannot be that large, so some stated or implied limit is exceeded); 400 `malformed_request` stays reserved for bytes that are not valid JSON and for wrong JSON types. Authentication is still answered first (401) where the route needs it. The body cap is at least 8 MiB on API routes and large enough on reset/import for any state the service can export. (c) A valid-JSON body nested deeper than the service can compare or validate is 422, not 400; a non-string `note` is 422 at any depth the service parses. Reason: section 5 gives 422 for 'values exceeding a stated maximum or length' and reserves 400 for a body that does not parse; every 4xx must carry the error body."
Check: 17,000-character key and `limit`; 2,200,000-character note; 40,000 transfers; a head over the cap; a body over the cap with and without a token; a non-string note nested 201 and 5,000 deep. None may be 5xx, bare, or 400.

Row A13 [D], in full: "Path parameters are compared after percent-decoding, so `/requests/rq%5F1/pay` and `/requests/rq_1/pay` are the same resource and the same idempotency scope. An undecodable escape is 404 `not_found`."
Check: pay with a key on one spelling, replay on the other -> 200 with the original body.

A12 and A13 turn three of the Verifier's non-blocking notes (2 MiB body with only an unknown field, nesting over 200, raw-path idempotency scope) into required rows, because each is a stated rule answered with the wrong code. They are in scope for this fix.

## Also do in this fix (from the Verifier's maintainability notes; not separately blocking)

- Define `MAX_BALANCE` and the request status list once and import them.
- Make the atomicity rule enforceable rather than a comment: a test or a guard that fails if a state-changing handler returns a promise or yields before commit.
- Memory: 2 GiB is the limit and nothing is pruned. Keep it bounded under the caps above (reading a body up to the cap for 50 requests in flight must stay well inside 2 GiB; reject by `Content-Length` before buffering where it is present, and stop reading once the cap is passed).

Not required: fixture leniencies (omitted `currency`/`minor_units`/`users`, a seeded amount of 0, `payment_id: null` on a seeded `paid` request) stay as they are; whole-second timestamps stay.

## Report

Implementer: commit under your seat identity, then report the new full revision to the Architect and the Verifier with the evidence header, the two reproductions' new output, your tests, and harness host and isolated runs with new --out directories (s1-impl-03, s1-impl-04), run from /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs:
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/s1-impl-03
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/s1-impl-04
Verifier: when that revision is reported, verify it in full against the specification and the map including A12 and A13 (the complete specification and map you hold are otherwise unchanged), and report PASS, BLOCK or INCONCLUSIVE for that full revision.
