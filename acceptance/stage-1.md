# Stage 1 acceptance map (Pocketful: payments and settlements)

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (complete). Target folder: `stage-1/`.
Every row must hold. "Check" names how the row is verified: **H** = supplied harness suite
(`harness run --track pocketful --stage 1`), **T** = a test the seat writes from the spec and runs
against the built container, **I** = inspection of source / image / files.
The supplied suite is a partial sample; rows marked T or I are not covered by it and still bind.

## A. Delivery and runtime (§2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds an HTTP service, a `Dockerfile` and a `RUN.md` with one command that builds and starts it with no manual setup; no nested `.git` | I + run the RUN.md command verbatim |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose, no volume, no second container needed | T: `docker run -e PORT=9123 -p 9123:9123` |
| A3 | No outbound network at run time; all dependencies, assets and init inside the image | H `--mode isolated`; T: `docker run --network none` health check via `docker exec` or internal network |
| A4 | Listens on `0.0.0.0`, port from `PORT`, default `8080` when unset | T: run without `-e PORT` and probe 8080 |
| A5 | `GET /health` -> 200 `{"status":"ok"}` within 60 s of container start | H + T (timed) |
| A6 | Fits 2 vCPU / 2 GiB; 50 requests in flight; every request under 5 s (reset/export/import under 10 s) | T: run with `--cpus 2 --memory 2g`, 50-way bursts incl. 50 concurrent logins, timed; reset of a large fixture (e.g. 200 users) under 10 s |
| A7 | No request produces a 5xx, including under concurrent load and with hostile input (huge bodies/keys, wrong types, deep/odd JSON, non-object JSON bodies) | H + T fuzz |
| A8 | `POST /_test/reset` with a fixture -> 204, replaces **all** state (users, tokens, payments, requests, splits, settlements, idempotency records, operators, currency); later requests see only that fixture; repeated resets work; no auth needed | H + T: old token is 401 after reset; old key is a first use after reset |
| A9 | Responses are `application/json; charset=utf-8`; 204 responses have no body | T: header check on success and error responses |
| A10 | Response timestamps are RFC 3339 with explicit offset (e.g. `+00:00`) | T: regex + parse on every timestamp field |
| A11 | Unknown body fields are ignored; unknown query parameters are ignored (e.g. `direction` on `/activity`) | H + T |
| A12 | IDs are opaque strings of at most 64 characters; fixture-supplied ids are kept as given | T |

## B. Model and fixture (§4)

| Row | Requirement | Check |
|---|---|---|
| B1 | One currency from the fixture; `minor_units` 0, 2 or 3 (EUR/JPY/BHD) reported by `/me`, `currency` on payments/requests/splits | H + T for all three |
| B2 | Amounts are exact integers end to end; JSON `1000`, `1000.0`, `1e3` are the same valid amount; booleans and strings are not numbers; responses emit integer JSON numbers (never `1000.0`) | H + T |
| B3 | Handle unique, matches `^[a-z0-9_]{1,20}$`, immutable; seeded users keep the fixture handle | T |
| B4 | Signup handle derived from email: local part, lowercased, every char outside `[a-z0-9_]` -> `_`, truncated to 20 | H + T (`A.b-C+d@x` -> `a_b_c_d`; 30-char local -> 20) |
| B5 | New users start at balance 0 and can immediately receive money and be asked for money | H + T |
| B6 | Seeded users can log in with the fixture password immediately after reset | H |
| B7 | Fixture `balance` is the final balance: seeded payments are **not** replayed against balances | T: fixture with payments, `/me` equals fixture balance |
| B8 | Seeded payments appear in the feed under the feed contract with all payment fields (`request_id` null, `settlement_id` null, handles resolved, `created_at` assigned) | H + T |
| B9 | Seeded requests appear in `GET /requests` for their two parties only, keep id/amount/note/status, and can be paid/declined/cancelled per their status | H + T (each of the four statuses) |
| B10 | Negative `balance` in a fixture -> `422 validation_failed` from reset and **nothing changes** (previous state, tokens and all, intact) | H + T |
| B11 | `settlement_operator_ids` optional in fixture, default `[]` | H + T |
| B12 | Invariant: sum of wallet balances always equals the seeded total of the last reset, including under concurrency and retries | H + T: sum `/me` over all users after bursts |
| B13 | Invariant: no balance is ever negative, including transiently (check and debit are one atomic step) | T: concurrent drain, parts and ring bursts; no 201 beyond funds |
| B14 | Invariant: a payment request moves money at most once (concurrent pays with different keys: exactly one 201) | T |
| B15 | Balances up to ±2^53 handled exactly (no float arithmetic on money) | T: large seeded balance near 2^53 round-trips exactly through `/me`, payment and export/import; I: no floats in money paths |

