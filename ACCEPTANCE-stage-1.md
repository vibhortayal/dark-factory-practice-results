# Acceptance map — pocketful stage 1

Source of truth: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (§ numbers below refer to it).
Every row must hold. "Supplied" = covered at least partly by the harness suite
(`pocketful/test/stage_1`); "Own" = needs a check written from the spec by the Implementer
(self-check) and independently by the Verifier. Supplied checks are a sample only.

Check kinds: **H** harness run · **T** own HTTP test against the running container ·
**C** own concurrency test (up to 50 in flight) · **I** inspection of files/source/image.

## D. Delivery and runtime (§2, §3)

| Row | Requirement | Check |
|---|---|---|
| D1 | `stage-1/` holds the service source, a `Dockerfile` and a `RUN.md`; `RUN.md` gives a command that builds and starts the service with no manual setup. No nested `.git`. | I; follow RUN.md verbatim from a clean clone |
| D2 | Image runs alone with `-e PORT=<port>` + port mapping; listens on `0.0.0.0:$PORT`, default `8080` when PORT unset. Compose is not needed to start it. | T: run with and without `-e PORT` |
| D3 | No outbound network at run time; all deps, init and seed data inside the single container. | H `--mode isolated`; T `docker run --network none` + exec health |
| D4 | `GET /health` → 200 `{"status":"ok"}` within 60 s of container start; no auth. | H; T timing |
| D5 | Works within 2 vCPU / 2 GiB; 50 requests in flight; every request < 5 s, reset/export/import < 10 s (also with a large fixture, e.g. 500 users, and 50 concurrent logins). | C with `--cpus 2 --memory 2g` |
| D6 | No request produces a 5xx, including under concurrent load and with hostile input (huge/deep JSON, invalid UTF-8, 10 kB header, 1000-element arrays, numbers like `1e400`). | H; C; T fuzz |
| D7 | Requests/responses are `application/json; charset=utf-8` (every response with a body, including errors). 204 responses have no body. | T header check |
| D8 | Timestamps are RFC 3339 with an explicit numeric offset (e.g. `2026-09-24T11:04:03+00:00`). | T regex on every `created_at`/`committed_at` |
| D9 | Unknown body fields are ignored, never an error; unknown query parameters are ignored (e.g. `direction`/`status` on `/activity`). | H; T |
| D10 | IDs are opaque strings ≤ 64 chars; generated IDs never collide with fixture-supplied IDs (e.g. a fixture using `u_1`, `p_1`, `rq_1`) nor after import. | T |
| D11 | Stage 1 only: HTTP API only, no stage-2+ surface (no UI pages or later-stage endpoints). The stage-2 suite must not pass against `stage-1/`. | H (harness probes the next stage); I |
| D12 | Built from the supplied requirements only; no source, API docs or schemas from existing products. | I |

## R. Reset, fixture, model (§3.3, §4)

| Row | Requirement | Check |
|---|---|---|
| R1 | `POST /_test/reset` with a fixture → 204; replaces **all** state (users, tokens, payments, requests, splits, settlements, idempotency records, operators); later requests see only the fixture; repeated resets work; unauthenticated. | H; T: old tokens → 401, old keys unclaimed |
| R2 | Seeded users log in immediately with the fixture password; keep fixture `id`, `handle`, `display_name`, `balance`. | H |
| R3 | `balance` is final: seeded payments are NOT replayed against balances. | T: fixture with payments, `/me` equals fixture balance |
| R4 | Negative `balance` in fixture → 422 `validation_failed`, nothing changes (previous state, tokens intact). Any other invalid fixture → 4xx per §5 (unparseable 400, invalid 422), state unchanged, never 5xx. | H; T |
| R5 | One currency from the fixture; `minor_units` ∈ {0,2,3} (EUR 2, JPY 0, BHD 3); reported by `/me` and `currency` on payments/requests/splits. | H; T for BHD/JPY |
| R6 | Seeded payments (`id, from_user_id, to_user_id, amount, note, visibility`) appear in `/activity` under the feed contract with full payment shape (`request_id: null`, `settlement_id: null`, handles, currency, `created_at`). | H; T |
| R7 | Seeded requests (`id, requester_id, payer_id, amount, note, status`) appear in `/requests` for their two parties only, are payable/declinable/cancellable when `pending`, and non-pending ones give 409 `request_not_pending` on pay. | H; T |
| R8 | Optional `settlement_operator_ids` (array of user ids, default `[]`) grants operator permission; `payments`/`requests` may be absent or empty. | H; T |
| R9 | Handles: unique, `^[a-z0-9_]{1,20}$`, immutable. New (signup) users start at balance 0 and can receive payments and requests immediately. | H; T |
| R10 | All amounts are exact integers of minor units; arithmetic exact up to ±2^53; responses carry amounts as JSON integers (`1500`, never `1500.0` or a string). | T with amounts near 1e9 and balances near 2^53 |

