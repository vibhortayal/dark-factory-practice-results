@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier
STAGE 1 HANDOFF, part 4 of 5. Rows: all · Revision: no stage code yet (map commit at HEAD) · Files: stage-1/ · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer builds, Verifier prepares checks.

== Acceptance map, verbatim, continued (sections D to G) ==

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

== end of part 4 of 5; the acceptance map continues in part 5 ==
