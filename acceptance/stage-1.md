# Acceptance map: Pocketful stage 1

Source: `pocketful/spec/stage-1.md` in the kickoff checkout. Every row must hold for the
revision that is accepted. The supplied harness checks sample only part of this map.

Check kinds: **T** black-box HTTP test against the built container (status, `error.code`,
body, balances via `GET /me`) · **C** concurrency burst, up to 50 requests in flight, under
`--cpus 2 --memory 2g` · **D** docker build/run inspection · **R** source review.
Rows marked *(choice)* are Architect readings where the spec is silent; see "Choices".

## A. Delivery and runtime (§1 to §3)

- A01 [§2] `stage-1/` holds a complete service, a `Dockerfile` and a `RUN.md` with a command that builds and starts it with no manual setup. No nested `.git`. D: follow RUN.md from a clean clone.
- A02 [§2] Image runs alone with `-e PORT=<port>` and a port mapping; Compose is not needed. D.
- A03 [§2] No outbound network at run time; all dependencies, assets, initialisation in the image. D: run with `--network none` or internal network; harness `--mode isolated`.
- A04 [§2] Works within 2 vCPU, 2 GiB. First healthy response within 60 s of start. D: `docker run --cpus 2 --memory 2g`, time to `/health`.
- A05 [§2] 50 requests in flight, each answered within 5 s (reset, export, import within 10 s). C: mixed burst, record max latency. Includes 50 concurrent logins and a reset of a 50-user fixture.
- A06 [§3.1] Listens on `0.0.0.0`, port from `PORT`, default `8080`. D: run with and without `PORT`.
- A07 [§3.2] `GET /health` gives 200 `{"status":"ok"}` once ready; no auth. T.
- A08 [§3.3] `POST /_test/reset` with a fixture gives 204 with no body, replaces all state (users, tokens, payments, requests, splits, settlements, idempotency records, operators); afterwards only the fixture is visible; old tokens give 401; repeatable; no auth needed; a stale `Authorization` header on it is ignored. T.
- A09 [§3.4] Responses are `application/json; charset=utf-8`. T: header on success and error responses.
- A10 [§3.4] Response timestamps are RFC 3339 with explicit numeric offset (e.g. `+00:00`). T: regex and parse.
- A11 [§3.4] Unknown body fields ignored; unknown query parameters ignored (e.g. `direction` on `/activity`). T.
- A12 [§3.4] IDs are opaque strings of at most 64 characters, including fixture-supplied IDs kept as given. T.
- A13 [§2,§1] Only the HTTP API; no UI or later-stage features in `stage-1/`. R.

## B. Model and invariants (§1, §4)

- B01 [§1.1] Sum of all wallet balances always equals the total seeded by the last reset (or import). T+C: sum `/me` over all users after every scenario and burst.
- B02 [§1.2] No balance ever negative, including transiently. C: 50 clients drain one wallet; exactly the affordable number succeed, rest 409 `insufficient_funds`, final balance >= 0.
- B03 [§1.3] A request moves money at most once. C: 50 concurrent pays of one request with distinct keys give exactly one 201, others 409 `request_not_pending`; concurrent pay against decline/cancel has one winner.
- B04 [§4] One currency and `minor_units` (0, 2 or 3) from the fixture, shown in `/me` and every payment/request/split. T with EUR, JPY, BHD.
- B05 [§4] Amounts are integral JSON numbers: `1000`, `1000.0`, `1e3` are the same valid amount; booleans, strings, `null`, fractions are invalid. Responses emit amounts as JSON integers (`1000`, never `1000.0`). T.
- B06 [§4] `amount` max 1000000000 on any request; arithmetic exact up to ±2^53 (no floating-point balances). T: `1e9` and `1000000000` accepted as valid (409 if unfunded); `1000000001` rejected. R: integer arithmetic.
- B07 [§4] Handles: unique, `^[a-z0-9_]{1,20}$`, immutable. Seeded users keep the fixture handle. T.
- B08 [§4] Signup handle derived from email: local part, lowercased, every character outside `[a-z0-9_]` replaced by `_`, truncated to 20. T: `Dee.Ann+tag@example.com` gives `dee_ann_tag`; long local part truncated to 20.
- B09 [§4] New users start at balance 0 and can immediately receive money and be asked for money. T.
- B10 [§4] Request lifecycle: `pending`, then exactly one of `paid`, `declined`, `cancelled`; terminal states never change. T.
- B11 [§4] A request may exceed the payer's balance: created normally, stays `pending`; pay while short is 409 `insufficient_funds` and changes nothing; payable later once funded. T.
- B12 [§4] Visibility belongs to the payment; requests carry none and never appear in any feed. T.
- B13 [§4] Feed rule: a payment is visible to a caller iff it is `public` or the caller is its sender or receiver. No other rule. T: third party, sender, receiver, public and private; an operator gets no extra visibility.
- B14 [§4] Fixture: seeded users log in with the given password at once; ids, handles, display names kept; `balance` taken as given (seeded payments are not replayed against balances). T.
- B15 [§4] Seeded `payments` appear in the feed under the feed rule with their fixture id, `request_id` null, `settlement_id` null. Seeded `requests` are listed for their two parties with fixture id and status; a seeded `pending` request can be paid; a seeded non-pending one gives 409 `request_not_pending`. T.
- B16 [§4] A fixture user `balance` below zero gives 422 `validation_failed` from reset and changes nothing (previous state and tokens intact). T.
- B17 [§4] *(choice)* Other invalid fixtures (missing required field, wrong type, duplicate user id/handle/email, payment or request naming an unknown user, `minor_units` not 0/2/3, bad status or visibility, non-integer balance) give 422 `validation_failed` and change nothing; an unparseable body gives 400 `malformed_request`. `payments`, `requests`, `settlement_operator_ids` are optional and default to `[]`. Never 5xx. T.
- B18 [§4] No deposit, top-up, withdrawal or administrative balance endpoint exists. R+T: such paths give 404.