## E. Errors and validation (§5)

| Row | Requirement | Check |
|---|---|---|
| E1 | Every 4xx/5xx body is `{"error":{"code":..., "message":...}}` with the specified status and code — including unknown routes (404 `not_found`). | T on every error path |
| E2 | 400 `malformed_request`: body does not parse as JSON, body is not a JSON object, or a field has the wrong JSON type (other than the E3 exceptions), e.g. `to_handle: 5`, `participant_handles: "ada"` or containing non-strings, `email: 1`. | H; T |
| E3 | Field-specific overrides → 422 `validation_failed`: any invalid `amount` (0, negative, > 1000000000, non-integral like `1.5`, string, boolean, `null`); non-string `note` including `null`; `note` > 200 characters; any `visibility` other than exactly `"public"`/`"private"` (`"Public"`, `""`, `null`, numbers). Omitting `note`/`visibility` selects defaults (`""`, `"public"`). | H; T |
| E4 | `amount` accepts any integral JSON number 1..1000000000: `1000`, `1000.0`, `1e3` are the same valid amount; `1e9` is valid. | H; T raw bodies |
| E5 | Missing required field or query parameter → 422 `validation_failed`. Correct type but bad format/out-of-range → 422. | H; T |
| E6 | `note` length is counted in characters (Unicode code points): 200 emoji accepted, 201 rejected; stored and returned verbatim byte for byte (no trim/escape/normalisation). | H; T with combining marks, whitespace, `<>&"`, NUL-free control chars |
| E7 | `Idempotency-Key`: absent or empty → 400 `missing_idempotency_key`; longer than 255 characters → 422 `validation_failed` (a 10 kB header must still get this, not a transport error); exactly 255 is valid. | H; T |
| E8 | `limit` integer 1..200 (default 50), `offset` integer ≥ 0 (default 0); written as plain decimal digits only: `1e9`, `4.0`, `+4`, `-1`, `abc`, empty → 422 `validation_failed`. `limit=0`, `201` → 422; `1` and `200` valid. | H; T |
| E9 | 401 `unauthenticated` for missing, malformed or unknown bearer token on every endpoint except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, `/auth/signup`, `/auth/login`. | T across all endpoints |

## A. Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| A1 | `POST /auth/signup {email,password,display_name}` → 201 `{user_id, display_name, token}`; token works immediately. A `handle` field in the body is ignored. | H; T |
| A2 | Derived handle: email local part, lowercased, every char outside `[a-z0-9_]` → `_`, truncated to 20 chars (e.g. `Ada.L+x@…` → `ada_l_x`; 30×`a` → 20×`a`). | H; T |
| A3 | Email already registered → 409 `email_taken`; derived handle taken → 409 `handle_taken` and no account is created (login then 401). Concurrent identical signups: exactly one 201. | H; C |
| A4 | Password shorter than 8 characters → 422 (8 is accepted); email not `local@domain` → 422; missing field → 422. | T |
| A5 | `POST /auth/login` → 200 `{user_id, display_name, token}`; wrong password or unknown email → 401 `unauthenticated`. | H; T |
| A6 | Tokens never expire; an account may hold several valid tokens at once (each login/signup issues one; earlier ones stay valid). | T |
| A7 | Passwords stored only as a password hash (bcrypt/scrypt/Argon2 or equivalent); no plaintext in memory state, storage or export. | I source; T: export does not contain the plaintext password |

