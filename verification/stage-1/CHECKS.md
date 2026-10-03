# Verifier check list — Pocketful stage 1

Derived from `pocketful/spec/stage-1.md` clause by clause, before reading the Implementer's
code or tests. Every check names the specification section it tests and the acceptance-map rows.
Scripts: `deliver.py` (build, start, limits; runs `checks.py`) and `checks.py` (HTTP behaviour).

Firm assertions fail the check. Where the specification leaves a choice open the script records a
`note` (probe) instead: non-object body 400 vs 422, empty-string query value, missing key vs field
validation order, signup without `display_name`, `state: {}` on import, a body with invalid UTF-8,
paying a zero-amount split request, `Z` as the timestamp offset.

Sizes used: fixtures of 2-60 users, up to 60 seeded payments/requests, notes up to 201 characters,
settlements up to 33 transfers, at most 50 requests in flight (the stated limit).

## Delivery and runtime (deliver.py)

| Check | Spec | Map rows | What it checks |
|---|---|---|---|
| A1-files | §2 | A1 | `Dockerfile` and `RUN.md` exist in the stage folder |
| A1-clean-build | §2 | A1 | `docker build --no-cache` of the stage folder succeeds |
| A1-runmd (manual) | §2 | A1 | The command in RUN.md, followed verbatim, builds and starts the service with no manual setup |
| A2-default-port | §3.1, §3.2 | A2,A4 | Without PORT the service answers on 8080 through a port mapping, healthy within 60 s |
| A2-port-env | §2, §3.1 | A2,A4 | With `-e PORT=9123` and a port mapping the service answers (listens on 0.0.0.0) |
| A2-port-sanity | §3.1 | A2 | Probe sanity: an unmapped port does not answer |
| A3-network-none | §2 | A3 | Container starts and stays up with `--network none` |
| A4-timed-start | §2, §3.2 | A4 | Start to first healthy response under `--cpus 2 --memory 2g`, limit 60 s |
| HTTP-check-list | all | A5-J6 | All checks below, against a 2 vCPU / 2 GiB container on a network without outbound access |
| A5-no-oom, A5-no-oom-src | §2 limits | A5 | Containers were not OOM-killed or restarted during the run |
| Supplied (manual) | task | all | Harness `--stage 1`, normal and `--mode isolated`, fresh `--out` each; Implementer's own tests |
| Scope (manual) | task, §1 | A10 | Stage folder implements no later-stage feature; route list equals the specification's |
| E7-code (manual) | §6 | E7 | Password hashing function in the code is scrypt/bcrypt/Argon2 or equivalent |
| Maintainability (manual, note only) | — | A11 | One read of the code; self-contained folder, no nested repository |

## HTTP behaviour (checks.py)

