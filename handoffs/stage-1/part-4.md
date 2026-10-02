@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier

Rows: all · Revision: n/a · Files: n/a · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer builds, Verifier prepares checks.

STAGE 1 HANDOFF — PART 4 of 5

## Acceptance map, continued: sections E–G

## E. Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; token works immediately | HTTP |
| E2 | `POST /auth/login` → 200 `{user_id, display_name, token}` | HTTP |
| E3 | Email already registered → 409 `email_taken` | Signup twice; signup with seeded email |
| E4 | Password shorter than 8 characters → 422; exactly 8 OK | 7 and 8 chars |
| E5 | `email` not `local@domain` → 422 (no at-sign, empty local part, empty domain part, empty string) | HTTP |
| E6 | Wrong password or unknown email on login → 401 `unauthenticated` | HTTP |
| E7 | Derived handle already taken (by a seeded or signed-up user) → 409 `handle_taken`, no account created (email stays free, login fails 401) | `ada@other.com` when handle `ada` exists; `a.b@x.com` then `a_b@x.com` |
| E8 | All endpoints except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, `/auth/signup`, `/auth/login` require a bearer token | 401 without token on `/me`, `/payments`, `/requests`, pay/decline/cancel, `/splits`, `/activity`, `/settlements` |
| E9 | Tokens do not expire; multiple tokens per account stay valid concurrently | Login twice → both tokens work |
| E10 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent; never plaintext (also not in export) | Read source; export state contains no plaintext seeded password |
| E11 | Signup/login wrong types → 400; missing fields → 422 | HTTP |

## F. Idempotency (§7) — each row applies independently to `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`

| Row | Requirement | Check |
|---|---|---|
| F1 | Header absent or empty → 400 `missing_idempotency_key` | Each path |
| F2 | First use → normal response, 201 | Each path |
| F3 | Replay (same user, method, path, same JSON value) → 200 with body identical (as JSON value) to the original; no further state change | Replay, deep-compare, balances/feed unchanged |
| F4 | "Same body" is JSON-value equality: key order and whitespace irrelevant | Replay with reordered keys / extra whitespace → 200 |
| F5 | Same key, different body → 409 `idempotency_key_reuse` (an added unknown field is a different body; `{}` vs `{"visibility":"public"}` are different) | Each path |
| F6 | Key scoped to the authenticated user: two users using the same key do not interact | Two users, same key → both 201 |
| F7 | Same key + same body on a different path is a different request and succeeds normally (incl. two different `/requests/{id}/pay` paths) | Same key on `/payments` and `/requests`; on two pay paths |
| F8 | Key whose original request failed with 4xx is treated as first use (any body) | Fail (409 insufficient / 422 / 404), then succeed with same key |
| F9 | Concurrent identical requests with an unused key: exactly one 201, all others 200 with the same body; effect once | 20–50 parallel identical requests on each path |
| F10 | Replay returns the original response even after the resource changed (request later paid/cancelled/declined; balance now insufficient) | Create request, cancel it, replay create → 200 original `pending` body |
| F11 | After body parses as an object and caller is authenticated, a claimed key is resolved BEFORE field validation and current-resource checks: successful request re-sent with invalid body under the same key → 409 `idempotency_key_reuse` (not 422/404) | Each path |
| F12 | Replay of a successful pay returns 200 original payment even though the request is now `paid`; never 409 `request_not_pending`; no extra money | HTTP |

## G. API (§8)

| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}` | Seeded and signed-up users |
| G2 | `POST /payments` 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, settlement_id: null, created_at`; debit+credit atomic | HTTP + balances |
| G3 | Payment: balance below amount → 409 `insufficient_funds`, no trace in either wallet or feed; amount == balance succeeds (balance 0) | Boundary: balance, balance+1 |
| G4 | Payment: amount 1 and 1000000000 OK; 0, -1, 1000000001, 1.5 → 422 | Boundary |
| G5 | Payment to own handle → 422 `self_payment` | HTTP |
| G6 | `note` 200 chars OK, 201 → 422; default `""`; stored and returned verbatim (no trim/escape/normalise; unicode, emoji, leading/trailing spaces, `<script>`, NFD forms byte-for-byte) | Round-trip via POST response, `/activity`, replay, export/import |
| G7 | `visibility` default `"public"`; `"private"` accepted; others 422 | HTTP |
| G8 | Unknown `to_handle` → 404 `not_found` | HTTP |
| G9 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at`; caller is requester; payer balance NOT checked | HTTP incl. amount > payer balance |
| G10 | Request: amount rules as G4; own handle → 422 `self_request`; note > 200 → 422; unknown handle → 404 | HTTP |
| G11 | `POST /requests/{id}/pay` → 201 with payment exactly as `/payments` returns, `request_id` set; payer debited, requester credited; request becomes `paid` with `payment_id`; body `visibility` optional default public (payer's choice) | HTTP; `GET /requests` afterwards from both sides |
| G12 | Pay errors: not pending (paid/declined/cancelled) → 409 `request_not_pending`; short balance → 409 `insufficient_funds`; caller not payer (requester, third party, operator) → 403 `forbidden`; unknown id → 404 `not_found` | HTTP |
| G13 | `POST /requests/{id}/decline`: payer only, no idempotency key needed; 200 with request `status:"declined"`; already declined → 200 current state; `paid`/`cancelled` → 409 `request_not_pending`; not payer → 403; unknown → 404 | Transition matrix |
| G14 | `POST /requests/{id}/cancel`: requester only, no key; 200 `status:"cancelled"`; already cancelled → 200; `paid`/`declined` → 409; not requester → 403; unknown → 404 | Transition matrix |
| G15 | Concurrent pay vs decline vs cancel on one request: exactly one outcome wins, money moves at most once, final state consistent | Race burst |
| G16 | `GET /requests`: only requests where caller is requester or payer; newest first by `created_at`; `direction` `incoming` (caller is payer) / `outgoing` (caller is requester) / absent = both; `status` one of four or absent; unknown `direction`/`status` → 422; response `{requests, has_more}` | HTTP as each party, third party and operator |
| G17 | Pagination on `/requests` and `/activity`: `limit`/`offset` per D5/D6; `has_more` true iff items exist beyond the last returned (exact at boundary: N items, limit N → false; limit N-1 → true; offset beyond end → `[]`, false) | Boundary |
| G18 | `POST /splits` 201 body: `split_id, amount, currency, note, shares[{handle, amount}], requests[…], created_at`; `shares` covers every participant incl. caller in given order and sums to amount; `requests` covers every participant except caller, same order, caller is requester, each `pending` with that share and the split's note | HTTP with caller included/omitted |
| G19 | Split errors: amount rules as G4; `participant_handles` empty or with duplicate → 422; note > 200 → 422; any unknown handle → 404; a failed split creates no requests | HTTP |
| G20 | Split whose only participant is the caller is valid: one share, `"requests": []`; split never checks balances; caller omitted → n = number of listed handles and every one gets a request | HTTP |
| G21 | `GET /activity`: payments only; a payment appears iff it is `public` OR caller is sender or receiver; newest first by `created_at`; `{payments, has_more}`; requests and splits never appear; a `private` payment is visible to its receiver, hidden from third parties and from operators who are not party | HTTP as sender, receiver, third party, operator, new signup |

(end of part 4 of 5)
