# Acceptance map: stage 1

Source: `pocketful/spec/stage-1.md` in the kickoff checkout (§ numbers below refer to it).
Target folder: `stage-1/`. Every row must hold; the supplied checks cover only some rows.
"Check" says how the Verifier establishes the row: `H` = supplied harness run,
`P` = the Verifier's own HTTP probe against the built image, `I` = inspection of source or image.

Rows marked **[D]** record a decision the Architect made where the specification leaves a
choice open; the reason is given so the choice can be re-examined, not waived.

## A. Delivery and runtime (§2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds source, a `Dockerfile` and a `RUN.md` whose command builds and starts the service with no manual setup. No `.git`, submodule or symlink inside the folder. | I, P: follow RUN.md literally from a clean build |
| A2 | The image runs alone with `-e PORT=<port>` and a port mapping; listens on `0.0.0.0:$PORT`, default `8080` when `PORT` is unset. | P: run with and without `PORT` |
| A3 | No outbound network at run time; all dependencies, initialisation and seed data inside the one container; Compose is not needed to start. | H `--mode isolated`; P: `docker run --network none` plus exec probe, or internal network |
| A4 | Healthy within 60 s of container start: `GET /health` -> 200 `{"status":"ok"}`. | P: time from `docker run` to first 200 |
| A5 | Works within 2 vCPU / 2 GiB with up to 50 requests in flight; each request < 5 s (reset, export, import < 10 s). | P: run with `--cpus 2 --memory 2g`, 50-way bursts, record max latency |
| A6 | No request produces a 5xx, including under concurrent load and with hostile input (huge numbers, deep or huge bodies, wrong types, non-UTF-8 bytes, unknown routes and methods). | P: fuzz table + bursts, assert no status >= 500 |
| A7 | Requests and responses are `application/json; charset=utf-8`; a request without or with a different `Content-Type` but a parseable JSON body must not 5xx. | P: header check on success and error responses |
| A8 | Every timestamp in a response is RFC 3339 with an explicit numeric offset (`+00:00` form, not a bare local time). | P: regex over every `created_at` / `committed_at` |
| A9 | Unknown body fields are ignored; unknown query parameters are ignored. | H, P |
| A10 | Every ID is an opaque string of at most 64 characters, including seeded IDs returned unchanged. | P |
| A11 | Every 4xx/5xx body is `{"error":{"code":..., "message":...}}`, including 404 for an unknown route and 405-style cases. Unknown route is 404 `not_found` (after auth where the route family needs it). | P |

## B. Reset, fixture, model (§3.3, §4)

| Row | Requirement | Check |
|---|---|---|
| B1 | `POST /_test/reset` with a fixture -> 204, no auth; afterwards only that fixture is visible: earlier users, tokens, payments, requests, idempotency records, settlements and operator grants are gone. Repeated resets work. | H, P: reset twice with different fixtures, old token -> 401 |
| B2 | Seeded users can log in at once with the fixture password; seeded `id`, `handle`, `display_name`, `balance` are returned unchanged. | H, P |
| B3 | Seeded `balance` is final: seeded payments are not replayed against it. | P: fixture with a seeded payment, balances equal fixture values |
| B4 | Seeded payments appear in the feed under the feed contract with their seeded `id`, parties, `amount`, `note`, `visibility`; `request_id` and `settlement_id` null; a server-assigned `created_at`. | H, P |
| B5 | Seeded requests appear to their two parties only, keep `id`, `amount`, `note`, `status`; a pending one can be paid, declined, cancelled; a non-pending one behaves as that status. | H, P |
| B6 | A fixture with a `balance` below zero -> 422 `validation_failed` and the previous state is untouched (same tokens, balances, records). | H, P |
| B7 | `minor_units` 0, 2 or 3 with `currency` from the fixture are reported by `GET /me` and on every payment/request/split. One currency per service. | H, P for EUR, JPY, BHD |
| B8 | `payments`, `requests`, `settlement_operator_ids` are optional in the fixture and default to empty. Unparseable reset body -> 400 `malformed_request`, state untouched. **[D]** Any other structurally invalid fixture (not an object, `users` not an array, duplicate user id/handle/email, a record naming an unknown user, `minor_units` outside 0/2/3, non-integer balance) -> 422 `validation_failed`, state untouched. Reason: reset must be all-or-nothing and must not 5xx. | P |
| B9 | Invariant 1: the sum of all wallet balances equals the seeded total after every operation, burst and retry. | H, P: sum `GET /me` over all users after each burst |
| B10 | Invariant 2: no balance is ever negative, even transiently (no debit-then-check ordering that a concurrent reader could observe). | P: concurrent readers during a drain burst; I: debit is guarded in the same atomic step |
| B11 | Invariant 3: a payment request moves money at most once (concurrent pay attempts with different keys: exactly one 201). | P: 50-way burst |
| B12 | Amounts are exact integers end to end; balances up to ±2^53 are exact; responses print amounts as JSON integers, never `1000.0` or exponent form. | P: seed a balance near 2^53, move 1 unit, read back |
| B13 | Handles match `^[a-z0-9_]{1,20}$`, are unique and never change. | P, I |