## I. Idempotency (§7)

| Row | Requirement | Check |
|---|---|---|
| I1 | Exactly five paths require the key: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`. Decline/cancel need none. | H; T |
| I2 | First use → normal response 201. Replay (same user, method, path, same JSON body) → 200 with a body equal as a JSON value to the original; no further state change, even after the resource changed (request paid/cancelled, balances moved). | H; T |
| I3 | Same key, different body → 409 `idempotency_key_reuse`. "Same body" = same JSON value after parsing (key order and whitespace irrelevant). `{}` vs `{"visibility":"public"}` are different. | H; T |
| I4 | Key scope is the authenticated user and the method+path: another user with the same key string is independent; the same key + body on a different path is a new request and succeeds normally. | H; T |
| I5 | A request that failed with 4xx does not claim the key: retrying the same key (same or different body) is a first use (e.g. pay short → 409, fund, retry same key → 201, exactly one payment). | H; T |
| I6 | Once the caller is authenticated and the body parsed as a JSON object, a claimed key is resolved before field validation and before current-resource checks: a successful request re-sent with an invalid body → 409 `idempotency_key_reuse`; a replayed pay on a now-`paid` request → 200, never 409 `request_not_pending`. | H; T |
| I7 | N concurrent identical requests with an unused key: exactly one 201, the rest 200 with the same body; the effect happens once. | C (50 in flight, all five paths) |

## M. `GET /me`, payments (§8)

| Row | Requirement | Check |
|---|---|---|
| M1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}`. | H |
| M2 | `POST /payments {to_handle, amount, note?, visibility?}` → 201 with `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, settlement_id: null, created_at`. | H; T exact key set |
| M3 | Balance below `amount` → 409 `insufficient_funds`, nothing changes; paying exactly the balance succeeds (balance → 0). | H |
| M4 | `to_handle` is the caller's own → 422 `self_payment`; no user with that handle (including strings that cannot be handles: `""`, `ADA`, `@ada`) → 404 `not_found`. | H; T |
| M5 | Debit and credit are one atomic step; a failed payment leaves no trace (no feed item, no balance change, no claimed key). | T; C |
| M6 | Invariants under concurrency and retries: Σ balances == seeded total at all times; no balance ever negative (even transiently); e.g. 50 clients draining one wallet, a 3-wallet cycle, 50 wallets cross-paying. | H (10 clients); C (50) |

## Q. Requests (§4, §8)

| Row | Requirement | Check |
|---|---|---|
| Q1 | `POST /requests {payer_handle, amount, note?}` → 201 with `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at`; caller is requester. | H; T exact key set |
| Q2 | Payer's balance is NOT checked at creation: a request above the payer's balance is created `pending`. | H |
| Q3 | `payer_handle` is the caller's own → 422 `self_request`; unknown handle → 404; amount/note rules per E3. | H; T |
| Q4 | `POST /requests/{id}/pay {visibility?}` (payer only, key required) → 201 with the created payment exactly as `POST /payments` returns it, `request_id` = this request; request becomes `paid` with `payment_id` set; money moves once. Note of the payment = the request's note. | H; T |
| Q5 | Pay errors: unknown request 404 `not_found`; caller not the payer (including the requester, and third parties) 403 `forbidden`; not `pending` 409 `request_not_pending`; payer short 409 `insufficient_funds` with no change, request stays `pending` and becomes payable once funded. | H; T |
| Q6 | A request may move money at most once: concurrent pays with different keys → exactly one 201; pay racing decline/cancel → exactly one of them wins and the final state is consistent. | C |
| Q7 | `POST /requests/{id}/decline`: payer only, no key; 200 with the request `status: "declined"`; already declined → 200 current state; `paid` or `cancelled` → 409 `request_not_pending`; not the payer → 403; unknown → 404. | H; T |
| Q8 | `POST /requests/{id}/cancel`: requester only, no key; 200 `status: "cancelled"`; already cancelled → 200; `paid` or `declined` → 409 `request_not_pending`; not the requester → 403; unknown → 404. | H; T |
| Q9 | `GET /requests`: only requests where the caller is requester or payer (operators get nothing extra); newest first by `created_at`; `direction` = `incoming` (caller is payer) / `outgoing` (caller is requester) / absent = both; `status` = `pending|paid|declined|cancelled` / absent = all; unknown `direction`/`status` → 422; `limit`/`offset` per E8; response `{requests:[…], has_more}` with `has_more` true iff items exist beyond the last returned. | H; T paging edges |
| Q10 | Requests carry no visibility and never appear in `/activity`. | H |