## C. Errors (§5)

- C01 Every 4xx/5xx body is `{"error":{"code":...,"message":...}}`, including 404 for unknown routes, 405, oversized or unparseable requests. T.
- C02 400 `malformed_request`: unparseable body (bad JSON, bad UTF-8, empty where a body is required, JSON that is not an object), or a field of the wrong JSON type (e.g. `to_handle: 5`, `participant_handles: "ada"`, `email: 5`). T.
- C03 422 `validation_failed`: required field or query parameter missing; correct type but invalid format or out of range; exceeding a stated maximum or length. T: missing `to_handle`, missing `amount`.
- C04 Endpoint field rules win over C02: invalid `amount` (string, boolean, null, fraction, 0, negative, above max), non-string `note` (including `null`), and any `visibility` other than exactly `public`/`private` (`"Public"`, `""`, `null`, number) are 422 `validation_failed`. Omission selects defaults. T on payments, requests, splits, pay, settlements.
- C05 401 `unauthenticated` for missing, malformed or unknown bearer token on every authenticated endpoint; checked before anything else on that endpoint. T on each endpoint.
- C06 403 `forbidden`, 404 `not_found` as listed per endpoint. T.
- C07 Integer query parameters are plain decimal digits only: `1e9`, `4.0`, `+4`, `-1`, `abc`, empty are 422. T on `limit` and `offset` of `/requests` and `/activity`.
- C08 `limit` integer 1 to 200 (default 50), `offset` integer >= 0 (default 0), otherwise 422. T: 0, 201, 200, 1; very large digit strings never 5xx.
- C09 `Idempotency-Key` 1 to 255 characters; longer is 422 `validation_failed` (a 10 000-character key must reach the handler and give 422, not a server-level 431/400); absent or empty is 400 `missing_idempotency_key`. T on all five paths.
- C10 No request produces a 5xx, including under 50 concurrent requests and awkward input (huge numbers such as `1e400`, deep or large bodies, 1000-element lists, lone surrogates, NUL characters). T+C.

## D. Authentication (§6)

- D01 `POST /auth/signup` `{email,password,display_name}` gives 201 `{user_id,display_name,token}`. T.
- D02 `POST /auth/login` `{email,password}` gives 200 `{user_id,display_name,token}`. T.
- D03 Email already registered: 409 `email_taken`. T.
- D04 Password shorter than 8 characters: 422. Exactly 8 accepted. T.
- D05 `email` not of the form `local@domain`: 422. T: no `@`, empty local, empty domain.
- D06 Wrong password or unknown email on login: 401 `unauthenticated`. T.
- D07 Derived handle already taken: 409 `handle_taken` and no account is created (the email can not log in; a later signup with a free handle works). T.
- D08 Missing signup/login field: 422; wrong JSON type: 400. T.
- D09 All endpoints except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, `/auth/signup`, `/auth/login` require `Authorization: Bearer <token>`. T.
- D10 Tokens never expire; one account may hold several valid tokens at once (each login/signup issues a new one, old ones stay valid). T.
- D11 Passwords stored only as a salted password hash (bcrypt, scrypt, Argon2 or equivalent); never plaintext, also not in the export. R + inspect export.

## E. Idempotency (§7): applies to POST /payments, /requests, /requests/{id}/pay, /splits, /settlements