## C. Errors and input rules (§5, §4 amounts)

| Row | Requirement | Check |
|---|---|---|
| C1 | Unparseable body -> 400 `malformed_request`. **[D]** A body that parses but is not a JSON object (array, string, number, null) -> 400 `malformed_request` (wrong JSON type). An empty body on an endpoint that needs a body is unparseable -> 400. C1 governs the authenticated API endpoints; for `POST /_test/reset` and `POST /_test/import` a body that parses as JSON but is not an object is a structurally invalid fixture/export -> 422 (rows B8, J6). An empty or absent body on `POST /requests/{id}/pay`, whose body is entirely optional, may be treated as `{}`. | H, P |
| C2 | A field of the wrong JSON type -> 400 `malformed_request`, except the endpoint-specific rules in C3..C5. Applies e.g. to `to_handle`, `payer_handle`, `from_handle` as number/null/array, `participant_handles` not an array or holding a non-string, `email`/`password`/`display_name` not strings. | P |
| C3 | `amount`: valid iff a JSON number with integral value in 1..1000000000. `1000`, `1000.0`, `1e3` are the same valid amount. Strings, booleans, `null`, fractions, 0, negatives, above the maximum, and numbers too large to represent (`1e400`) -> 422 `validation_failed`. | H, P |
| C4 | `note`: optional, default `""`. Any non-string including `null` -> 422. More than 200 characters (Unicode code points, not bytes or UTF-16 units) -> 422. Exactly 200 is accepted. Stored and returned verbatim, byte for byte, no trimming, escaping or normalisation. | H, P |
| C5 | `visibility`: optional, default `"public"`. Anything other than exactly `"public"` or `"private"` (including `null`, `""`, `"Public"`, numbers) -> 422. | H, P |
| C6 | A missing required field or required query parameter -> 422 `validation_failed`. | H, P |
| C7 | A value of the right type but invalid format or out of range -> 422 unless the endpoint names another error. **[D]** A string handle that matches no user, including one that cannot match the handle pattern (`""`, `"ADA"`, `"@ada"`), is 404 `not_found`: the endpoint tables name 404 for "no user has that handle", and §5 lets an endpoint-specific error win. | H (accepts 404 or 422), P |
| C8 | `Idempotency-Key` absent or empty -> 400 `missing_idempotency_key`; longer than 255 characters -> 422 `validation_failed`; 1..255 accepted (255 exactly passes, 256 fails). | H, P |
| C9 | `limit`: plain decimal digits, 1..200, default 50. `offset`: plain decimal digits, >= 0, default 0. `0`, `201`, `-5`, `abc`, `1e2`, `4.0`, `+4`, empty string -> 422. Enforced on `GET /requests` and `GET /activity`. An offset beyond the end returns an empty page with `has_more: false`, not an error. | H, P |
| C10 | 401 `unauthenticated` for a missing, malformed or unknown bearer token on every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login`. | P: no header, `Bearer`, `Basic x`, unknown token, on each route |
| C11 | **[D]** Order of checks on an idempotent write: (1) authentication 401; (2) for settlements, operator permission 403; (3) `Idempotency-Key` presence 400 and length 422; (4) body parses as a JSON object, else 400; (5) an already-claimed key for this caller, method and path: same body -> 200 replay, different body -> 409 `idempotency_key_reuse`; (6) field validation: wrong types 400, rule violations 422; (7) resource checks in the order of D/E/F/H rows; (8) funds 409. Steps 5-before-6-and-7 are stated by §7; the rest are the least surprising order and are recorded so both seats test the same thing. | P |

## D. Authentication (§6, §4 handles)

| Row | Requirement | Check |
|---|---|---|
| D1 | `POST /auth/signup` `{email,password,display_name}` -> 201 `{user_id,display_name,token}`; new balance 0; the user can receive money and be asked for money at once. | H, P |
| D2 | Derived handle: local part of the email, lowercased, every character outside `[a-z0-9_]` replaced by `_`, truncated to 20 characters. No `handle` field is read from the body. | H, P: `Dee.Ann+tag@…` -> `dee_ann_tag`; 30 chars -> 20; non-ASCII local part |
| D3 | Email already registered -> 409 `email_taken`. Derived handle already taken (by a seeded or a signed-up user) -> 409 `handle_taken` and no account is created (login with that email is 401). **[D]** `email_taken` is tested before `handle_taken` (table order); emails compare exactly as given. | H, P |
| D4 | Password shorter than 8 characters -> 422. `email` not of the form `local@domain` (missing `@`, empty local part, empty domain) -> 422. Missing field -> 422; wrong type -> 400. | P |
| D5 | `POST /auth/login` -> 200 `{user_id,display_name,token}`; wrong password or unknown email -> 401 `unauthenticated`. | H, P |
| D6 | Tokens never expire; an account may hold several valid tokens at once (each login issues a working token and does not invalidate earlier ones). | P |
| D7 | Passwords are stored only as a salted password hash (bcrypt, scrypt, Argon2 or equivalent); never in plaintext, in memory, in the export or in logs. Passwords longer than the hash function's native input limit must not be silently truncated into collisions. | I; P: export contains no fixture password string |
| D8 | Hashing cost fits the limits: reset of a fixture with 200 users returns in < 10 s, and 50 concurrent logins each return in < 5 s, on 2 vCPU. Concurrent signups for the same email or the same derived handle create exactly one account. | P |
| D9 | `GET /me` -> `{user_id,display_name,handle,balance,currency,minor_units}`. | H, P |

## E. Payments (§8)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /payments` `{to_handle,amount,note?,visibility?}` -> 201 with exactly `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id (null), settlement_id (null), created_at`. | H, P |
| E2 | Debit and credit are one atomic step; a failed payment leaves no trace in either wallet or in any feed. | H, P |
| E3 | Balance below `amount` -> 409 `insufficient_funds`; paying exactly the balance succeeds and leaves 0. | H, P |
| E4 | `to_handle` is the caller's own -> 422 `self_payment`. No user has the handle -> 404 `not_found`. | H, P |
| E5 | Amount, note, visibility rules C3..C5. **[D]** Precedence: field validation (400/422) -> unknown handle 404 -> `self_payment` -> `insufficient_funds`. | P |
| E6 | Concurrency: N clients each sending the whole balance -> exactly one 201, the rest 409, balance 0; draining in parts never overdraws; a three-wallet cycle of concurrent payments conserves the total and never deadlocks or 5xxs. | H, P at 50 in flight |