## S. Splits and rounding (§8, §9)

| Row | Requirement | Check |
|---|---|---|
| S1 | `POST /splits {amount, participant_handles, note?}` → 201 `{split_id, amount, currency, note, shares:[{handle, amount}], requests:[…], created_at}`. `shares` covers every listed participant (caller included if listed) in the given order and sums to `amount`; `requests` covers every participant except the caller in the same order, each `pending`, caller as requester, amount = that share. Caller may be listed or omitted. | H; T both variants |
| S2 | Equal-split rule: whole units, differ by at most 1, larger shares to the first participants: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333×3; 5/5 → 1×5. Reordering handles moves the extra unit. Each split independent of earlier ones. | H; T table |
| S3 | A share of 0 is legal and still creates a request for that participant. | H |
| S4 | Caller as the only participant is valid: one share, `requests: []`. Nothing in a split checks any balance; a split moves no money and is not a feed item. | H; T |
| S5 | Errors: amount per E3; `participant_handles` empty or with a duplicate → 422; note > 200 → 422; any unknown handle → 404; 1000 handles → 4xx, never a crash. A failed split creates no requests. | H; T |
| S6 | After splits are paid in full, Σ balances still equals the seeded total. | T |

## F. Activity feed (§4, §8)

| Row | Requirement | Check |
|---|---|---|
| F1 | `GET /activity` returns payments only; a payment is listed iff `visibility` is `public` OR the caller is its sender or receiver. No other rule. Private payments are visible to both parties and hidden from third parties (operators included). | H; T three-party matrix |
| F2 | Newest first by `created_at`; `{payments:[…], has_more}`; `limit`/`offset` exactly as `GET /requests` (E8). | H; T |
| F3 | Payment objects in the feed are identical (as JSON values) to the receipt returned at creation, for direct, request-paying, settlement and seeded payments. | T |

## X. Export / import (§10)

