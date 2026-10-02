# Acceptance map — Pocketful stage 1

Source of truth: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (§ numbers below refer to it).
Each row: requirement → how it is checked. "HTTP" = black-box check against the running
container built from `stage-1/Dockerfile`. "Harness" = the supplied partial checks
(`python -m harness run --track pocketful --stage 1`). The supplied checks are a sample;
every row must be checked whether or not the harness covers it.

## A. Delivery and deployment (§2)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` contains the service source, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service with no manual setup | Follow RUN.md verbatim from a clean clone; `docker build` from clean state (no cache) succeeds |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose, no volume, no second container | `docker run -e PORT=9123 -p 9123:9123 <image>`; `/health` 200 |
| A3 | No outbound network at run time; all runtime deps, init and seed in the one image | `docker run --network none` (exec in-container requests) or harness `--mode isolated`; full behaviour works |
| A4 | Start to first healthy response ≤ 60 s | Time from `docker run` to first 200 on `/health` |
| A5 | Works within 2 vCPU / 2 GiB | Run with `--cpus 2 --memory 2g`; all checks, incl. load rows, pass |
| A6 | Up to 50 concurrent in-flight requests; each request ≤ 5 s (reset/export/import ≤ 10 s) | 50-way concurrent mixed bursts under A5 limits; max latency recorded; no 5xx |
| A7 | State is ephemeral; no dependence on files surviving restart | Restart container → fresh empty state, healthy, reset works |
| A8 | Stage 1 only: no UI, no authorizations/holds/captures, no statements/corrections, no refunds (stages 2–4) | Probe stage-2..4 paths (`/authorizations`, `/statement`, …) → 404 `not_found`; read source tree |
| A9 | Built from requirements only; maintainable: small modules with one job each, RUN.md says where each part lives; no nested git repo | Read source and RUN.md |

## B. Runtime contract (§3)

| Row | Requirement | Check |
|---|---|---|
| B1 | Listens on `0.0.0.0`, port from `PORT`, default `8080` | Run with and without `-e PORT` |
| B2 | `GET /health` → 200 `{"status":"ok"}`, no auth | HTTP |
| B3 | `POST /_test/reset` with fixture → 204, empty body, no auth; replaces ALL state (users, tokens, payments, requests, splits, settlements, idempotency records, operators) | Reset, mutate, reset again; old tokens → 401; old keys are first-use again; old ids gone |
| B4 | Repeated resets supported; after 204 only the new fixture is visible | Reset twice with different fixtures/currencies |
| B5 | Responses are `application/json; charset=utf-8` (bodies of 2xx with content and all 4xx) | Inspect `Content-Type` on every endpoint and on errors |
| B6 | Timestamps are RFC 3339 with explicit offset (numeric offset such as `+00:00`) | Regex on every `created_at` / `committed_at` |
| B7 | Unknown body fields are ignored, never an error (all endpoints incl. reset fixture, settlement entries) | Send extra fields everywhere → normal success |
| B8 | Unknown query parameters are ignored | `GET /activity?foo=1`, `GET /requests?x=y`, `GET /me?z=1` |
| B9 | IDs are opaque strings ≤ 64 chars; generated ids never collide with seeded/imported ids (e.g. seeded `p_1`, `rq_1`, `u_1`) | Seed ids that look like generated ones, create new resources, assert uniqueness and length |

## C. Model and invariants (§1, §4)