## F. Requests (§4, §8)

| Row | Requirement | Check |
|---|---|---|
| F1 | `POST /requests` `{payer_handle,amount,note?}` -> 201 with exactly `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status "pending", payment_id null, created_at`. Caller is the requester. | H, P |
| F2 | The payer's balance is not checked at creation; a request above it is created and stays pending. A request carries no visibility. | H, P |
| F3 | `payer_handle` is the caller's own -> 422 `self_request`; unknown -> 404; amount and note rules C3, C4. | H, P |
| F4 | `POST /requests/{id}/pay` body `{visibility?}` -> 201 with the created payment (E1 shape) and `request_id` set; the request becomes `paid` and carries `payment_id`; money moves payer -> requester atomically with the status change. | H, P |
| F5 | Pay errors: unknown request 404; caller is not the payer 403 `forbidden` (the requester and any third party alike **[D]**: the pay/decline/cancel tables name 403 for "not the payer/requester"); not pending 409 `request_not_pending`; payer short 409 `insufficient_funds` and nothing changes, the request stays pending and becomes payable once money arrives. **[D]** Precedence: visibility validation -> 404 -> 403 -> not pending -> funds. | H, P |
| F6 | Replaying a successful pay (same key, same body) -> 200 with the original payment even though the request is now `paid`; never 409 `request_not_pending`; no more money moves. `{}` and `{"visibility":"public"}` are different bodies -> 409 `idempotency_key_reuse`. | H, P |
| F7 | `POST /requests/{id}/decline`: payer only, no key needed. 200 with the request `declined`; declining an already declined request is 200 with the current state; `paid` or `cancelled` -> 409 `request_not_pending`; not the payer 403; unknown 404. A body is not required and is ignored. | H, P |
| F8 | `POST /requests/{id}/cancel`: requester only, no key needed. 200 `cancelled`; again on a cancelled one 200; `paid` or `declined` -> 409; not the requester 403; unknown 404. | H, P |
| F9 | A request is `pending` and then exactly one of `paid`, `declined`, `cancelled`; races between pay, decline and cancel resolve to exactly one final state, and money moved iff the final state is `paid`. | P: concurrent pay+decline+cancel bursts |
| F10 | `GET /requests`: only requests where the caller is requester or payer; newest first by `created_at`; `direction` = `incoming` (caller is payer) / `outgoing` (caller is requester) / absent for both; `status` one of the four or absent; unknown `direction` or `status` (including empty) -> 422; `limit`/`offset` per C9; body `{requests:[…], has_more}` with `has_more` true iff items exist past the last returned. | H, P |
| F11 | Requests never appear in `GET /activity`; nobody but the two parties can read a request under any filter, including a settlement operator. | H, P |