## C. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| C1 | Every 4xx/5xx body is `{"error":{"code":...,"message":...}}` — including unknown routes (404 `not_found`), wrong method, and framework-level errors | T |
| C2 | Unparseable body -> 400 `malformed_request`; body that parses but is not a JSON object -> 400 `malformed_request` | H + T |
| C3 | Field of the wrong JSON type -> 400 `malformed_request` (e.g. `to_handle: 5`, `participant_handles: "ada"`, `email: 7`), **except** the endpoint rules in C4 | T |
| C4 | Invalid `amount` (string, boolean, null, non-integral, out of range), non-string `note` (incl. `null`), any `visibility` other than `public`/`private` (incl. `null`, `""`, `"Public"`, numbers) -> 422 `validation_failed` | H + T |
| C5 | Missing required field or query parameter -> 422 `validation_failed` | H + T |
| C6 | Correct type but invalid format / out of range -> 422 `validation_failed` unless the endpoint names another code | T |
| C7 | Missing/empty `Idempotency-Key` on a path that needs one -> 400 `missing_idempotency_key`; longer than 255 characters -> 422 `validation_failed` (255 exactly is accepted) | H + T |
| C8 | Missing, malformed or unknown bearer token -> 401 `unauthenticated` on every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login` | T: each endpoint, no header / `Bearer` / `Basic x` / unknown token |
| C9 | `limit` integer 1..200 (default 50), `offset` integer >= 0 (default 0); outside -> 422, on both `/requests` and `/activity` | H + T |
| C10 | Integer query parameters must be plain decimal digits: `1e9`, `4.0`, `+4`, `abc`, empty string -> 422 `validation_failed` | H + T |
| C11 | 403 `forbidden` when authenticated but not permitted; 404 `not_found` for no such resource | H + T |

## D. Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| D1 | `POST /auth/signup` `{email,password,display_name}` -> 201 `{user_id,display_name,token}`; token works immediately | H + T |
| D2 | `POST /auth/login` -> 200 `{user_id,display_name,token}` | H + T |
| D3 | Email already registered -> 409 `email_taken` (checked before the handle rule) | T |
| D4 | Password shorter than 8 characters -> 422 `validation_failed` (8 exactly accepted) | T |
| D5 | `email` not of the form `local@domain` -> 422 `validation_failed` | T (`nope`, `@x`, `a@`, `a@b@c`) |
| D6 | Wrong password or unknown email -> 401 `unauthenticated` | H + T |
| D7 | Derived handle already taken -> 409 `handle_taken`, **no account created** (login with that email is 401) | H + T |
| D8 | Tokens do not expire; several valid tokens / concurrent sessions per account | T: two logins, both tokens work |
| D9 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent; never plaintext — in memory, in store and in export | I + T: export contains no fixture password string |
| D10 | Missing `email`/`password`/`display_name` -> 422; wrong JSON type -> 400 | T |

## E. Idempotency (§7) — applies independently to each of the five write paths

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements` all require the key | H (four) + T (settlements) |
| E2 | First use -> the normal 201 | H |
| E3 | Replay (same user, method, path, JSON-equal body) -> **200** with a body equal as a JSON value to the original; no further state change | H + T on all five paths |
| E4 | Body equality is on the parsed JSON value: key order and whitespace do not matter; `{}` vs `{"visibility":"public"}` differ; unknown extra fields make the body different | H + T |
| E5 | Same key, different body -> 409 `idempotency_key_reuse` | H + T |
| E6 | Key scoped to the authenticated user: two users may use the same key string independently | H |
| E7 | Same key and body on a different path is not a replay and succeeds normally (incl. `/requests/a/pay` vs `/requests/b/pay`) | H + T |
| E8 | Key used by a request that failed with 4xx stays unclaimed: next use is a first use (may be a different body) | H + T |
| E9 | Concurrent identical requests with an unused key: exactly one 201, the others 200 with the same body, effect happens once | T: 50-way burst on each path |
| E10 | A successful replay returns the original response even after the resource changed (request later paid/cancelled, balances changed) | H + T |
| E11 | Once the caller is authenticated and the body parsed as a JSON object, a claimed key is resolved **before** field validation and current-resource checks: a claimed key with a now-invalid body -> 409 `idempotency_key_reuse`, not 422; pay replay on a paid request -> 200, not 409 | H + T |

## F. Endpoints (§8)

