@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier
STAGE 1 HANDOFF, part 5 of 5 (FINAL). Rows: all · Revision: no stage code yet (map commit at HEAD) · Files: stage-1/ · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer builds, Verifier prepares checks.

== Acceptance map, verbatim, continued (sections H, I and Choices) ==

## H. Export and import (§10)

- H01 `GET /_test/export` (no auth) gives 200 `{track:"pocketful", format_version:1, state:{...}}`; atomic read-only snapshot; later writes do not change an export already taken. T+C.
- H02 `POST /_test/import` (no auth) with that entire object gives 204 and atomically replaces all state; accepts its own unchanged export; replacement not merge; repeating it duplicates nothing. T: export, import, export again gives an equal state.
- H03 Import into a fresh container of the same image works: no dependency on source process, files, volume, port, address. D+T with two containers.
- H04 Invalid JSON gives 400; missing fields, wrong `track`/`format_version`, or invalid `state` give 422 `validation_failed`, destination unchanged. T.
- H05 Import preserves: accounts and hashed-password login, existing bearer tokens, currency and minor units, balances, payments, requests, splits, operator permissions, settlement membership, ids and timestamps (not regenerated), every completed idempotent request body and its original response (replay still 200 with the same body; changed body still 409). Balances are not replayed. T.
- H06 Failed request keys remain reusable after import. New ids issued after import or reset never collide with existing ones. T.
- H07 Import removes all previous destination data and credentials (old tokens 401, old users gone). Reset clears everything including imported state. T.
- H08 Export, import and reset each complete within 10 s. T.

## I. Settlements (§11)

- I01 Fixture `settlement_operator_ids` (array of user ids, default `[]`) names operators. Operator rights give no access to other users' requests or private activity. T.
- I02 `POST /settlements`: no token 401; authenticated non-operator 403 `forbidden`; key required (E01 to E11). T.
- I03 `transfers` holds 1 to 32 objects `{from_handle,to_handle,amount,note?,visibility?}` with ordinary payment rules and defaults. Malformed batch shape (missing, not an array, 0 or 33+ entries, entry not an object) 422 `validation_failed`. Unknown fields ignored. T at 1, 32, 33.
- I04 Entry errors: unknown handle 404; self-transfer 422 `self_payment`; amount/note/visibility rules 422. The first failing entry in input order decides, and entry errors come before insufficient funds. T.
- I05 Affordable iff every wallet's balance after all incoming and outgoing transfers is non-negative (net, so money may pass through a wallet); otherwise 409 `insufficient_funds`. All movements commit together or none. T: pass-through chain with an empty middle wallet succeeds; one unaffordable leg rolls back all.
- I06 Failed validation or 409 claims no key and creates no payment. T.
- I07 201 `{settlement_id, committed_at, payments}`, payments in input order; each member is an ordinary payment with `settlement_id` set, `request_id` null and `created_at` equal to `committed_at`. Payments outside a settlement expose `settlement_id: null`. T.
- I08 Members follow the ordinary feed rule; the settlement response and its replay contain every member's receipt, including private ones the operator is not party to. Replay 200 with the complete original response. T.
- I09 Reset/import preserve operator permissions, original payments, requests, settlement membership and retry responses (see H05); reset with a new fixture replaces operators. T.
- I10 Concurrent settlements and payments over shared wallets keep B01 and B02. C.

## Choices (Architect readings where the specification is silent)

1. Check order on the five idempotent paths: 401 auth, (settlements only) 403 non-operator, key header (400 missing / 422 too long), body parse (400), claimed-key resolution (200 replay / 409 reuse), field validation (422, then 400 for other wrong types as C02/C04 define), handle lookup (404), self rule (422), resource state (404 unknown request, 403, 409 not pending), funds (409). Reason: §7 fixes the position of key resolution; the rest follows the order of §5.
2. A handle value that is a string but does not match `^[a-z0-9_]{1,20}$` (`""`, `"ADA"`, `"@ada"`) is 422 `validation_failed`; a well-formed unknown handle is 404. Reason: §5 format rule; supplied checks allow either.
3. Idempotency scope is (user, method, path, key). Body equality is JSON-value equality with numbers compared numerically (`100` equals `100.0`); unknown fields are part of the body.
4. Emails are compared exactly as given (no case folding). `email_taken` is checked before `handle_taken`. Email form: exactly one `@`, non-empty local and domain parts, no whitespace.
5. In `POST /settlements`, everything wrong inside `transfers` other than the named 404 and `self_payment` cases is 422 `validation_failed` (§11 "malformed batch shape"), including a handle of the wrong JSON type.
6. An empty (zero-length) body on `POST /requests/{id}/pay` is treated as `{}`; decline and cancel ignore any body.
7. Unknown routes give 404 `not_found`; a known route with an unsupported method gives 405 with the error envelope and code `method_not_allowed`.
8. Timestamps are UTC with `+00:00`. Lists order by `created_at` descending with creation sequence as tie-break (later created first); seeded items take the reset time, later fixture entries being newer.
9. Before the first reset the service is empty with currency `EUR`, `minor_units` 2.
10. A request with amount 0 (zero split share) can be paid: it creates a payment of 0 and becomes `paid`.
11. `settlement_operator_ids` naming an unknown user id is accepted and ignored.
12. Password hashing cost is chosen so that a 50-user reset and 50 concurrent logins stay inside the §2 time limits on 2 vCPU; hashing must not stall other requests.

== END OF ACCEPTANCE MAP. END OF HANDOFF (FINAL part 5 of 5). ==
Implementer: build stage-1/ now, self-check every row, commit, hand the full revision to the Verifier and report to the Architect. Verifier: prepare your check list and scripts from the specification now; no verdict and no reply until a committed revision is handed to you.