## G. Splits and rounding (§8, §9)

| Row | Requirement | Check |
|---|---|---|
| G1 | `POST /splits` `{amount,participant_handles,note?}` -> 201 `{split_id, amount, currency, note, shares:[{handle,amount}], requests:[…], created_at}`. | H, P |
| G2 | Shares: whole units, sum exactly to `amount`, differ by at most one, the larger shares go to the first participants in the given order: 1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3 -> 4,3,3; 999/3 -> 333,333,333; 5/5 -> 1×5. Independent of earlier splits. | H, P |
| G3 | `shares` lists every participant including the caller in the given order. `requests` lists one pending request per participant except the caller, same order, caller as requester, amount = that share, note = the split note. A 0 share still creates a request (amount 0 is legal for a split-created request, and paying it moves 0 and marks it paid). | H, P |
| G4 | The caller may be listed or omitted. If omitted, the amount is divided among the listed participants only **[D]** (shares "cover every participant" and "always sum to amount"; the caller is not a participant unless listed). A split whose only participant is the caller is valid: one share, `requests: []`. | H, P |
| G5 | `participant_handles` empty or with a duplicate -> 422; any unknown handle -> 404; amount and note rules C3, C4. **[D]** Precedence: type errors 400 -> amount/note/empty/duplicate 422 -> unknown handle 404. A 1000-handle list is validated, not crashed, and answers within 5 s. | H, P |
| G6 | A split checks nobody's balance and moves no money. A split is not a feed item. Created requests are atomic with the split: a rejected split creates none. | H, P |
| G7 | After any number of splits are paid in full, balances still sum to the seeded total. | P |

## H. Activity feed (§4, §8)

| Row | Requirement | Check |
|---|---|---|
| H1 | `GET /activity` returns payments only: a payment appears iff it is `public`, or the caller is its sender or receiver. No other rule. | H, P with three users |
| H2 | A `private` payment is visible to both of its parties with the same single `visibility` value, hidden from everyone else, including a settlement operator who is not a party. | H, P |
| H3 | Newest first by `created_at`; `{payments:[…], has_more}`; `limit`/`offset` per C9; request-only parameters (`direction`, `status`) are ignored here. | H, P |
| H4 | Payments made by paying a request and settlement members follow the same rule and carry `request_id` / `settlement_id`. | P |

## I. Idempotency (§7)

