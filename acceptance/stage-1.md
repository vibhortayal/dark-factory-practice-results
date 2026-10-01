# Acceptance map — Pocketful stage 1

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (whole file). Target folder: `stage-1/`.
Every row must hold. "Check" says how the row is verified: `H` = supplied harness suite
(partial sample only), `T` = the seat's own black-box HTTP test against the built container,
`C` = concurrency test (many in-flight requests), `I` = inspection of files/source/image.
A row is accepted only on Verifier evidence for the head revision.

## D — Delivery and deployment (§2)

| Row | Requirement | Check |
|---|---|---|
| D1 | `stage-1/` contains the HTTP service source, a `Dockerfile` and a `RUN.md` whose command builds and starts the service with no manual setup. No nested `.git`. | I + run RUN.md command verbatim |
| D2 | Image runs alone with `docker run -e PORT=<port> -p <port>:<port>`; compose is not needed to start it. | T: `docker build` + `docker run`, then `/health` |
| D3 | No outbound network at run time: all deps, init, seed data inside the image; service works with `--network none`/internal network. | H `--mode isolated` + I |
| D4 | Within 2 vCPU / 2 GiB; healthy within 60 s of start. | T: `docker run --cpus 2 --memory 2g`, time to first 200 |
| D5 | Up to 50 requests in flight; each request < 5 s (`/_test/reset`, export, import < 10 s). | C: 50-way mixed load, max latency |
| D6 | State is in-container and ephemeral; no dependency on volumes or host files. | I |
| D7 | No source code, API docs or schemas from existing products in this domain used. | I |
| D8 | Folder implements stage 1 only: no stage-2+ surface (no UI screens, no `/authorizations`, no `/statement`, no refunds/corrections). Harness must print `claimed stage: 1`. | H + T: stage-2+ routes are 404 |

## R — Runtime contract (§3)

| Row | Requirement | Check |
|---|---|---|
| R1 | Listens on `0.0.0.0:$PORT`, default `8080` when `PORT` unset. | T: run with and without `-e PORT` |
| R2 | `GET /health` → 200 `{"status":"ok"}` once service and store are ready. No auth. | T/H |
| R3 | `POST /_test/reset` with fixture → 204, empty body; replaces **all** state (users, tokens, payments, requests, splits, settlements, idempotency records, operators, currency). After 204 only the fixture is visible. No auth. | T: write state, reset, old tokens 401, old data gone |
| R4 | Repeated resets work, including a reset to a different currency/minor_units. | T |
| R5 | Responses are `application/json; charset=utf-8` (all JSON responses, including errors). | T: header check on every endpoint |
| R6 | Response timestamps are RFC 3339 with an explicit offset (e.g. `+00:00`). | T: regex on every `created_at`/`committed_at` |
| R7 | Unknown request-body fields are ignored, never an error (all endpoints, incl. nested settlement transfers). | T |
| R8 | Unknown query parameters are ignored. | T |
| R9 | IDs are opaque strings ≤ 64 chars (generated ids). Fixture ids are kept verbatim. | T |
| R10 | Unknown route / unsupported method returns a 4xx with the §5 error body (404 `not_found`), never 5xx or a non-JSON body. | T |

## M — Model and fixture (§4)

| Row | Requirement | Check |
|---|---|---|
| M1 | One currency from the fixture; `currency` and `minor_units` (0, 2 or 3; EUR/JPY/BHD) are reported by `/me` and on payments/requests/splits. | T with EUR, JPY, BHD fixtures |
| M2 | Amounts are exact integers of minor units. JSON `1000`, `1000.0`, `1e3` are the same valid amount. Booleans and strings are not numbers. Responses emit integers (`1000`, not `1000.0`). | T |
| M3 | Handle: unique, `^[a-z0-9_]{1,20}$`, immutable. Seeded users use the fixture handle. | T |
| M4 | Signup handle derived from email: local part → lowercase → every char outside `[a-z0-9_]` replaced by `_` → truncated to 20. E.g. `Jo.Ann+x@ex.com` → `jo_ann_x`; 25-char local part truncated to 20. | T: signup then `/me` |
| M5 | New users start at balance 0 and can immediately receive money and be asked for money. | T |
| M6 | Seeded users can log in immediately with the fixture password. | T/H |
| M7 | Fixture `balance` is the balance after seeded payments; seeded payments are **not** replayed against balances. | T: `/me` equals fixture balance |
| M8 | Seeded payments appear in `/activity` under the feed rule with their id, parties, amount, note, visibility, `request_id` (null unless fixture links one), `settlement_id` null, and a valid `created_at`. | T/H |
| M9 | Seeded requests appear in `GET /requests` for their two parties with fixture id, amount, note, status; a seeded `pending` request can be paid/declined/cancelled. | T/H |
| M10 | A fixture `balance` < 0 → `POST /_test/reset` returns 422 `validation_failed` and **changes nothing** (previous state fully intact). | T |
| M11 | Fixture `settlement_operator_ids` (array of user ids, default `[]`) defines operators. | T |
| M12 | `amount` ≤ 1000000000 per request; balances stay exact within ±2^53 (no float rounding anywhere). | T: large balances near 2^53, exact arithmetic |
| M13 | A request may exceed the payer's balance: legal at creation, stays `pending`; pay while short → 409 `insufficient_funds` and changes nothing; becomes payable after money arrives. | T |
| M14 | Request lifecycle: `pending` → exactly one of `paid`, `declined`, `cancelled`; terminal states never change. | T + C |
| M15 | No administrative balance endpoint, no directory/user-search endpoint, no deposits/top-ups/withdrawals. | T: such routes 404 |

