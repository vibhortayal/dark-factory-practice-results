# Stage 1 acceptance map (pocketful)

Source: `pocketful/spec/stage-1.md` (kickoff checkout). Every row is a statement of the
specification with the way it is checked. "API test" means a black-box HTTP check against the
running container. Rows marked **[reading]** record a choice the Architect made where the
specification leaves the point open; the reason is given. The supplied harness checks cover
only part of this map.

## A. Delivery and runtime (§2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds the service source, a `Dockerfile` and a `RUN.md` with one command that builds and starts it with no manual setup. No `.git`, submodule or symlink inside the folder. | Inspect folder; follow RUN.md from a clean clone |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; listens on `0.0.0.0:$PORT`, default `8080`. Compose is never needed. | `docker run` with and without `PORT`; curl `/health` |
| A3 | No outbound network at run time; all dependencies, initialisation and seed data inside the single container. | Harness `--mode isolated`; `docker run --network none`-style check |
| A4 | Limits: 2 vCPU, 2 GiB, first healthy response within 60 s, up to 50 requests in flight, 5 s per request (10 s for `/_test/reset`, `/_test/export`, `/_test/import`). | Run with `--cpus 2 --memory 2g`; 50-way concurrent bursts of payments, pays, logins and signups, timing each request; reset with a large fixture under 10 s. Password hashing cost must be chosen so 50 concurrent logins/signups each finish under 5 s on 2 vCPU and a reset of a few hundred users finishes under 10 s |
| A5 | `GET /health` -> 200 `{"status":"ok"}` once the service and store can serve. No auth. | API test |
| A6 | `POST /_test/reset` with a fixture -> 204, no body; replaces **all** state (users, tokens, payments, requests, splits, settlements, idempotency records, operators); later requests see only the fixture; repeatable; enabled in the delivered image; no auth. | API test: reset, write, reset, confirm old tokens are 401 and old data gone |
| A7 | Requests and responses are `application/json; charset=utf-8`. Every 4xx/5xx carries `{"error":{"code","message"}}`, including unknown routes (404 `not_found`) and unsupported methods. | API test on headers and on error bodies for every error path |
| A8 | Response timestamps are RFC 3339 with an explicit numeric offset (e.g. `+00:00`). **[reading]** emit a numeric offset, not `Z`, because the spec's examples all show one. | Regex on every `created_at` / `committed_at` |
| A9 | Unknown body fields are ignored, never an error; unknown query parameters are ignored (e.g. `direction`/`status` on `/activity`). | API test |
| A10 | IDs are opaque strings of at most 64 characters. Seeded ids from the fixture are kept as given. | API test on every id field |
| A11 | No request yields a 5xx, including under concurrent load and with hostile input (10 kB key, 1000 participants, wrong types, non-object bodies). | Fuzz-style API tests; scan status codes |

## B. Invariants (§1)

| Row | Requirement | Check |
|---|---|---|
| B1 | Sum of wallet balances always equals the total seeded by the last reset, under concurrency and retries. | After every concurrent burst, sum `GET /me` over all users |
| B2 | No balance negative, even transiently. | Concurrent overdraft burst: N payers racing for a balance that covers only k payments; exactly k succeed, rest 409 `insufficient_funds`; poll balances during the burst |
| B3 | A payment request moves money at most once. | Concurrent pays of one request with different keys: exactly one 201, others 409 `request_not_pending`; same key: one 201, others 200 |
| B4 | Amounts are exact integers of minor units; no float rounding anywhere; no balance outside ±2^53. | Amounts at 1 and 1000000000; odd splits; balances near 2^53 in a fixture |

## C. Model (§4)