- E01 Header absent or empty: 400 `missing_idempotency_key`. T x5.
- E02 First use: normal response, 201. T x5.
- E03 Replay (same user, method, path, key, same body as a JSON value regardless of key order or whitespace): 200 with a body equal to the original response as a JSON value; no further state change. T x5.
- E04 Same key, different body: 409 `idempotency_key_reuse`. T x5; `{}` against `{"visibility":"public"}` on pay is reuse.
- E05 Key reused after the original failed with 4xx: treated as first use (a failure claims no key). T: 409 `insufficient_funds`, fund, retry same key gives 201 and one payment.
- E06 Keys are scoped per authenticated user: two users with the same key do not interact. T.
- E07 Same key and body on a different path is a different request and succeeds normally (scope includes method and path; `/requests/a/pay` and `/requests/b/pay` are different paths). T.
- E08 Concurrent identical requests with an unused key: exactly one 201, the rest 200 with the same body, effect once. C: 50 in flight x5 paths.
- E09 A successful replay returns the original response even after the resource changed (request later paid/cancelled; payment replay after balances moved). T.
- E10 Once the caller is authenticated and the body parsed as a JSON object, a claimed key is resolved before field validation and resource checks: a claimed key with a now-invalid body is 409 `idempotency_key_reuse`, not 422/404. T.
- E11 Replaying a successful pay returns 200 with the original payment even though the request is `paid`; never 409 `request_not_pending`; moves nothing. T.

## F. Endpoints (§8)

- F01 `GET /me` gives `{user_id,display_name,handle,balance,currency,minor_units}`. T.
- F02 `POST /payments` 201 with `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, settlement_id: null, created_at`. `note` defaults `""`, `visibility` defaults `"public"`. Debit and credit are one atomic step. T.
- F03 Payment rejections: balance below amount 409 `insufficient_funds` (paying exactly the balance succeeds); amount rules 422; own handle 422 `self_payment`; note over 200 characters 422; bad visibility 422; unknown handle 404 `not_found`. A failed payment leaves no trace (balances, feed). T.
- F04 `note` stored and returned verbatim, no trimming/escaping/normalisation; Unicode and emoji round-trip exactly; length counted in Unicode code points (200 emoji accepted, 201 rejected). T.
- F05 `POST /requests` 201 with `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at`; caller is the requester; payer balance not checked. T.
- F06 Request rejections: amount rules 422; own handle 422 `self_request`; note over 200 422; unknown handle 404. T.
- F07 `POST /requests/{id}/pay`: body carries optional `visibility` (default public); 201 with a payment exactly as `POST /payments` returns, `request_id` set; request becomes `paid` with `payment_id`; money moves payer to requester. T.
- F08 Pay rejections: unknown request 404; caller not the payer 403 `forbidden` (requester and third parties alike); not pending 409 `request_not_pending`; short balance 409 `insufficient_funds` (nothing changes, stays pending). T.
- F09 `POST /requests/{id}/decline`: payer only, no key needed; 200 with the request `declined`; repeat decline 200 with current state; `paid` or `cancelled` gives 409 `request_not_pending`; not payer 403; unknown 404. T.
- F10 `POST /requests/{id}/cancel`: requester only, no key needed; 200 `cancelled`; repeat 200; `paid` or `declined` gives 409; not requester 403; unknown 404. T.
- F11 `GET /requests`: only requests where the caller is requester or payer; newest first by `created_at`; `direction` incoming (caller is payer) / outgoing (caller is requester) / absent for both; `status` one of four or absent; unknown `direction` or `status` value 422; `{requests, has_more}`; `has_more` true iff items exist beyond the last returned. T including a third party under every filter.
- F12 `POST /splits`: 201 `{split_id, amount, currency, note, shares, requests, created_at}`; `shares` one per participant in given order (caller included only if listed), summing to `amount`; one `pending` request per participant except the caller, same order, caller as requester, amount = share; caller may be listed or omitted. T.
- F13 Split rejections: amount rules 422; `participant_handles` empty or with a duplicate 422; note over 200 422; any unknown handle 404. 1000 handles never 5xx. T.
- F14 A split with only the caller is valid: one share, `requests: []`. No split checks any balance. T.
- F15 `GET /activity`: payments visible per B13, newest first by `created_at`, `{payments, has_more}`, `limit`/`offset` as F11/C08; requests and splits never appear. T.

## G. Money and rounding (§9)

- G01 Shares are whole minor units, sum to `amount`, differ by at most 1; larger shares go to the first participants in given order. T: table rows 1000/3, 1/3, 10/3, 999/3, 5/5.
- G02 A different handle order moves the extra unit; a share of 0 is legal and still creates a request (amount 0), which can be paid. T.
- G03 Each split independent of earlier ones; after splits are paid in full the balances still sum to the seeded total. T.

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