| Row | Requirement | Check |
|---|---|---|
| C1 | Sum of all wallet balances always equals seeded total, including under concurrency and retries | Sum `/me` over all users after every burst (payments, pays, settlements) |
| C2 | No balance negative, even transiently | Concurrent overdraft race: N payments of full balance → exactly the affordable number succeed, rest 409; `/me` polled during bursts never < 0 |
| C3 | A payment request moves money at most once | Concurrent pay of one request with different keys → exactly one 201, rest 409 `request_not_pending`; same key → one 201 + 200s |
| C4 | Amounts are exact integers; JSON `1000`, `1000.0`, `1e3` are the same valid amount; responses emit integers; booleans/strings are not numbers | Raw-body requests with `1000.0` and `1e3` → 201, response `amount` is `1000` |
| C5 | Single currency from fixture; `minor_units` 0, 2 or 3 (EUR/JPY/BHD); `currency` echoed on `/me`, payments, requests, splits; `minor_units` on `/me` | Reset with each currency |
| C6 | Handle: unique, `^[a-z0-9_]{1,20}$`, immutable; seeded users take fixture handle | `/me` |
| C7 | Signup handle derived from email: local part → lowercase → every char outside `[a-z0-9_]` replaced by `_` → truncated to 20 chars | Signup `Ada.Lovelace+x@example.com` → `ada_lovelace_x`; 25-char local part → first 20 |
| C8 | New users start with balance 0 and can immediately receive payments and be asked for money | Signup, then pay them / request from them |
| C9 | Request lifecycle: `pending` then exactly one of `paid`, `declined`, `cancelled`; terminal states never change | Transition matrix (see G rows) |
| C10 | A request may exceed payer's balance: created normally; pay while short → 409 `insufficient_funds`, nothing changes, request still `pending`; payable later once funds arrive | Create oversized request, pay → 409, fund payer, pay → 201 |
| C11 | Visibility belongs to the payment, one value seen identically by everyone; request objects carry no visibility | Field presence checks; pay-time visibility appears on payment for both parties |
| C12 | Amount ≤ 1000000000 per request; balances exact up to ±2^53 (no float rounding) | Seed balances near 9007199254740000, move 1000000000 and 1, assert exact values |
| C13 | Fixture: seeded users can log in immediately with given password | Login each seeded user |
| C14 | Fixture `balance` is final (after seeded payments); seeded payments are NOT replayed | Seed payments, assert `/me` balance equals fixture balance |
| C15 | Fixture with any `balance` < 0 → 422 `validation_failed`, previous state untouched | Reset bad fixture after good; old token and balance still valid |
| C16 | Seeded payments appear in the feed under the feed rule with full payment shape (handles, currency, `request_id` null, `settlement_id` null, `created_at`) | Seed public and private payments; read `/activity` as party and third party |
| C17 | Seeded requests appear in `GET /requests` for their two parties only, with full request shape; seeded pending requests can be paid/declined/cancelled; seeded non-pending obey G rows | HTTP |
| C18 | Fixture `settlement_operator_ids` (default `[]`) grants operator permission | See K rows |
| C19 | Other malformed fixtures never 5xx and change nothing. Unparseable body or body not a JSON object → 400 `malformed_request`. A fixture field of the wrong JSON type → 400 `malformed_request` (`users`/`payments`/`requests`/`settlement_operator_ids` not an array; an element of those of the wrong type; a user's `id`/`email`/`password`/`display_name`/`handle` not a string; `currency` not a string; `minor_units` not a number; ids inside payments/requests not strings). Right type but bad value or required member missing → 422 `validation_failed` (negative `balance`, `minor_units` not 0/2/3, `users` missing, duplicate handle/id/email, handle not matching the pattern, payment/request referring to an unknown user id, unknown request `status`). In a seeded payment or request the §5 field rules hold as on the endpoints: a non-string `note` (including `null`) → 422, a `visibility` other than `public`/`private` (any type) → 422, an invalid `amount` (any type) → 422; omitted `note`/`visibility` take the defaults. A `balance` of the wrong JSON type may be 400 or 422. (Revised after Verifier round 1, finding 1: §5 wrong-type rule applies to reset; and after round 2, note N7: §5 note/visibility/amount rule applies to seeded records.) | Table of bad fixtures after a good reset; assert status+code and that the old token, balances and feed are untouched |

## D. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx has body `{"error":{"code":…,"message":…}}` incl. framework-level errors (bad JSON, unknown route, wrong method, oversize) | Inspect every error response; unknown route → 404 `not_found` |
| D2 | 400 `malformed_request`: unparseable body, body not a JSON object, or a field of the wrong JSON type (except amount/note/visibility, see D4) | `{bad`, `[]`, `"x"`, `to_handle: 5`, `participant_handles: "ada"`, `email: 1` |
| D3 | 422 `validation_failed`: required field or query parameter missing; correct type but invalid format/out of range | Missing `amount`, missing `to_handle`, etc. |
| D4 | Field rules that override D2: invalid `amount` (string, boolean, null, fraction, array, object, 0, negative, > 1000000000) → 422; non-string `note` incl. `null` → 422; `visibility` anything but `"public"`/`"private"` (incl. null, number) → 422; omission selects defaults (`""`, `"public"`) | Parametrised on every endpoint that takes these fields: `/payments`, `/requests`, `/requests/{id}/pay` (visibility), `/splits`, `/settlements` entries |
| D5 | Integer query params must be plain decimal digits: `1e9`, `4.0`, `+4`, `-1`, empty, `abc` → 422 | `limit` and `offset` on `/requests` and `/activity` |
| D6 | `limit` 1..200 (default 50): 1 and 200 OK; 0 and 201 → 422. `offset` ≥ 0 (default 0): 0 OK; `-1` → 422 | Boundary values on both list endpoints |
| D7 | `Idempotency-Key` length 1..255: 255 chars OK; 256 → 422 `validation_failed`; absent/empty → 400 `missing_idempotency_key` | On each of the five write paths |
| D8 | 401 `unauthenticated`: missing header, non-Bearer scheme, empty token, unknown token | On every authenticated endpoint |
| D9 | No request produces a 5xx, including under concurrent load and with hostile-but-ordinary input (huge numbers `1e400`, deep unicode, 10^30 integers) | Fuzz-ish table + load bursts; grep statuses ≥ 500 |

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

## H. Money and rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| H1 | Shares are whole units, sum to amount, differ by ≤ 1; extra units go to the first participants in given order: (1000,3)→334,333,333; (1,3)→1,0,0; (10,3)→4,3,3; (999,3)→333,333,333; (5,5)→1,1,1,1,1 | Table-driven + property sweep over amounts/n |
| H2 | Different handle order gives the extra unit to a different person | Same people, permuted |
| H3 | A share of 0 is legal and still creates a request (amount 0, `pending`); a 0-amount split request can be paid (moves 0), declined, cancelled without error | (1,3) split, then pay the 0 request |
| H4 | Shares independent of previous splits; after paying splits in full, balances sum to seeded total | Many splits paid, C1 check |

## I. Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{…}}`; atomic read-only snapshot | HTTP; export during writes is internally consistent (balances sum to total) |
| I2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically REPLACES state (not merge); repeating import does not duplicate | Export → mutate → import → state equals export; import twice |
| I3 | Import works in a different fresh container (no dependency on source process, files, volume, port, address) | Export from container A, import into new container B, compare all reads |
| I4 | Preserved: accounts, hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests (status, payment_id), splits' requests, ids, timestamps, operator permissions, settlement membership | Compare `/me`, `/activity`, `/requests` for all users before/after; old tokens still work |
| I5 | Preserved: all completed idempotent request bodies and original responses → replays after import return 200 original body; changed body → 409; failed keys remain reusable | Each of five write paths |
| I6 | Balances are not regenerated or replayed (payments not re-applied to net balances) | Balances identical after import |
| I7 | Import removes all previous destination data and credentials (old destination tokens → 401) | HTTP |
| I8 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid state → 422 `validation_failed`; destination unchanged in all these cases. "Invalid state" includes a `state` that is not an object, a state member that is missing, and a state member whose container type is wrong (e.g. an object where the service's own export has an array, or the reverse): import validates the whole state before replacing anything and never loads a wrong-typed member as empty. An unchanged export is always accepted. (Clarified after Verifier round 1, note N3.) | HTTP with mutated exports, then verify old state intact |
| I9 | Reset clears everything including imported state; ids generated after import do not collide with imported ids | HTTP |
| I10 | Export/import/reset complete within 10 s at ordinary populated state | Time them |

## K. Atomic net settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| K1 | No token → 401; authenticated non-operator → 403 `forbidden`; operator needs idempotency key (F rows) | HTTP |
| K2 | Operator may move money across any wallets (not only their own); permission grants no access to others' requests (pay/decline/cancel → 403; `GET /requests` unchanged) or private activity | HTTP |
| K3 | `transfers` has 1..32 objects: 1 and 32 OK; 0, 33, missing, non-array, non-object element → 422 `validation_failed` | Boundary |
| K4 | Each entry uses payment rules: amount (G4/D4), note (≤200, default `""`, verbatim), visibility (default public) → 422; unknown handle (from or to) → 404; from == to → 422 `self_payment`; unknown entry fields ignored | Per-entry parametrised |
| K5 | Entry errors take precedence in input order and before insufficient funds: first bad entry decides the error | Batch with entry 0 unknown handle + entry 1 invalid amount → 404; reversed → 422; bad entry + unaffordable → entry error |
| K6 | Affordable iff every wallet's balance after ALL transfers is nonnegative (net): chain A→B→C where B starts at 0 succeeds; else 409 `insufficient_funds` | Net-chain and cycle cases |
| K7 | All-or-nothing: failure moves nothing, creates no payments, claims no key (key reusable) | Balances, feed, key reuse after failure |
| K8 | 201 body: `settlement_id`, `committed_at`, `payments` in input order; each member is an ordinary payment with `settlement_id` = batch id, `request_id` null, `created_at` == `committed_at` (same for all); non-members expose `settlement_id: null` everywhere | HTTP |
| K9 | Members follow ordinary feed visibility (private member hidden from third parties and from operator if not party; visible to its parties); the settlement response itself contains every member | `/activity` as each party |
| K10 | Replay → 200 with original complete response; different body → 409; concurrency per F9; conservation C1/C2 under concurrent settlements + payments | HTTP + race |
| K11 | Reset replaces operators; export/import preserves operators, settlement membership and retry responses | With I rows |

## L. Architect decisions where the specification is silent or two rules meet

These are the readings the band builds and verifies against. Reason given for each.

| Row | Decision | Reason |
|---|---|---|
| L1 | Check order on the five idempotent paths: (1) auth → 401; (2) `/settlements` only: operator → 403; (3) key absent/empty → 400 `missing_idempotency_key`; (4) key > 255 → 422; (5) body parse / not an object → 400 `malformed_request`; (6) claimed key: same body → 200 replay, different → 409 reuse; (7) field types and field validation (400/422); (8) handle lookups → 404; (9) self → 422 `self_payment`/`self_request`; (10) state checks (403 not payer, 409 not pending, 409 insufficient funds) | §7 fixes (6) before (7)–(10); the rest follows §5/§6 with cheapest-first ordering |
| L2 | For pay/decline/cancel on a request: unknown id → 404, then caller role → 403, then status → 409, then funds → 409. Any existing request gives 403 to every non-permitted caller (also third parties) | §8 tables: "caller is not the request's payer → 403", "Unknown request → 404" |
| L3 | A handle value that is a string but matches no existing user (any content, incl. `""`, uppercase, invalid characters) → 404 `not_found`; lookups are exact, no case folding or trimming | Endpoint rule "No user has that handle → 404" is the more specific rule (§5 "unless an endpoint specifies a different error") |
| L4 | Handle field of a non-string type → 400; `participant_handles` not an array or with a non-string element → 400; settlement `transfers` container shape (missing, not array, size 0 or > 32, element not an object) → 422; inside an entry, non-string handle → 400, missing handle → 422 | §5 wrong-type rule; §11 "malformed batch shape is 422" overrides it for the batch container |
| L5 | Idempotency body equality: numbers compare by numeric value (`1000` ≡ `1000.0` ≡ `1e3`); objects ignore key order; everything else exact, including unknown fields | §7 "same JSON value after parsing"; §4 says those spellings are the same amount |
| L6 | `POST /requests/{id}/pay`, decline and cancel with a zero-length body: pay treats it as `{}`; decline/cancel never read the body | Body is optional-content on pay; decline/cancel define no body |
| L7 | "Characters" (note 200, password 8, handle truncation 20, key 255) are Unicode code points | Only reading under which emoji notes behave as users expect |
| L8 | Signup: `email`, `password`, `display_name` required strings; email valid iff exactly one `@` with non-empty local and domain parts; emails compared exactly as given; order: types → missing → email format → password length → `email_taken` → `handle_taken` | §6 table order; no normalisation is stated |
| L9 | Seeded payments/requests get `created_at` = reset time; fixture array order is creation order (later = newer). Ties in `created_at` are broken by creation sequence, newest first, so pagination is deterministic. Seeded requests have `payment_id: null` | Fixture carries no timestamps; §8 says same-second order is unspecified |
| L10 | Unknown route or unsupported method → 404 `not_found` with the error body | §5 "Every 4xx … carries this body" |
| L11 | Request bodies are parsed as JSON regardless of the request `Content-Type` header | Spec defines no content-type rejection |
| L12 | Payment objects always include `settlement_id` (null unless a settlement member), in every representation (`/payments`, pay, `/activity`, settlement, replays) | §11 "nonmembers expose null for that field" |
| L13 | Password hashing cost must be chosen so that reset of 200 seeded users finishes within 10 s and 50 concurrent logins each finish within 5 s on 2 vCPU, without blocking other requests past their timeout | §2 limits + §6 hashing rule |
