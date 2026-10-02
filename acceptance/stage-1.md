# Acceptance map — pocketful stage 1

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (the specification wins over this map
wherever they differ). Target folder: `stage-1/`. Every row must hold; the supplied harness
suite covers only part of it. "Check" says how the row is verified: `H` = supplied harness
suite, `T` = own test against the running container, `L` = load/concurrency test under the
stated limits, `I` = inspection of code/image.

## A. Delivery and runtime (§1–§3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds a complete HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts it with no manual setup | I, T (follow RUN.md verbatim) |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose needed; all dependencies, init and seed data inside the one container | T (`docker run --network none`-style / harness `--mode isolated`) |
| A3 | No outbound network at run time; nothing fetched at start | T (isolated mode), I |
| A4 | Works within 2 vCPU / 2 GiB; first healthy response within 60 s of start | T (`--cpus 2 --memory 2g`, time to health) |
| A5 | Up to 50 requests in flight; every request under 5 s (reset/export/import under 10 s) | L (50 concurrent mixed requests under the limits, max latency recorded) |
| A6 | Listens on `0.0.0.0`, port from `PORT`, default `8080` | T (with and without `PORT`) |
| A7 | `GET /health` → 200 `{"status":"ok"}` once service and store can serve | H, T |
| A8 | `POST /_test/reset` → 204 no content; replaces ALL state with the fixture; later requests see only the fixture; repeatable; no auth; enabled in the delivered image | H, T (reset twice, old tokens/users/payments/keys gone) |
| A9 | Requests and responses are `application/json; charset=utf-8` (response header on every JSON body) | T |
| A10 | Response timestamps are RFC 3339 with an explicit offset | T (regex on every `created_at` / `committed_at`) |
| A11 | Unknown body fields ignored; unknown query parameters ignored | H, T |
| A12 | IDs are opaque strings ≤ 64 chars (generated and seeded ids both served) | T |
| A13 | No request ever produces a 5xx, including under concurrent load and with hostile input | L, T (fuzz of bad bodies/params) |
| A14 | Stage 2+ surface is NOT implemented (no UI, no `/authorizations`, etc.) | I, H (harness later-stage probe) |

## B. Invariants (§1, §4 arithmetic)

| Row | Requirement | Check |
|---|---|---|
| B1 | Sum of all wallet balances always equals the total seeded by the last reset — also during concurrency and retries | L (sum via `/me` of every user after bursts) |
| B2 | No balance is ever negative, even transiently | L (concurrent overspend: N payers racing on one wallet, exactly affordable count succeed) |
| B3 | A payment request moves money at most once (pay vs pay, pay vs decline/cancel races) | L |
| B4 | Amounts are exact integers; no float rounding up to balances of ±2⁵³; amounts serialised as JSON integers | T (large balances near 2⁵³, max amount), I |
| B5 | Money moves only between existing wallets; no deposit/top-up/withdraw/admin-balance endpoints | I |

## C. Model and fixture (§4)

| Row | Requirement | Check |
|---|---|---|
| C1 | One currency from the fixture; `minor_units` 0, 2 or 3 (EUR/JPY/BHD) reported by `/me` and on payments/requests/splits `currency` | H, T |
| C2 | Amount accepts JSON `1000`, `1000.0`, `1e3` as the same value; booleans and strings are not numbers | H, T |
| C3 | Handle unique, matches `^[a-z0-9_]{1,20}$`, immutable; seeded users take the fixture handle | T |
| C4 | Signup handle derived from email: local part → lowercase → every char outside `[a-z0-9_]` becomes `_` → truncate to 20 | H, T (`Jo.Ann+x@…` → `jo_ann_x`, 25-char local part) |
| C5 | New users start at balance 0, can receive money and be requested immediately | H, T |
| C6 | Seeded users can log in immediately with the fixture password | H, T |
| C7 | Seeded `balance` is final (seeded payments are NOT replayed against it) | H, T |
| C8 | Negative seeded balance → `POST /_test/reset` returns 422 `validation_failed` and changes nothing (previous state fully intact) | H, T |
| C9 | Seeded payments and requests (any status) are served with their fixture ids, parties, amount, note, visibility/status; seeded pending request can be paid; non-pending cannot | H, T |
| C10 | `settlement_operator_ids` optional, default `[]`; `payments`, `requests` absent are treated as empty | T |
| C11 | Unparseable reset body → 400 `malformed_request`; invalid fixture → 422 `validation_failed`, state unchanged | T |