| Row | Requirement | Check |
|---|---|---|
| X1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{…}}`; atomic read-only snapshot (consistent under concurrent writes; later writes do not alter an already returned export). | H; C: Σ balances in effect after import == seeded total |
| X2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically **replaces** all state (previous destination data, credentials and tokens gone); repeating the import yields the same state with no duplicates. | H; T |
| X3 | Import works in a different container of the same image (no dependency on source process, files, volume, port, address). | T: export from container A, import into fresh container B |
| X4 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track or version, or an invalid `state` → 422 `validation_failed`; destination unchanged in every failure case. | T |
| X5 | Preserved across export→(reset)→import: accounts and password login, existing bearer tokens, currency/minor_units, balances (not re-derived), payments, requests, splits' requests, operator permissions, settlement membership (`settlement_id`), IDs and timestamps unchanged, feed/request ordering unchanged. | H; T deep-equal of `/me`, `/activity`, `/requests` for every user before/after |
| X6 | Preserved idempotency: every completed key replays 200 with the original body after import (all five paths); a completed key with a different body still gives 409; keys of failed requests remain reusable. | T |
| X7 | After import, newly generated IDs do not collide with imported ones; reset after import clears everything including imported state. | T |

## T. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| T1 | `POST /settlements` needs a token (else 401), an operator (authenticated non-operator → 403 `forbidden`) and an idempotency key. Operator status comes from fixture `settlement_operator_ids`. Operator permission grants no access to others' requests or private activity. | H; T |
| T2 | Body `{transfers:[{from_handle,to_handle,amount,note?,visibility?}]}` with 1..32 entries; each entry follows payment amount/note/visibility rules (defaults `""`, `public`); unknown fields ignored. Malformed batch shape (missing/non-array `transfers`, 0 or > 32 entries, non-object entry) → 422 `validation_failed`. | T at 0, 1, 32, 33 |
| T3 | Entry errors: unknown handle → 404; `from_handle == to_handle` → 422 `self_payment`; the first failing entry in input order decides the response, and entry errors come before insufficient funds. | T ordering cases |
| T4 | Affordable iff every wallet's balance after ALL incoming and outgoing transfers is ≥ 0 (net): e.g. bob with 0 may pass on 50 of an incoming 100 in the same batch; ada→bob 100 and bob→ada 100 leaves balances unchanged. Otherwise 409 `insufficient_funds`. | H; T |
| T5 | All-or-nothing: on any failure no payment is created, no balance changes, no key is claimed. Under concurrency Σ balances and non-negativity hold. | T; C |
| T6 | 201 `{settlement_id, committed_at, payments:[…]}` in input order; each member is an ordinary payment (sender = `from_handle`'s user, receiver = `to_handle`'s user) with `settlement_id` = the batch, `request_id: null`, and `created_at` == `committed_at` for all members. Non-member payments expose `settlement_id: null` everywhere. | H; T |
| T7 | Members follow ordinary feed visibility (a private member is hidden from a non-party operator's `/activity`, yet the settlement response holds every receipt). Replay → 200 with the complete original response. | T |
| T8 | Reset/import preserve operator permissions, payments, requests, settlement membership and retry responses (see X5, X6). | T |

## Architect decisions on points the spec leaves open

These are binding for this run unless a seat shows a spec sentence that contradicts one;
report such a conflict instead of silently deviating.

1. **Check order on the five idempotent paths**: authenticate (401) → for `/settlements` operator check (403) → `Idempotency-Key` present (400) and ≤ 255 chars (422) → body parses as a JSON object (400) → claimed-key resolution (200 replay / 409 reuse) → field validation (422/400) → resource checks: 404, then 403, then self_* 422, then 409 `request_not_pending`, then 409 `insufficient_funds`. Reason: §7 fixes the position of key resolution; the rest is the most conventional order consistent with the supplied checks.
2. **Empty request body** on an endpoint that reads a body is unparseable → 400 `malformed_request`. Decline and cancel never read a body. The request `Content-Type` header is not required for parsing.
3. **Handle lookups**: a `*_handle` string that matches no user (including strings that violate the handle pattern) → 404 `not_found`; a non-string handle → 400 `malformed_request`. Reason: §8 tables ("No user has that handle") and §5 wrong-type rule.
4. **Idempotent body equality** is JSON-value equality on the whole parsed object: numbers compare by numeric value (`1000` == `1000.0` == `1e3`), unknown fields are part of the body.
5. **Split `n`** is the number of handles in `participant_handles`; an omitted caller gets no share. The created requests take the split's `note`. A 0-amount request can be paid (a 0-amount payment, 201) — no rule forbids it.
6. **Emails** are compared exactly as given (no case folding or trimming); `local@domain` means exactly one `@` with non-empty text on both sides. Signup check order: field validation (422) → `email_taken` → `handle_taken`.
7. **Ordering**: lists are newest first by `created_at` with a deterministic creation-sequence tie-break (later created first); seeded items are stamped at reset time in fixture array order.
8. **Unknown routes/methods** → 404 `not_found` with the error body. Oversized or otherwise unacceptable input must still produce a 4xx with the standard error body, never 5xx.
9. **Timestamps** use a numeric offset (`+00:00`), not `Z`.
10. **Settlement entry check order** within one entry: batch shape → amount/note/visibility (422) → handle types (400) → unknown handle (404) → self-transfer (422 `self_payment`).