| Check | Spec | Map rows | What it checks |
|---|---|---|---|
| A4-health | §3.2 | A4 | GET /health -> 200 {"status":"ok"}; unknown query parameter ignored; no auth needed |
| A8-unknown-fields | §3.4 | A8 | Unknown body fields and unknown query parameters are ignored on every endpoint |
| A9-ids | §3.4 | A9 | Generated IDs are strings of at most 64 characters; seeded IDs are kept as given |
| A10-out-of-scope | §1, §4 | A10 | Deposits, top-ups, withdrawals and an admin balance endpoint are out of scope: no such route changes a balance |
| B2-overspend | §1 inv 1,2 | B1,B2 | 20 parallel payments of 100 from a wallet holding 500: exactly 5 succeed, 15 are 409 insufficient_funds, balance never negative, sum preserved |
| B3-pay-once | §1 inv 3, §8 pay | B3 | 10 parallel pays of one request with different keys: exactly one 201, the rest 409 request_not_pending, money moves once |
| B3-race-terminal | §1 inv 3, §4 requests | B3 | Concurrent pay / decline / cancel of one request leave exactly one terminal state, consistent with the money moved |
| B4-exact-2p53 | §4 arithmetic range | B4 | Balances up to 2^53 stay exact: seed near 2^53, move 1 unit at a time, compare exactly |
| C1-reset-replaces | §3.3 | C1,C7 | Reset returns 204 without auth and replaces all state: users, tokens, payments, requests, idempotency records, operators; repeated resets work |
| C2-seeded-users | §4 fixture, §8 /me | C2,C3,G1 | Seeded users log in at once; /me shows seeded id, display_name, handle, balance (not replayed), currency, minor_units |
| C4-seeded-records | §4 fixture, feed contract | C4 | Seeded payments appear in /activity under the feed rule with the full payment shape; seeded requests appear in /requests with their status |
| C5-negative-balance | §4 fixture | C5 | Fixture balance below zero -> 422 validation_failed and nothing changes; balance 0 is accepted |
| C6-currencies | §4 model, fixture | C6 | minor_units 0, 2, 3 (JPY, EUR, BHD); currency echoed on /me, payments, requests, splits |
| C8-reset-malformed | §3.3, §5 | C8 | Unparseable reset body -> 400 malformed_request; state unchanged |
| D1-error-shape | §5 | D1 | Every 4xx body is {error:{code,message}}, including unknown routes and wrong methods |
| D2-malformed | §5 | D2 | Unparseable body, or a field of the wrong JSON type (other than amount/note/visibility) -> 400 malformed_request |
| D3-field-rules | §5 bullet 1, §8, §11 | D3,D5,D6 | Invalid amount (string, boolean, null, fractional, <1, >1e9, array, object), non-string note incl. null, note of 201 chars, and any visibility other than public/private -> 422 validation_failed on every endpoint taking them; nothing moves |
| D4-integral-forms | §4 model | D4 | JSON 1000, 1000.0 and 1e3 are the same valid amount; 1000.5 is 422 |
| D5-amount-bounds | §4 arithmetic range, §8, §11 | D5 | amount 0 -> 422, 1 ok, 1000000000 ok, 1000000001 -> 422 on payments, requests, splits and settlement entries |
| D6-note | §8 payments note | D6 | note of 200 characters ok, 201 -> 422 (characters, not bytes); stored and returned verbatim (no trimming, escaping or normalisation) on payments, requests, splits, settlements, feed and replay |
| D7-missing-fields | §5 | D7 | A missing required field -> 422 validation_failed |
| D8-query-digits | §5 bullet 2 | D8 | Integer query parameters must be plain decimal digits: 1e1, 4.0, +4, -1, abc -> 422 on /requests and /activity |
| D9-limit-offset | §5 shared ranges, §8 GET /requests, GET /activity | D9,G12,G16 | limit 1..200 (0, 201 -> 422; 1, 200 ok), default 50; offset >= 0, default 0; has_more true iff items exist beyond the last returned |
| D10-idem-key-header | §5 shared ranges, §7 | D10 | Idempotency-Key absent or empty -> 400 missing_idempotency_key; 255 chars ok; 256 -> 422 validation_failed; on all five paths |
| D11-unauthenticated | §5, §6, §11 | D11,E9,F10,I1 | Missing, malformed or unknown bearer token -> 401 unauthenticated on every protected endpoint, before body and key checks; health, reset, export, signup, login need no token |
| E1-signup | §6, §4 users | E1,B1 | Signup -> 201 {user_id, display_name, token}; balance 0; can be paid and asked for money immediately |
| E2-handle-derivation | §4 users and handles | E2,E8 | Handle derived from the email: local part, lowercased, characters outside [a-z0-9_] -> _, truncated to 20 |
| E3-signup-conflicts | §6 table, §4 | E3 | Email already registered -> 409 email_taken; derived handle taken (seeded or signed-up, incl. by truncation) -> 409 handle_taken and no account is created |
| E4-signup-validation | §6 table | E4 | Password shorter than 8 characters -> 422 (7 fails, 8 ok); email not of the form local@domain -> 422 |
| E5-login | §6 | E5,E6 | Login -> 200 {user_id, display_name, token}; wrong password or unknown email -> 401; tokens do not expire on new login; several tokens valid at once |
| F1-replay | §7 table | F1,F3,F9 | On each of the five paths: first use 201; replay 200 with the identical JSON body and no further effect; same key with a different body 409 idempotency_key_reuse, also when the new body is invalid |
| F2-same-body | §7 | F2 | Same body means the same JSON value: key order and whitespace do not matter; {} and {"visibility":"public"} differ |
| F4-key-scope | §7 | F4,F5 | Key is scoped to the authenticated user; the same key and body on a different path is a new request and succeeds |
| F6-failed-key-reusable | §7 table | F6 | A key whose original request failed with 4xx is treated as a first use afterwards, with the same or a different body |
| F7-concurrent-identical | §7 | F7,B1 | 20 concurrent identical requests with an unused key on each of the five paths: exactly one 201, the others 200 with the same body, one effect |
| F8-replay-after-change | §7 | F8,G9 | A successful replay returns the original response even after the resource changed or was cancelled, or the balance no longer covers it; no further state change |
| F10-order | §7 last paragraph, §5 | F10 | Order of checks: 401 first; a claimed key is resolved before field validation and current-resource checks |
| G2-payment | §8 POST /payments | G2,G3,G4 | Payment 201 body, defaults, atomic debit+credit; errors insufficient_funds (balance == amount ok), self_payment, not_found; a failed payment leaves no trace |
| G5-request | §8 POST /requests, §4 requests | G5,G6 | Request 201 body; caller is requester; payer balance not checked; errors self_request, not_found |
| G7-pay | §8 pay, §4 requests | G7,G8,G17 | Pay: payer only; 201 payment with request_id; request becomes paid with payment_id; visibility is the payer's; errors 404, 403, 409 request_not_pending, 409 insufficient_funds (changes nothing, payable later) |
| G10-decline-cancel | §8 decline, cancel; §4 requests | G10,G11 | Decline: payer only, 200 declined, repeat 200, paid/cancelled 409, non-payer 403, unknown 404. Cancel: requester only, 200 cancelled, repeat 200, paid/declined 409, non-requester 403, unknown 404. No idempotency key needed; no money moves |
| G12-list-requests | §8 GET /requests, §4 feed contract | G12,G17 | GET /requests: only the caller's (requester or payer); newest first; direction and status filters; unknown values 422; shape {requests, has_more} |
| G13-split | §8 POST /splits | G13,G14,G15,G17 | Split 201 body; shares cover all participants in the given order; requests for every participant except the caller, caller as requester; caller included or omitted; errors; caller-only split valid; no balance check; not a feed item |
| G16-activity | §4 feed contract, §8 GET /activity | G16,G17 | Activity: payments only; visible iff public or the caller is sender or receiver; one visibility value seen by both parties; newest first; shape {payments, has_more} |
| H1-rounding | §9 | H1,H2 | Equal-split table: 1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3 -> 4,3,3; 999/3 -> 333 x3; 5/5 -> 1 x5; order moves the extra unit; a share of 0 still produces a request |
| H3-splits-paid | §9 last paragraph | H3,B1 | Shares are independent across splits; after several splits are paid in full the balances still sum to the seeded total |
| I1-settlement-auth | §11 | I1,I2 | Settlements: no token 401; non-operator 403 forbidden; operator may move money between wallets it is not party to; the permission grants no access to others' requests or private activity |
| I3-settlement-shape | §11 | I3,I4,D3 | transfers holds 1..32 objects (0 and 33 -> 422; 1 and 32 ok); malformed batch shape -> 422; entry rules and defaults as for payments; unknown fields ignored |
| I4-settlement-errors | §11 | I4,I6 | Unknown handle 404; self-transfer 422 self_payment; entry errors take precedence in input order and before insufficient funds; a failed settlement claims no key and creates no payment |
| I5-net-affordability | §11 | I5,B1,B2 | Affordability is net over the whole batch: a wallet may pass on money it receives in the same batch, in any input order; otherwise 409 insufficient_funds and nothing moves |
| I7-settlement-response | §11 | I7,I8 | 201 {settlement_id, committed_at, payments in input order}; members are ordinary payments with settlement_id set, request_id null and created_at == committed_at; non-members show settlement_id null; replay 200 with the complete original response |
| A5-load-50 | §2 resource limits, §5 last line, §1 invariants | A5,A6,B1 | 50 requests in flight (mixed reads, payments, requests, logins): no 5xx, each under 5 s, sum of balances preserved; reset of a 60-user fixture under 10 s |
| J1-export-import | §10 | J1,J2,J3,J4,E7 | Export shape; import of an unchanged export -> 204, replaces (not merges) all state; accounts, password login, tokens, balances, payments, requests, operators, settlement membership, ids, timestamps and idempotency records survive; failed keys stay reusable; repeat import duplicates nothing; reset clears imported state |
| J5-import-invalid | §10, §5 | J5 | Import: invalid JSON -> 400 malformed_request; missing fields, wrong track, wrong format_version or invalid state -> 422 validation_failed; destination unchanged |
| J6-cross-container | §10 | J3,J6 | Export from one container, import into a second, fresh container, with the source container stopped before verification: everything is preserved with no dependency on the source process, files, port or address |
| A6-no-5xx | §5 last line | A6 | Across every request sent by this run: no 5xx response and no transport error |
| A7-content-type | §3.4 | A7 | Across every response with a body: Content-Type is application/json; charset=utf-8 |
| A5-latency | §2 resource limits | A5 | Across every request sent by this run: under 5 s (10 s for /_test/* control calls) |