## I — Invariants (§1), under concurrency and retries

| Row | Requirement | Check |
|---|---|---|
| I1 | Sum of all wallet balances always equals the total seeded by the last reset (also after signups, splits, settlements, import). | C: sum of `/me` across all users after concurrent load |
| I2 | No wallet balance is ever negative, including transiently (concurrent overdraft attempts: exactly the affordable number succeed, rest 409 `insufficient_funds`). | C: N parallel payments draining one wallet |
| I3 | A payment request moves money at most once (concurrent `pay` with different keys: one 201, others 409 `request_not_pending`; pay vs decline vs cancel races yield exactly one outcome). | C |
| I4 | Debit and credit are one atomic step; a failed payment leaves no trace in either wallet or in the feed. | T + C |
| I5 | No request produces a 5xx, including under 50-way concurrent load and malformed input. | C + fuzz of bad bodies/headers |

## E — Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| E1 | Every 4xx/5xx body is `{"error":{"code":"...","message":"..."}}` with the specified status and code. | T on every error row |
| E2 | 400 `malformed_request`: unparseable body, or a field of the wrong JSON type (e.g. `to_handle: 5`, `email: 1`, `participant_handles: "x"`, body that is not a JSON object). | T |
| E3 | 400 `missing_idempotency_key`: header absent or empty on the five idempotent paths. | T |
| E4 | 401 `unauthenticated`: missing, malformed or unknown bearer token, on every authenticated endpoint. | T |
| E5 | 403 `forbidden`: authenticated but not permitted. | T |
| E6 | 404 `not_found`: no such resource or not visible to caller. | T |
| E7 | 409 `idempotency_key_reuse`: key already used by this caller with a different body. | T |
| E8 | 422 `validation_failed`: required field or query parameter missing, or a stated rule violated with no more specific code. | T |
| E9 | Correct JSON type but invalid format / out of range → 422 (invalid dates, negative counts, values over a stated maximum or length). | T |
| E10 | Field-rule precedence: invalid `amount` (including strings, booleans, non-integral numbers, null) → 422; non-string `note` (including `null`) → 422; any `visibility` other than `public`/`private` (any type) → 422. Omission alone selects the defaults. Other wrong types → 400. | T |
| E11 | Integer query parameters are plain decimal digits only: `1e9`, `4.0`, `+4`, `-1`, empty, `abc` → 422. | T on `limit` and `offset` |
| E12 | `Idempotency-Key` longer than 255 characters → 422 `validation_failed` (1..255 valid; 255 accepted, 256 rejected). | T |
| E13 | `limit` integer 1..200 else 422 (0, 201 rejected; 1, 200 accepted); `offset` ≥ 0 else 422. | T |