| Row | Requirement | Check |
|---|---|---|
| C1 | One currency from the fixture; `minor_units` 0, 2 or 3 (EUR 2, JPY 0, BHD 3). `currency` returned on `/me`, payments, requests, splits. | Reset with each currency; read back |
| C2 | Amount accepts any JSON number with an integral value: `1000`, `1000.0`, `1e3` are the same amount. Booleans, strings, `null`, non-integral (`1.5`) are 422 `validation_failed`. Range 1..1000000000: `0`, `-1`, `1000000001` are 422; `1` and `1000000000` (and `1e9`) are valid. Applies to `/payments`, `/requests`, `/splits`, each settlement transfer. Amounts are returned as JSON integers. | API test per endpoint with each value |
| C3 | Handles are unique, match `^[a-z0-9_]{1,20}$`, never change. Seeded users keep the fixture handle. A handle that matches no user (including `ADA`, `@ada`, `""`) is 404 `not_found`. | API test |
| C4 | Signup handle = email local part, lowercased, every char outside `[a-z0-9_]` replaced by `_`, truncated to 20. No `handle` field in signup. | Signup `Ab.C-d+e@x.io` -> `ab_c_d_e`; 30-char local part -> 20 chars |
| C5 | New users start at balance 0 and can immediately receive money and be asked for money. | Signup, then pay to / request from the new handle |
| C6 | A request is `pending`, then exactly one of `paid`, `declined`, `cancelled`. Only the payer pays or declines; only the requester cancels. | State-transition matrix test, every (state, action, caller) |
| C7 | A request may exceed the payer's balance: created normally; pay while short is 409 `insufficient_funds` and changes nothing (request stays `pending`, no payment, key not claimed); after money arrives the same request is payable. | API test |
| C8 | Visibility belongs to the payment, chosen by the payer at pay time; a request has no visibility field. | Inspect request objects; pay with `private` |
| C9 | Feed contract: a payment is in the caller's `/activity` iff it is `public` or the caller is sender or receiver. Requests and splits never appear. Same `visibility` value seen by everyone; a `private` payment is visible to its receiver. Operators get no extra visibility. | Three-user test with public and private payments, seeded and created, including settlement members |
| C10 | Fixture: seeded users can log in immediately with the given password; `balance` is final (seeded payments are **not** replayed); seeded payments and requests appear through the API with their ids, notes, visibility and status; `payments`, `requests`, `settlement_operator_ids` may be absent (default empty). | Reset then read `/me`, `/activity`, `/requests` |
| C11 | A negative `balance` in a fixture -> 422 `validation_failed` from reset and nothing changes (previous state, tokens included, intact). **[reading]** any other structurally invalid fixture (missing `users`, `minor_units` not 0/2/3, duplicate id/handle/email, non-integer balance, reference to an unknown user id) is also 422 with nothing changed; an unparseable body is 400 `malformed_request`. | API test |
| C12 | **[reading]** Seeded payments and requests carry no timestamp in the fixture; the service assigns `created_at` at reset and orders them in fixture order (later entry = newer). Optional fixture fields that appear (`created_at`, `payment_id`, `request_id`, `settlement_id`) are honoured if valid. | Read back ordering |