## D. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code":…,"message":…}}`, including unknown routes and framework-generated errors | T |
| D2 | 400 `malformed_request`: unparseable body, body not a JSON object, or field of the wrong JSON type (other than the D4 exceptions) | H, T |
| D3 | 422 `validation_failed`: required field or query parameter missing; correct type but invalid format / out of range / over a stated maximum or length | H, T |
| D4 | Field-rule precedence: invalid `amount` (incl. string, boolean, null, non-integral, <1, >1000000000), non-string `note` (incl. `null`), any `visibility` other than `public`/`private` → 422 `validation_failed`; omission selects the default | H, T |
| D5 | Integer query parameters are plain decimal digits only: `1e9`, `4.0`, `+4`, `abc`, empty, negative → 422 | H, T |
| D6 | `limit` 1..200, `offset` ≥ 0, `Idempotency-Key` 1..255 chars, otherwise 422 on every endpoint that takes them (empty/absent key is 400 `missing_idempotency_key`) | H, T (255 ok, 256 → 422, 10 kB → 422) |
| D7 | 401 `unauthenticated` for missing, malformed or unknown bearer token on every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login` | T (each endpoint) |
| D8 | 403 `forbidden`, 404 `not_found` (missing resource or not visible to caller) as listed per endpoint | H, T |

## E. Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; token works immediately | H, T |
| E2 | `POST /auth/login` → 200 `{user_id, display_name, token}` | H, T |
| E3 | Email already registered → 409 `email_taken` | T |
| E4 | Password shorter than 8 characters → 422; exactly 8 accepted | T |
| E5 | `email` not of the form `local@domain` → 422 | T |
| E6 | Wrong password or unknown email on login → 401 `unauthenticated` | T |
| E7 | Derived handle already taken → 409 `handle_taken`, no account created (login afterwards is 401, email still free) | H, T |
| E8 | Tokens never expire; several valid tokens / concurrent sessions per account | T (login twice, both tokens work) |
| E9 | Passwords stored only via a password-hashing function (bcrypt/scrypt/Argon2 or equivalent); no plaintext anywhere incl. export | I, T (export contains no plaintext password) |

## F. Idempotency (§7) — applies independently to each of the five write paths

| Row | Requirement | Check |
|---|---|---|
| F1 | Required on `POST /payments`, `/requests`, `/requests/{id}/pay`, `/splits`, `/settlements`; absent or empty → 400 `missing_idempotency_key` | H, T |
| F2 | First use → normal response 201 | H |
| F3 | Replay (same user, method, path, body-as-JSON-value) → 200 with body identical to the original as a JSON value; key order/whitespace irrelevant | H, T |
| F4 | Same key, different body → 409 `idempotency_key_reuse` | H, T |
| F5 | Key reused after the original failed with 4xx → treated as first use (failed requests claim no key) | H, T |
| F6 | Keys scoped per authenticated user; same key by two users does not interact | H |
| F7 | Same key + same body on a different path is a different request and succeeds normally | H, T |
| F8 | Concurrent identical requests on an unused key: exactly one 201, the rest 200 with the same body, effect applied once | L |
| F9 | Successful replay returns the original response even after the resource changed or was cancelled; no further state change | H, T |
| F10 | Once body parsed as a JSON object and caller authenticated, an already-claimed key is resolved BEFORE field validation and current-resource checks (successful request → same key with invalid body = 409 `idempotency_key_reuse`; replay of paid request = 200 not `request_not_pending`) | H, T |
| F11 | No key header check on decline/cancel | H |

## G. Endpoints (§8)

| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}` | H |
| G2 | `POST /payments` 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, created_at` (+ `settlement_id: null`, see I6) | H, T |
| G3 | `note` default `""`, `visibility` default `"public"` | H |
| G4 | Balance below amount → 409 `insufficient_funds`, no trace in either wallet or feed; paying exactly the balance succeeds | H, T |
| G5 | `amount` <1, >1000000000, non-integer → 422; exactly 1 and 1000000000 in range | H, T |
| G6 | `to_handle` is caller's own → 422 `self_payment` | H |
| G7 | `note` longer than 200 characters (code points) → 422; exactly 200 (incl. 200 emoji) accepted | H |
| G8 | Bad `visibility` → 422 | H |
| G9 | No user has that handle → 404 `not_found` | H |
| G10 | Debit and credit are one atomic step | L, I |
| G11 | `note` stored and returned verbatim, byte for byte (no trim/escape/normalise; unicode, emoji, leading/trailing whitespace, combining characters) | H, T |
| G12 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at`; caller is requester | H |
| G13 | `/requests` rejections: amount range/integer 422; own handle 422 `self_request`; note >200 → 422; unknown handle 404; payer balance NOT checked | H, T |
| G14 | `POST /requests/{id}/pay`: payer only; body `visibility` optional default public; returns 201 with a payment exactly as `POST /payments` with `request_id` set; request becomes `paid` and carries `payment_id` | H, T |
| G15 | pay rejections: unknown request 404; caller not payer 403; not pending 409 `request_not_pending`; payer short 409 `insufficient_funds` and nothing changes (request stays pending and becomes payable once funded) | H, T |
| G16 | `{}` vs `{"visibility":"public"}` on the same key → 409 `idempotency_key_reuse` | H |
| G17 | `POST /requests/{id}/decline`: payer only (else 403); 200 with request `status: "declined"`; already declined → 200 current state; paid/cancelled → 409 `request_not_pending`; unknown → 404 | H, T |
| G18 | `POST /requests/{id}/cancel`: requester only (else 403); 200 `status: "cancelled"`; already cancelled → 200; paid/declined → 409 `request_not_pending`; unknown → 404 | H, T |
| G19 | `GET /requests`: only requests where caller is requester or payer; newest first by `created_at`; `direction` incoming/outgoing/absent; `status` one of four or absent; unknown value → 422; `{requests, has_more}` | H, T |
| G20 | `limit` default 50 (1..200), `offset` default 0 (≥0); `has_more` true iff items exist beyond the last returned (exact at boundaries) | H, T |
| G21 | `POST /splits` 201 body: `split_id, amount, currency, note, shares[{handle, amount}], requests[…], created_at`; `shares` covers every participant incl. caller in given order and sums to `amount`; `requests` covers every participant except the caller in the same order, caller is requester, each `pending` | H, T |
| G22 | Caller may be included or omitted in `participant_handles`; caller-only split valid → one share, `requests: []`; no balance checked | H, T |
| G23 | splits rejections: amount range/integer 422; empty list or duplicate handle 422; note >200 → 422; any unknown handle 404 | H, T |
| G24 | `GET /activity`: payments only, newest first, `{payments, has_more}`; a payment is listed iff `visibility` is public OR caller is sender or receiver; same paging rules as `/requests`; request-only params ignored | H, T |
| G25 | Requests and splits never appear in the feed; private payment visible to both its parties with the same `visibility` value, hidden from third parties (incl. operators) | H, T |