## A — Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| A1 | `POST /auth/signup {email,password,display_name}` → 201 `{user_id, display_name, token}`; token works at once. | T |
| A2 | `POST /auth/login {email,password}` → 200 `{user_id, display_name, token}`. | T/H |
| A3 | Email already registered → 409 `email_taken`. | T |
| A4 | Password shorter than 8 characters → 422 (7 rejected, 8 accepted). | T |
| A5 | `email` not of form `local@domain` → 422. | T |
| A6 | Wrong password or unknown email on login → 401 `unauthenticated`. | T |
| A7 | Derived handle already taken (different email, same derived handle, incl. collision with a seeded handle and collision after truncation) → 409 `handle_taken`, **no account created** (login with that email then 401; email remains free). | T |
| A8 | Every endpoint except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, `/auth/signup`, `/auth/login` requires `Authorization: Bearer <token>`. | T |
| A9 | Tokens do not expire; one account may hold several valid tokens concurrently (two logins → both tokens valid). | T |
| A10 | Passwords stored with a password-hashing function (bcrypt/scrypt/Argon2 or equivalent); never plaintext, including inside the export state. | I + T: export contains no plaintext password |
| A11 | Missing required signup/login field → 422; wrong JSON type → 400. | T |

## K — Idempotency (§7), for each of `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`

| Row | Requirement | Check |
|---|---|---|
| K1 | Header absent or empty → 400 `missing_idempotency_key`. | T ×5 |
| K2 | First use → normal response, 201. | T ×5 |
| K3 | Replay (same user, method, path, JSON-equal body) → 200 with body identical to the original as a JSON value; no further state change. | T ×5 |
| K4 | Same key, different body (same user, same path) → 409 `idempotency_key_reuse`. | T ×5 |
| K5 | Key reused after the original failed with 4xx → treated as first use (failed attempts claim no key). | T |
| K6 | Key scoped to the authenticated user: two users using the same key string do not interact. | T |
| K7 | Same key + same body on a different path (e.g. `/requests/a/pay` vs `/requests/b/pay`, or `/payments` vs `/requests`) is a different request and succeeds normally. | T |
| K8 | "Same body" is JSON-value equality: key order and whitespace irrelevant. `{}` vs `{"visibility":"public"}` are different. | T |
| K9 | Concurrent identical requests on an unused key: exactly one 201, all others 200 with the same body; effect happens once. | C ×5 |
| K10 | A successful replay returns the original response even after the resource later changed (e.g. request since paid/cancelled). | T |
| K11 | Once body parsed as a JSON object and caller authenticated, a claimed key is resolved before field validation or current-resource checks: a successful request re-sent with the same key and a now-invalid body → 409 `idempotency_key_reuse` (not 422/404). | T |

## P — API (§8)