## D. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| D1 | 400 `malformed_request`: body does not parse, body is not a JSON object, or a field has the wrong JSON type (e.g. `to_handle: 5`, `participant_handles: "ada"`, a non-string element in it, `email: 1`). | API test per endpoint |
| D2 | Exceptions to D1, always 422 `validation_failed`: invalid `amount` of any type (string, boolean, null, fraction); `note` that is not a string (including `null`); `visibility` other than exactly `public`/`private` (including `null`, `""`, `Public`, non-strings). Omission selects defaults (`note` `""`, `visibility` `public`). | API test |
| D3 | 422 `validation_failed`: a required field or query parameter missing; correct type but invalid format or out of range. | API test |
| D4 | 400 `missing_idempotency_key` when the header is absent or empty on the five idempotent paths. Key longer than 255 characters -> 422 `validation_failed`; 255 accepted, 256 rejected. | API test |
| D5 | 401 `unauthenticated`: missing, malformed (not `Bearer <token>`) or unknown token, on every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login`. | API test over all routes |
| D6 | 403 `forbidden`, 404 `not_found` (no such resource or not visible), 409 `idempotency_key_reuse` as defined per endpoint. | Per-endpoint rows |
| D7 | `limit`: integer 1..200, default 50; `offset`: integer >= 0, default 0. Written as plain decimal digits only: `1e9`, `4.0`, `+4`, `-1`, `abc`, empty string are 422. `limit=0`, `201` are 422; `1`, `200` valid. | API test on `/requests` and `/activity` |
| D8 | **[reading]** Order of checks on an idempotent write: (1) 401; (2) for `/settlements`, 403 non-operator; (3) missing/empty key 400, over-long key 422; (4) body parse / not an object 400; (5) claimed-key resolution (replay 200 or 409 reuse); (6) field type/validation errors; (7) resource checks (self, 404, 403, state); (8) insufficient funds. Steps 1, 4, 5, 6 order is fixed by §7; the rest is the natural reading. | API tests on combined-error requests |
| D9 | **[reading]** On `/payments` and `/requests`: field validation (422) first, then self (`self_payment` / `self_request`), then unknown handle 404, then `insufficient_funds`. | API test |

## E. Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup {email,password,display_name}` -> 201 `{user_id, display_name, token}`. | API test |
| E2 | `POST /auth/login {email,password}` -> 200 `{user_id, display_name, token}`. | API test |
| E3 | Email already registered -> 409 `email_taken`. | API test (seeded and signed-up emails) |
| E4 | Password shorter than 8 characters -> 422 (7 rejected, 8 accepted). | API test |
| E5 | `email` not of the form `local@domain` -> 422 (no `@`, empty local, empty domain). | API test |
| E6 | Wrong password or unknown email on login -> 401 `unauthenticated`. | API test |
| E7 | Derived handle already taken -> 409 `handle_taken`, no account created (login with that email then gives 401). **[reading]** order: field validation, then `email_taken`, then `handle_taken`. Emails are compared exactly as given (the spec states no normalisation). Missing `display_name` is 422. | API test |
| E8 | Tokens never expire; an account may hold several valid tokens at once (each login/signup issues a new one; old ones stay valid). | Login twice, use both |
| E9 | Passwords stored with bcrypt, scrypt, Argon2 or equivalent; never plaintext, including in exports. | Code read; inspect export for the plaintext password |
| E10 | Concurrent signups with the same email/handle: exactly one 201, no 5xx. | Concurrent API test |

## F. Idempotency (§7)

Applies independently to `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`.

| Row | Requirement | Check |
|---|---|---|
| F1 | First use -> normal response, 201. | API test on each of the five paths |
| F2 | Replay (same user, method, path, key, same JSON value) -> 200, body equal to the original as a JSON value; no further state change. "Same body" ignores key order and whitespace. | API test on each path; compare bodies and balances |
| F3 | Same key, different body -> 409 `idempotency_key_reuse`. `{}` vs `{"visibility":"public"}` differ. **[reading]** comparison is on the parsed JSON value as sent, including unknown fields, since the spec defines "same body" as the parsed value. | API test |
| F4 | Key scoped to the authenticated user; two users may use the same key string. | API test |
| F5 | Same key and body on a different path is a new request and succeeds (including `/requests/A/pay` vs `/requests/B/pay`). | API test |
| F6 | A key whose original request failed with 4xx is treated as first use afterwards. | Fail with 409/422/404, then succeed with the same key |
| F7 | Concurrent identical requests with an unused key: exactly one 201, the rest 200 with the same body; effect happens once. | 50-way burst on each path |
| F8 | A successful replay returns the original response even after the resource changed (request paid/cancelled/declined later, balances changed). | API test: create request, cancel it, replay create -> 200 original `pending` body |
| F9 | Claimed key resolved before field validation and current-resource checks: successful request, then same key with an invalid body -> 409 `idempotency_key_reuse`; replay of a successful pay on a now-`paid` request -> 200, never `request_not_pending`. | API test |

## G. API (§8, §9)

| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /me` -> `{user_id, display_name, handle, balance, currency, minor_units}`. | API test |
| G2 | `POST /payments {to_handle, amount, note?, visibility?}` -> 201 payment `{payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, settlement_id: null, created_at}`. | API test on exact key set |
| G3 | Payment rejections: balance below amount 409 `insufficient_funds` (balance == amount succeeds, leaving 0); amount rules (C2); own handle 422 `self_payment`; note longer than 200 characters 422 (200 accepted; counted in Unicode characters: 200 emoji accepted, 201 rejected); bad visibility 422; unknown handle 404. | API test |
| G4 | Debit and credit are one atomic step; a failed payment leaves no trace (no payment in any feed, balances unchanged). | API test + concurrency (B1, B2) |
| G5 | `note` stored and returned verbatim: no trimming, escaping or normalisation; Unicode/emoji round-trip exactly (leading/trailing spaces, combining characters, `<script>`). | API test |
| G6 | `POST /requests {payer_handle, amount, note?}` -> 201 request `{request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at}`; caller is requester; payer's balance not checked. | API test |
| G7 | Request rejections: amount rules; own handle 422 `self_request`; note > 200 chars 422; unknown handle 404. | API test |
| G8 | `POST /requests/{id}/pay {visibility?}` -> 201 with the payment (as G2) with `request_id` set; request becomes `paid` with `payment_id`; money moves payer -> requester; the payment note is the request's note. **[reading]** an entirely empty request body on this path is treated as `{}`. | API test |
| G9 | Pay rejections: not pending 409 `request_not_pending`; payer short 409 `insufficient_funds`; caller not the payer 403 `forbidden` (requester and third parties alike); unknown request 404. **[reading]** order 404, 403, not-pending, insufficient. | API test |
| G10 | `POST /requests/{id}/decline`: payer only, no key, 200 with the request `status: "declined"`; already declined -> 200 current state; `paid` or `cancelled` -> 409 `request_not_pending`; not the payer -> 403; unknown -> 404. A body is not required. | API test |
| G11 | `POST /requests/{id}/cancel`: requester only, no key, 200 `status: "cancelled"`; already cancelled -> 200; `paid` or `declined` -> 409 `request_not_pending`; not the requester -> 403; unknown -> 404. | API test |
| G12 | `GET /requests` -> `{requests, has_more}`; only requests where the caller is requester or payer; newest first by `created_at` (stable tie-break by creation order); `direction` = `incoming` (caller is payer) / `outgoing` (caller is requester) / absent = both; `status` one of four or absent; unknown `direction` or `status` value 422; `limit`/`offset` per D7; `has_more` true iff items exist past the last returned. | API test incl. page boundaries (exactly `limit` items -> false) |
| G13 | `POST /splits {amount, participant_handles, note?}` -> 201 `{split_id, amount, currency, note, shares:[{handle, amount}], requests:[request...], created_at}`. `shares` covers every listed participant in the given order and sums to `amount`; `requests` covers every participant except the caller, same order, each `pending`, caller as requester, amount = that share, note = split note. Share of 0 still creates a request (an exception to the amount >= 1 rule for requests created by a split). Caller-only split is valid: one share, `requests: []`. No balance is checked. **[reading]** when the caller is omitted from `participant_handles`, `n` is the number of listed handles, shares cover exactly the listed handles and all of them get a request; the caller is not added implicitly, because shares are defined "in the order the handles are given". | API test |
| G14 | Split rejections: amount rules; `participant_handles` empty or with a duplicate 422; note > 200 422; any unknown handle 404; missing field 422; 1000 unknown handles handled without 5xx. Creation is atomic: all requests or none. | API test |
| G15 | Equal split (§9): base = amount div n, the first (amount mod n) participants get one more. Table: 1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3 -> 4,3,3; 999/3 -> 333,333,333; 5/5 -> 1,1,1,1,1. Reordering handles moves the extra unit. Each split independent of earlier ones. After paying all split requests balances still sum to the seeded total. | API test over the table and a randomised sweep |
| G16 | `GET /activity` -> `{payments, has_more}`; feed contract C9; newest first by `created_at`; `limit`/`offset` as G12. | API test |

## H. Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| H1 | `GET /_test/export` -> 200 `{track: "pocketful", format_version: 1, state: {...}}`; no auth; atomic read-only snapshot unaffected by later writes. | API test: export, write, compare with a second export; export during a write burst sums to the seeded total |
| H2 | `POST /_test/import` with an unchanged export -> 204; atomically **replaces** all state (not a merge; previous destination data, credentials and tokens gone); repeating it duplicates nothing. Works in a different, fresh container with no dependence on the source process, files, volume, port or address. | Export from container A, import into container B, compare `/me`, `/activity`, `/requests` and a second export |
| H3 | Import errors: invalid JSON per §5 (400 `malformed_request`); missing `track`/`format_version`/`state`, wrong track, wrong version or invalid state -> 422 `validation_failed`, destination unchanged. | API test with each broken variant, then confirm state intact |
| H4 | Preserved across export/import: accounts and hashed-password login, existing bearer tokens, currency and minor units, balances, payments, requests, splits, operator permissions, settlement membership, every completed idempotent request body with its original response (replay after import -> 200 same body; changed body -> 409). Ids and timestamps are not regenerated; payments are not replayed against balances. Failed keys stay reusable. | API test after import in a fresh container |
| H5 | Reset clears everything, including imported state. Export/import complete within 10 s. | API test |

## I. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| I1 | Fixture `settlement_operator_ids` (array of user ids, default `[]`) names operators. Operator status gives no access to other users' requests or private activity. | API test |
| I2 | `POST /settlements`: no token 401; authenticated non-operator 403 `forbidden`; key required (F rows, D4). | API test |
| I3 | Body `{transfers: [{from_handle, to_handle, amount, note?, visibility?}]}`, 1..32 entries (32 accepted; 0 and 33 -> 422). Malformed batch shape (missing `transfers`, not an array, an entry that is not an object) -> 422 `validation_failed`. Each entry uses the ordinary payment rules for amount, note, visibility. Unknown handle 404; `from_handle == to_handle` 422 `self_payment`; unknown fields ignored. The operator may move money between any wallets, not only their own. | API test |
| I4 | Entry errors take precedence in input order, before insufficient funds: the first entry (lowest index) that has any error decides the response, even if the batch is also unaffordable. **[reading]** within one entry the order is D9 (validation, self, 404); a wrong-typed handle inside an entry follows D1 (400). | API test with two bad entries in both orders |
| I5 | Affordability is on the net: the batch is affordable when every wallet's balance after all its incoming and outgoing transfers is nonnegative (a wallet may pass on money it only receives in the same batch). Otherwise 409 `insufficient_funds`. All movements commit together or none; no balance is ever observable negative or mid-batch. | Chain test (ada->bob 100, bob->cy 100 with bob at 0) succeeds; unaffordable net fails and leaves balances, feed and key untouched |
| I6 | Failed validation claims no key and creates no payment. | Retry the same key with a valid body -> 201 |
| I7 | 201 `{settlement_id, committed_at, payments}`; `payments` in input order; each is an ordinary payment with `settlement_id` set, `request_id: null`, and the same `created_at` equal to `committed_at`. Payments outside settlements expose `settlement_id: null`. | API test |
| I8 | Members follow the ordinary feed contract (private member hidden from third parties, including the operator when not a party); the settlement response itself contains every member. | API test |
| I9 | Replay -> 200 with the original complete response; concurrent identical settlements commit once; concurrent settlements and payments keep B1 and B2. | Concurrent API test |
| I10 | Reset/export/import preserve operator permissions, original payments, requests, settlement membership and retry responses. | With H4 |

## J. Stage boundary

| Row | Requirement | Check |
|---|---|---|
| J1 | `stage-1/` implements stage 1 only; nothing from a later stage. | Harness `--stage 1` reports `claimed stage: 1`; its stage-2 overshoot line fails |
| J2 | Supplied checks pass. | From the kickoff checkout: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>`; the final run adds `--mode isolated` |
| J3 | Maintainable code: small modules with one job each; RUN.md says where each part lives; the Implementer's own tests are in the folder and runnable. | Code read (note, not blocking) |