## H. Money and rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| H1 | Shares are whole minor units, sum exactly to `amount`, differ by at most 1; larger shares go to the first participants in given order | H, T (table: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3; 5/5) |
| H2 | A share of 0 is legal and still creates a request (amount 0) for that participant; a 0-amount request can be paid | H, T |
| H3 | Different handle order moves the extra unit; each split independent of earlier splits | H, T |
| H4 | After splits are paid in full, balances still sum to the seeded total | T |

## I. Export/import (§10) and settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` (no auth) → 200 `{track: "pocketful", format_version: 1, state: {…}}`; atomic read-only snapshot unaffected by later writes | H, T |
| I2 | `POST /_test/import` (no auth) takes that object unchanged, atomically REPLACES state (no merge; repeat import does not duplicate; previous data and credentials removed) → 204 | H, T |
| I3 | Import preserves: accounts + hashed-password login, existing bearer tokens, currency/minor units, balances, payments, requests, operator permissions, settlement membership, ids, timestamps, completed idempotent bodies and original responses (replay after import → 200 same body, changed body → 409), failed keys stay reusable | T (export → reset to other fixture → import → compare everything) |
| I4 | Import works with no dependency on the source process/files/port (export from one container, import into a fresh one) | T |
| I5 | Import: invalid JSON → 400 `malformed_request`; missing fields, wrong `track`, wrong `format_version`, invalid `state` → 422 `validation_failed`, destination unchanged | T |
| I6 | Reset clears all state including imported state; test-control calls finish under 10 s | T |
| I7 | `POST /settlements`: no token 401; authenticated non-operator 403 `forbidden`; operator + idempotency key required | H, T |
| I8 | `transfers` has 1..32 objects `{from_handle, to_handle, amount, note?, visibility?}` with ordinary payment rules and defaults; malformed batch shape (missing/not an array/0 or 33+ entries/non-object entry) → 422 `validation_failed` | T |
| I9 | Entry errors: unknown handle 404; self-transfer 422 `self_payment`; amount/note/visibility 422; the first failing entry in input order decides, and all entry errors come before `insufficient_funds` | T |
| I10 | Affordable iff every wallet's balance after ALL transfers (net) is ≥ 0 — a wallet may forward money it only receives in the same batch; otherwise 409 `insufficient_funds` | H, T (ada→bob 100, bob→cy 50 with bob at 0) |
| I11 | All-or-nothing: on any failure no payment exists, no balance moves, no key is claimed | T |
| I12 | 201 `{settlement_id, committed_at, payments[…in input order]}`; each member is an ordinary payment with `settlement_id` set, `request_id: null`, `created_at` == `committed_at` for all; every non-member payment (everywhere payments are returned) exposes `settlement_id: null` | H, T |
| I13 | Members follow ordinary feed visibility (from = the transfer's `from_handle`, not the operator); operator status grants no access to others' requests or private payments | T |
| I14 | Settlement replay → 200 with the original complete response; fifth idempotent path obeys all F rows | T |
| I15 | Operator permission, settlement membership and retry responses survive export/import; reset replaces operators with the new fixture's list | T |

## Recorded choices (where the specification leaves room)

1. Request processing order on idempotent paths: authenticate (401) → for `/settlements`, operator
   check (403) → `Idempotency-Key` absent/empty (400) or over 255 chars (422) → body parse, must be a
   JSON object (400) → claimed-key resolution (200 replay / 409 reuse) → field validation → resource
   checks. Reason: §7 fixes key resolution after auth + parse and before validation; 401/403 first is
   the conventional reading of §11 "requires an operator".
2. Body equality for replays is JSON-value equality with numbers compared numerically (`1000` ==
   `1000.0` == `1e3`). Reason: §7 "same JSON value after parsing" and §4 "all represent the same".
3. A handle string that cannot match `^[a-z0-9_]{1,20}$` (e.g. `ADA`, `@ada`, `""`) → 404
   `not_found`: no user has that handle; the endpoint table names that error (§5 "unless an endpoint
   specifies a different error"). A non-string handle → 400 `malformed_request`.
4. pay/decline/cancel check order: 404 unknown → 403 wrong party → 409 `request_not_pending` →
   409 `insufficient_funds`. A non-party gets 403 (endpoint tables), not 404.
5. `participant_handles` not an array, or with a non-string element → 400 `malformed_request`
   (general wrong-type rule); `transfers` of the wrong shape → 422 (§11 says so explicitly).
6. Timestamps use a numeric offset (`+00:00`), as in every spec example. Ordering "newest first"
   uses a strictly increasing internal sequence as the tie-breaker so paging is deterministic.
7. Unknown routes → 404 `not_found` in the error envelope.
8. Signup checks `email_taken` before `handle_taken` (the same email always derives the same
   handle, so the reverse order would make `email_taken` unreachable). Emails compare exactly as
   given. Missing `email`/`password`/`display_name` → 422; wrong JSON type → 400.
9. Seeded payments/requests have no timestamp in the fixture: `created_at` is assigned at reset,
   preserving fixture order (later entries newer). A seeded paid request has `payment_id: null`
   unless the fixture supplies one.
10. Password hashing cost must be chosen so that a reset of a fixture with a few hundred users
    completes inside the 10 s control timeout on 2 vCPU, and 50 concurrent logins stay under 5 s.