| Row | Requirement | Check |
|---|---|---|
| F1 | `GET /me` -> `{user_id,display_name,handle,balance,currency,minor_units}` | H |
| F2 | `POST /payments` -> 201 with `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, settlement_id:null, created_at` | H + T |
| F3 | Payment defaults: `note` `""`, `visibility` `"public"` when omitted | H |
| F4 | Balance below `amount` -> 409 `insufficient_funds`, nothing changes, no trace in either wallet or feed; paying exactly the balance succeeds | H + T |
| F5 | `amount` < 1, > 1000000000, or not an integer -> 422 | H |
| F6 | `to_handle` equal to caller's handle -> 422 `self_payment` | H |
| F7 | `note` longer than 200 characters (code points; 200 emoji accepted, 201 rejected) -> 422 | H |
| F8 | No user has that handle -> 404 `not_found` | H |
| F9 | Debit and credit are one atomic step; never visible in one wallet and not the other | T (concurrent readers during bursts, conservation) |
| F10 | `note` stored and returned verbatim: no trim, escape or normalisation; Unicode/emoji byte for byte (leading/trailing spaces, NFD vs NFC, `<script>`, `\u0000`-free control chars, ZWJ sequences) | H + T |
| F11 | `POST /requests` -> 201 with `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at`; caller is requester | H |
| F12 | Request rejections: amount rule 422; own handle 422 `self_request`; note > 200 -> 422; unknown handle 404 | H + T |
| F13 | Payer's balance is **not** checked at request creation | H |
| F14 | `POST /requests/{id}/pay`: payer only; body `visibility` optional default public; -> 201 with the payment (as F2) with `request_id` set; request becomes `paid` with `payment_id` | H |
| F15 | Pay rejections: unknown request 404; caller not the payer 403; not pending 409 `request_not_pending`; short balance 409 `insufficient_funds` changing nothing (request stays `pending` and is payable later once funded, same key allowed) | H + T |
| F16 | Pay visibility is the payer's choice and is the one value on the payment seen by everyone | H + T |
| F17 | `POST /requests/{id}/decline`: payer only, no key; 200 with request `declined`; already declined -> 200 current state; `paid`/`cancelled` -> 409 `request_not_pending`; not the payer -> 403; unknown -> 404 | H + T |
| F18 | `POST /requests/{id}/cancel`: requester only, no key; 200 with request `cancelled`; already cancelled -> 200; `paid`/`declined` -> 409; not the requester -> 403; unknown -> 404 | H + T |
| F19 | Decline/cancel accept an absent or empty body | H + T |
| F20 | `GET /requests`: only requests where caller is requester or payer; newest first by `created_at`; `direction` incoming/outgoing/absent; `status` one of four or absent; unknown value of either -> 422; body `{requests, has_more}` | H + T |
| F21 | `has_more` true exactly when items exist beyond the last returned (boundary: offset+limit == total -> false; offset beyond end -> `[]`, false) | H + T |
| F22 | `POST /splits` -> 201 `{split_id, amount, currency, note, shares[{handle,amount}], requests[...], created_at}`; `shares` covers every participant incl. caller in given order and sums to `amount`; `requests` covers everyone except the caller in the same order, caller as requester, each `pending`, note = split note | H + T |
| F23 | Caller may be included or omitted in `participant_handles`; when omitted the caller gets no share | T |
| F24 | Split rejections: amount rule 422; empty list or duplicate handle 422; note > 200 -> 422; any unknown handle 404; 1000 handles never 5xx | H + T |
| F25 | Split with only the caller is valid: one share, `requests: []`; a split checks nobody's balance | H |
| F26 | `GET /activity`: payments only, visible iff `public` or caller is sender or receiver; newest first; `{payments, has_more}`; `limit`/`offset` exactly as `/requests` | H + T |
| F27 | Requests and splits never appear in the feed; a private payment is visible to both its parties and hidden from third parties (incl. operators) | H + T |

## G. Money and rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| G1 | Shares are whole units, sum to `amount`, differ by at most 1; larger shares go to the first participants in given order: 1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3 -> 4,3,3; 999/3 -> 333,333,333; 5/5 -> 1×5 | H + T (table verbatim) |
| G2 | Different handle order moves the extra unit; a 0 share is legal and still creates a request (amount 0, payable, moves 0) | H + T |
| G3 | Each split independent of earlier ones; after splits are paid in full the balances still sum to the seeded total | T |