| Row | Requirement | Check |
|---|---|---|
| P1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}`. | T/H |
| P2 | `POST /payments {to_handle, amount, note?, visibility?}` → 201 payment `{payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, settlement_id: null, created_at}`; balances move by `amount`. | T/H |
| P3 | `note` defaults to `""`, `visibility` defaults to `"public"`. | T |
| P4 | Balance below `amount` → 409 `insufficient_funds`; paying the exact full balance succeeds. | T |
| P5 | `amount` < 1, > 1000000000, or non-integer → 422 (0, -1, 1.5, 1000000001 rejected; 1 and 1000000000 accepted). | T |
| P6 | `to_handle` is caller's own handle → 422 `self_payment`. | T |
| P7 | `note` longer than 200 characters → 422 (200 accepted, 201 rejected; length counted in characters, not bytes). | T |
| P8 | `visibility` not `public`/`private` → 422. | T |
| P9 | No user with that handle → 404 `not_found`. | T |
| P10 | `note` stored and returned verbatim: no trim, no escaping, no normalisation; Unicode and emoji round-trip byte for byte (leading/trailing spaces, `<b>`, combining characters, non-NFC forms). | T |
| P11 | `POST /requests {payer_handle, amount, note?}` → 201 request `{request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at}`; caller is requester; payer balance not checked. | T/H |
| P12 | Request errors: amount rule → 422; own handle → 422 `self_request`; note > 200 → 422; unknown handle → 404. | T |
| P13 | `POST /requests/{id}/pay {visibility?}` (payer only) → 201 with the created payment exactly as `POST /payments` returns it, `request_id` set; request becomes `paid` with `payment_id`; payment's note is the request's note. | T/H |
| P14 | Pay errors: not `pending` → 409 `request_not_pending`; payer short → 409 `insufficient_funds` (nothing changes); caller not payer → 403 `forbidden`; unknown request → 404. | T |
| P15 | Replaying a successful pay (same key, same body) → 200 with the original payment body even though the request is `paid`; no extra money moves; never 409 `request_not_pending`. | T |
| P16 | `POST /requests/{id}/decline` (payer only, no idempotency key) → 200 request with `status: "declined"`; repeat → 200 current state; `paid` or `cancelled` → 409 `request_not_pending`; not payer → 403; unknown → 404. | T |
| P17 | `POST /requests/{id}/cancel` (requester only, no idempotency key) → 200 request with `status: "cancelled"`; repeat → 200; `paid` or `declined` → 409 `request_not_pending`; not requester → 403; unknown → 404. | T |
| P18 | `GET /requests` → `{requests, has_more}`; only requests where caller is requester or payer; newest first by `created_at`. | T/H |
| P19 | `direction`: `incoming` (caller is payer), `outgoing` (caller is requester), absent = both; unknown value → 422. | T |
| P20 | `status`: one of `pending`, `paid`, `declined`, `cancelled`, absent = all; unknown value → 422. | T |
| P21 | `limit` default 50 (1..200), `offset` default 0 (≥ 0); `has_more` true iff items exist beyond the last returned. | T: page boundaries |
| P22 | `POST /splits {amount, participant_handles, note?}` → 201 `{split_id, amount, currency, note, shares, requests, created_at}`. `shares` covers every participant incl. caller in given order and sums to `amount`; `requests` covers every participant except the caller in the same order, each `pending`, caller as requester, amount = that share, note = split note. | T/H |
| P23 | Caller may be included or omitted in `participant_handles`; if omitted the caller gets no share (shares are over the listed handles only). | T |
| P24 | Split errors: amount rule → 422; `participant_handles` empty or with a duplicate → 422; note > 200 → 422; any unknown handle → 404; nothing is created on error. | T |
| P25 | A split whose only participant is the caller is valid: one share, `"requests": []`. No split checks any balance. | T |
| P26 | `GET /activity` → `{payments, has_more}`; newest first by `created_at`; `limit`/`offset` exactly as `GET /requests`. | T/H |
| P27 | Feed rule: a payment appears iff `visibility` is `public` OR caller is sender or receiver. Private payments visible to both parties, hidden from third parties (including operators). | T |
| P28 | Requests and splits never appear in `/activity`; requests are never visible to third parties (third party sees none in `GET /requests`; pay/decline/cancel by an outsider is 403). | T |
| P29 | Visibility is one value on the payment, identical for every viewer; a request carries no visibility. | T |

## S — Money and rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| S1 | Shares are whole minor units, sum exactly to `amount`, differ by at most one; larger shares go to the first participants in given order. Table: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333,333,333; 5/5 → 1,1,1,1,1. | T: all five rows |
| S2 | Different `participant_handles` order gives the extra unit to a different person. | T |
| S3 | A share of 0 is legal and still creates a request for that participant (amount 0, pending). Paying a 0 request must not break conservation or produce 5xx. | T |
| S4 | Each split's shares are independent of previous splits; after any number of splits are paid in full, balances still sum to the seeded total. | T |

## X — Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| X1 | `GET /_test/export` (no auth) → 200 JSON object with `track: "pocketful"`, `format_version: 1`, `state` (JSON object). | T |
| X2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically replaces all state. | T |
| X3 | Import works in a **fresh second container** of the same image (no dependency on the source process, files, volume, port or address). | T: export from container A, import into container B |
| X4 | Import is replacement, not merge: previous destination data and credentials are gone; repeating the import duplicates nothing. | T |
| X5 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track or version, or invalid state → 422 `validation_failed`, destination unchanged. | T |
| X6 | Export is an atomic read-only snapshot; later writes on the source do not change an already-taken export; export itself changes nothing. | T + C: export during load is internally consistent (balances sum to seeded total) |
| X7 | Preserved across export→import: accounts and hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests, operator permissions, handles. Ids and timestamps identical (not regenerated); balances not re-applied. | T: compare `/me`, `/activity`, `/requests` before and after |
| X8 | All completed idempotent request bodies and original responses preserved: replay after import → 200 with the original body; same key with different body → 409. Failed request keys remain reusable. | T |
| X9 | Reset after import clears everything, including imported state. | T |
| X10 | Export/import complete within 10 s. | T |
| X11 | Settlement membership, settlement retry responses and operator permissions survive export→import. | T |

## N — Atomic net settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| N1 | `POST /settlements` requires an operator and an idempotency key: no token → 401; authenticated non-operator → 403 `forbidden`. | T |
| N2 | Body `{"transfers":[{from_handle,to_handle,amount,note?,visibility?}, ...]}`; 1..32 objects (0 and 33 rejected; 1 and 32 accepted). Malformed batch shape (missing/non-array `transfers`, non-object entry, count out of range) → 422 `validation_failed`. | T |
| N3 | Each entry follows ordinary payment rules: amount 1..1000000000 integral; note string ≤ 200, default `""`; visibility `public`/`private`, default `public`. Unknown handle → 404; `from_handle == to_handle` → 422 `self_payment`. Unknown fields ignored. | T |
| N4 | Entry errors take precedence in input order (first failing entry decides the error), and before insufficient funds. | T: batch with entry-2 invalid and entry-3 unknown handle → entry-2's error; unaffordable + invalid entry → entry error |
| N5 | Affordability is on the **net**: affordable iff every wallet's balance after all transfers is ≥ 0; a wallet may send more than its starting balance if incoming transfers in the same batch cover it (e.g. bob has 0: ada→bob 100, bob→cy 50 succeeds). Otherwise 409 `insufficient_funds`. | T |
| N6 | All-or-nothing: on any failure nothing commits — no payment, no balance change, no idempotency key claimed. | T + C |
| N7 | Success → 201 `{settlement_id, committed_at, payments}` with `payments` in input order; each member is an ordinary payment with `settlement_id` set, `request_id` null, and `created_at` equal to `committed_at` (identical across members). | T |
| N8 | Every payment object in every response (payments, pay, activity, replays) carries `settlement_id`; null for non-members. | T |
| N9 | Members follow ordinary feed visibility: private members visible only to their sender/receiver; the operator sees them in `/activity` only if public or a party. The settlement response itself always contains every member. | T |
| N10 | Operator permission grants nothing else: operator cannot see or act on others' requests or private activity. The operator may move money between wallets that are not their own, and may be a party. | T |
| N11 | Replay → 200 with the original complete response; concurrent identical → one 201; different body same key → 409. | T + C |
| N12 | Invariants I1/I2 hold under concurrent settlements mixed with payments. | C |
| N13 | Operators come from the last reset/import; reset without `settlement_operator_ids` → no operators. | T |

## Decisions recorded by the Architect (spec is silent or needs a reading)

| # | Choice | Reason |
|---|---|---|
| Q1 | Check order on idempotent writes: authentication (401) → `Idempotency-Key` presence (400) and length (422) → body parses as a JSON object (400) → claimed-key resolution (200 replay / 409 reuse) → permission (403, e.g. non-operator) and field validation → resource checks → funds. | §7 last paragraph fixes key resolution after parse+auth and before validation; auth-first matches "No token gives 401". |
| Q2 | Validation order inside an endpoint: wrong JSON type (400) / field rules (422) before handle lookup (404) before self-payment/self-request (422) before funds (409). For settlements, per entry in input order. | §11 "Entry errors take precedence in input order, before insufficient funds"; shape before existence is the conventional reading. |
| Q3 | `amount: null` is treated as an invalid amount (422), a missing `amount` is 422. | §5: invalid `amount` values → 422; missing required field → 422. |
| Q4 | Paying a share-0 request succeeds (201) and creates a payment of amount 0. | §9 makes a 0 request legal and §8 pay has no amount rule of its own; the request exists and is payable by its payer. |
| Q5 | Seeded payments/requests without a timestamp in the fixture get a server-assigned `created_at` at reset; fixture order is treated as oldest-first. | Fixture format has no timestamp; a valid RFC 3339 value is still required. |
| Q6 | A non-pending decline/cancel by the wrong party is 403 (permission before state). | "Only the payer / only the requester" is the gate on the resource. |
| Q7 | Fixture and import numbers are API amounts: `balance`, seeded payment `amount` and seeded request `amount` in `POST /_test/reset` accept any integral JSON number form (`10000`, `10000.0`, `1e4`); non-integral or non-numeric values are 422. A negative balance stays 422. (Verifier finding F2, round 1.) | §4 says "Every amount in the API is an integer count" and "API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3`"; reset is an API endpoint and the sentence is unscoped. |
| Q8 | No input may yield a 5xx or a non-§5 error body: unsupported/unknown HTTP methods and unparseable request targets get a 4xx with the §5 body (404 `not_found` for unknown method/route, 400 `malformed_request` for an unparseable request line/target); numbers with extreme exponents are handled as ordinary invalid/ignored values; strings that cannot be encoded (lone surrogates) are accepted or rejected with 4xx; an import whose `state` would later make any endpoint fail is rejected with 422 at import. (Verifier finding F1, round 1.) | §5 "Requests must not produce 5xx responses"; §10 "an invalid state give 422 ... without changing the destination". |