| Row | Requirement | Check |
|---|---|---|
| I1 | Five paths need a key: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`. Decline and cancel do not. | H, P |
| I2 | A key is scoped to the authenticated user and to the method and path: two users with one key string do not interact; the same key and body on a different path (including a different `{id}`) is a first use and succeeds. | H, P |
| I3 | First use -> 201. Replay (same user, path, key, body) -> 200 with a body equal as a JSON value to the original, and no state change, even after the resource has since changed (request paid, declined, cancelled; balances moved). | H, P |
| I4 | Same key with a different body -> 409 `idempotency_key_reuse`. Body sameness is JSON-value equality after parsing: key order and whitespace do not matter; an extra unknown field makes it a different body. **[D]** Numbers compare by numeric value (`1000` = `1000.0` = `1e3`). | H, P |
| I5 | A key whose original request failed with 4xx is not claimed: reusing it, with the same or a different body, is a first use. | H, P |
| I6 | An already-claimed key is resolved after authentication and JSON-object parsing and before field validation and resource checks: changing a successful request to an invalid body under the same key is 409 `idempotency_key_reuse`, not 422/404/403. | P |
| I7 | Concurrent identical requests with an unused key: exactly one 201, all others 200 with the same body, one effect. | P: 50-way burst per path |
| I8 | Concurrent same-key requests with different bodies: exactly one takes effect; the others get 409 `idempotency_key_reuse` (or, if theirs failed validation on its own merits before the claim, their own 4xx); never two effects. | P |

## J. Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| J1 | `GET /_test/export` -> 200 `{track:"pocketful", format_version:1, state:{…}}`, no auth; an atomic read-only snapshot unaffected by later writes. | H, P |
| J2 | `POST /_test/import` with an unchanged export -> 204 and atomically replaces all state. It works in a different container of the same image (no dependency on the source process, files, volume, port or address). | P: export from container A, import into fresh container B |
| J3 | Import is replacement, not merge: previous destination users, tokens, records and operator grants are gone; importing twice gives the same state with nothing duplicated. | P |
| J4 | Preserved across export/import: accounts and password login, existing bearer tokens, currency and minor units, balances, payments (ids, timestamps, notes, visibility, links), requests and their status, splits' requests, settlement membership, operator grants, every completed idempotent request's body and original response. Nothing is regenerated or replayed against a balance. | H, P: replay each of the five paths after import -> 200 same body; old token works; feed equal item for item |
| J5 | Keys of failed requests stay reusable after import; new IDs issued after import do not collide with imported ones. | P |
| J6 | Invalid JSON -> 400 `malformed_request`. Missing `track`/`format_version`/`state`, wrong track or version, or an invalid `state` (wrong shape, tampered so it is inconsistent or unreadable) -> 422 `validation_failed`, destination unchanged. Never 5xx. | P |
| J7 | Reset clears everything, including imported state. Export and import each finish within 10 s on a populated state. Export holds password hashes, never plaintext passwords. | P, I |

## K. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| K1 | Fixture `settlement_operator_ids` (array of user ids, default `[]`) grants the operator permission. No token -> 401; authenticated non-operator -> 403 `forbidden`. Users created by signup are never operators. | H, P |
| K2 | `POST /settlements` `{transfers:[{from_handle,to_handle,amount,note?,visibility?}]}` with 1..32 entries; the operator may move money between any wallets, not only their own. | H, P |
| K3 | Malformed batch shape (`transfers` missing, not an array, empty, more than 32, an entry that is not an object) -> 422 `validation_failed`. | P: 0, 1, 32, 33 entries |
| K4 | Each entry follows the payment rules: amount C3, note C4, visibility C5 with defaults; unknown handle (either side) 404; `from_handle` = `to_handle` -> 422 `self_payment`. Entry errors are reported in input order (the first bad entry decides) and always before `insufficient_funds`. **[D]** Inside one entry: field validation -> unknown handle -> self-transfer. A missing handle field is 422; a handle of the wrong JSON type is 400 (C2). | P |
| K5 | Affordability is judged on the net result: the settlement is affordable iff every wallet's balance after all its incoming and outgoing transfers is >= 0, so a wallet may pass money on that it only receives inside the batch, and the order of entries does not matter. Not affordable -> 409 `insufficient_funds`. | H, P: chain a->b->c where b starts at 0 |
| K6 | All or nothing: on any failure no balance changes, no payment is created, and the idempotency key is not claimed. | P |
| K7 | 201 `{settlement_id, committed_at, payments:[…]}` with `payments` in input order; each member is an ordinary payment (E1 shape) with `settlement_id` set, `request_id` null, and `created_at` equal to `committed_at` for every member. Non-members expose `settlement_id: null`. | H, P |
| K8 | Members follow the ordinary feed rule: a private member is visible only to its sender and receiver; the operator sees it only if a party or if public. The 201/replay response still contains every member's receipt. Being an operator gives no access to other users' requests or private payments. | P |
| K9 | Replay -> 200 with the original complete response; same key with a different body -> 409; I-rows apply (fifth idempotent path). Concurrent settlements and payments over the same wallets keep invariants B9..B10. | P |
| K10 | Reset and import preserve operator grants, original payments, requests, settlement membership and retry responses (as the fixture / export state them). | P |

## L. Stage boundary

| Row | Requirement | Check |
|---|---|---|
| L1 | `stage-1/` implements the stage-1 specification only: no browser UI, no endpoints, fields or behaviour from a later stage. The harness overshoot line for stage 2 must be `fail` and the final lines `claimed stage: 1`. | H, I |
| L2 | The code is written to the specification, not to the supplied checks: no behaviour keyed to fixture names, test ids or check-specific values. | I |
| L3 | Maintainable: clear module layout, one place for validation, one for the ledger/atomicity, automated tests the Implementer ran, RUN.md accurate. | I |

## Commands

From `/home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs`:

```sh
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/<new-name>
```

Every run needs a new `--out` directory. The final check of the stage is the isolated one.