## H. Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| H1 | `GET /_test/export` (no auth) -> 200 `{track:"pocketful", format_version:1, state:{...}}` | H + T |
| H2 | `POST /_test/import` (no auth) with an unchanged export -> 204 and atomically replaces all state; replacement not merge; repeating it duplicates nothing | H + T |
| H3 | Import works on a **fresh container** from another process (no dependency on source process, files, volume, port, address) | T: export from container A, import into container B |
| H4 | Invalid JSON -> 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid state -> 422 `validation_failed`, destination unchanged | T |
| H5 | Export is an atomic read-only snapshot; later writes do not change an export already taken; export under concurrent writes is internally consistent (balances sum to total) | T |
| H6 | Import preserves: accounts and hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits' requests, operator permissions, settlement membership (`settlement_id`), ids and timestamps unchanged | H + T: compare `/me`, `/activity`, `/requests` before and after |
| H7 | Import preserves completed idempotent request bodies and original responses on all five paths: replay after import -> 200 original body; changed body -> 409; failed keys stay reusable | T |
| H8 | Balances are not regenerated or replayed on import (already-net) | T |
| H9 | Import removes all previous destination data and credentials (old tokens 401, old users gone) | T |
| H10 | Reset clears everything including imported state | T |
| H11 | Export/import/reset complete within 10 s | T (timed, large state) |

## I. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| I1 | `POST /settlements`: no token 401; authenticated non-operator 403 `forbidden`; operator + key required | H + T |
| I2 | Body `{transfers:[{from_handle,to_handle,amount,note?,visibility?}]}`, 1..32 objects; defaults note `""`, visibility public; unknown fields ignored | H + T (1, 32, 33, 0) |
| I3 | Malformed batch shape (missing/non-array `transfers`, empty, more than 32, non-object entries) -> 422 `validation_failed` | T |
| I4 | Entry errors: ordinary amount/note/visibility rules 422; unknown handle 404; self-transfer 422 `self_payment`; reported for the first bad entry in input order, and before insufficient funds | T |
| I5 | Affordability is on the **net**: every wallet's balance after all transfers is nonnegative (a wallet may pass money on that it only receives within the batch); otherwise 409 `insufficient_funds` | H + T (chain a->b->c with b at 0) |
| I6 | All movements commit together or none do; a failed settlement creates no payment, changes no balance and claims no key | T |
| I7 | 201 `{settlement_id, committed_at, payments[...]}` in input order; each member is an ordinary payment with `settlement_id` set, `request_id` null, `created_at` == `committed_at` for all members | H + T |
| I8 | Non-member payments (direct, request-paid, seeded) expose `settlement_id: null` everywhere a payment is returned | T |
| I9 | Members follow ordinary feed visibility (private member hidden from third parties; operator who is not a party does not see it in the feed); the settlement response carries every member's receipt | T |
| I10 | Operator permission grants no access to others' requests or private activity | T |
| I11 | Settlement replay -> 200 with the original complete response; fifth idempotent path obeys E1–E11 | T |
| I12 | Operator permissions, settlement membership and retry responses survive export/import | T |

## J. Stage boundary

| Row | Requirement | Check |
|---|---|---|
| J1 | `stage-1/` implements stage 1 only; nothing from `spec/stage-2.md` onward (a folder that passes the whole next suite claims nothing) | H: `--stage 1` report shows `claimed stage: 1`; I |
| J2 | Final check: `harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated` all green, zero skipped/errored | H |

## Decisions recorded by the Architect (spec silent or ambiguous; reason given)

1. **Precedence on idempotent paths**: 401 auth -> (settlements only: 403 non-operator) -> key header missing 400 / over 255 chars 422 -> body parse 400 (must be a JSON object) -> claimed-key resolution (replay 200 / reuse 409) -> field validation -> resource checks. Reason: §7 fixes key resolution after auth and body parse and before validation; keys are per user so auth is first.
2. **Pay precedence** for a fresh key: 404 unknown -> 403 not the payer -> 409 `request_not_pending` -> 409 `insufficient_funds`. A third party gets 403 (the §8 table says "caller is not the request's payer"). Same shape for decline/cancel.
3. **Handle lookup**: a `to_handle`/`payer_handle`/participant string that matches no user is 404 `not_found`, including strings that do not match the handle pattern (`""`, `ADA`, `@ada`): "no user has that handle". Non-string -> 400.
4. **Split validation order**: shape/amount/note 422 and empty/duplicate 422 before unknown-handle 404.
5. **Email identity**: emails compare as exact strings (no case folding); the spec states no normalisation. `email_taken` is checked before `handle_taken`.
6. **Note length** is counted in Unicode code points (200 emoji accepted by the supplied checks).
7. **Ordering tie-break**: items with equal `created_at` are ordered by creation sequence, newest first; seeded items take fixture order as creation order. Timestamps carry sub-second precision.
8. **Seeded `created_at`**: fixture payments/requests carry no timestamp, so the server assigns one at reset; if a fixture item does carry `created_at`, keep it.
9. **Reset validation**: a structurally invalid fixture (wrong types, duplicate ids/handles/emails, bad handle, references to unknown users, bad status/visibility, `minor_units` not 0/2/3, operator id unknown) is 422 `validation_failed` (unparseable body 400) and changes nothing.
