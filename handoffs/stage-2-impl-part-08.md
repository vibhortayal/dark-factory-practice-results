@vibhor15/nightshift-implementer
Rows: all stage-2 rows + stage-1 regression · Revision: stage-1 accepted at 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb; base = head of main · Files: stage-2/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-2 HANDOFF PART 8/9 — ACCEPTANCE MAP acceptance/stage-1.md (verbatim, regression baseline)

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
