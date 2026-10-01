# Stage 1 acceptance map

Source: `pocketful/spec/stage-1.md` in the kickoff checkout. Every row is a requirement, rule,
rejection case or boundary from the specification and how it is checked. "S" = covered (at
least partly) by a shipped harness check; "O" = must be covered by the band's own tests,
because the shipped checks are only a sample (79% of the graded stage-1 suite is shipped; the
rest is held back and is all derivable from the specification).

Rows marked **CHOICE** resolve a point the specification leaves open. The choice and its
reason are recorded here; if a shipped check contradicts a CHOICE, the check wins and the
contradiction is reported to the Architect.

## A. Delivery (§2)

| # | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` has `Dockerfile` and `RUN.md`; RUN.md gives one command that builds and starts the service with no manual setup | O: follow RUN.md verbatim from a clean clone |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose needed | S (harness builds and starts it) |
| A3 | No outbound network at run time; every runtime dependency is in the image | S: final harness run with `--mode isolated`; O: `docker run --network none` smoke |
| A4 | Within 2 vCPU / 2 GiB; healthy within 60 s of start | S (isolated mode applies the limits) |
| A5 | Up to 50 requests in flight; every request under 5 s (reset/export/import under 10 s) | O: 50-way concurrent mix of logins, payments and reads, timed |
| A6 | State is in the container only; no dependency on host files, volumes or other services | O: review + `--network none` run |
| A7 | No stage-2+ surface in `stage-1/`: no browser UI/HTML routes, no authorizations/holds/captures, no `total`/`available`/`held` on `/me`, no statements, corrections, revisions, refunds or batches | S: harness overshoot line `stage 2: fail`, `claimed stage: 1`; O: review of routes |

## B. Runtime contract (§3)

| # | Requirement | Check |
|---|---|---|
| B1 | Listens on `0.0.0.0:$PORT`, default 8080 | O: run without PORT, and with PORT |
| B2 | `GET /health` → 200 `{"status":"ok"}` once ready | S |
| B3 | `POST /_test/reset` → 204, no auth; replaces ALL state (users, tokens, payments, requests, splits, settlements, idempotency records, operators, currency); repeated resets work | S + O: old token is 401 after reset; old idempotency key is first-use after reset |
| B4 | Responses are `application/json; charset=utf-8` | O: header assertion on success and error |
| B5 | Timestamps are RFC 3339 with explicit numeric offset (`+00:00` style) | O: regex on every `created_at`/`committed_at` |
| B6 | Unknown body fields ignored; unknown query parameters ignored | S + O on every endpoint |
| B7 | IDs are opaque strings ≤ 64 chars; fixture ids are kept as given | O |
| B8 | Unknown route / wrong method → 4xx with the §5 error envelope (CHOICE: 404 `not_found`; reason: envelope is mandatory on every 4xx and `not_found` is the only fitting code) | O |

## C. Model (§4)

| # | Requirement | Check |
|---|---|---|
| C1 | One currency + `minor_units` (0, 2 or 3) from the fixture, echoed on `/me` and every payment/request/split `currency` | S (EUR/JPY/BHD) |
| C2 | Amount is accepted when its JSON numeric value is integral: `1000`, `1000.0`, `1e3` are valid and equal; booleans, strings, `null`, fractions are not | S + O: send raw bodies `1000.0`, `1e3`, `1.5`, `true`, `"5"`, `null` |
| C3 | Amounts in responses are JSON integers (never `1500.0`), exact, no float rounding; balances exact up to ±2^53 | O: raw-text assertion; large-value arithmetic test |
| C4 | Handle unique, `^[a-z0-9_]{1,20}$`, immutable; seeded users take the fixture handle | S |
| C5 | Signup handle = email local part, lowercased, every char outside `[a-z0-9_]` → `_`, truncated to 20 | S + O: `A.B-c+d@x` → `a_b_c_d`; 25-char local part |
| C6 | New users start at balance 0, can receive and be requested immediately | S |
| C7 | Payment is immediate and atomic; request lifecycle `pending` → exactly one of `paid`/`declined`/`cancelled` | S + O (concurrency in H) |
| C8 | Request above payer balance is legal, stays pending; pay while short → 409 `insufficient_funds`, nothing changes; payable later once funded | S |
| C9 | Visibility lives on the payment only; requests carry none | S + O: request objects have no `visibility` key |
| C10 | Feed rule: payment visible iff `public` OR caller is sender OR receiver. No other rule | S + O: private settlement member / private request payment hidden from third party and from an operator who is not a party |
| C11 | Requests never in `/activity`; `GET /requests` only where caller is requester or payer | S |
| C12 | A split is not a feed item | O |
| C13 | Fixture: seeded users can log in immediately with the given password | S |
| C14 | Fixture `balance` is final; seeded payments are NOT replayed against balances | S + O: sum of `/me` balances equals sum of fixture balances with seeded payments present |
| C15 | Negative fixture balance → reset 422 `validation_failed`, nothing changes (previous state and tokens still work) | S |
| C16 | CHOICE: any other structurally invalid fixture (not an object, missing/invalid `currency`/`minor_units`/`users`, duplicate id/handle/email, handle not matching the pattern, non-integer balance, payment/request referencing an unknown user, unknown request status, unknown visibility, operator id not a user) → 422 `validation_failed`, nothing changes; unparseable JSON → 400 `malformed_request`. Reason: "change nothing" on a reset error + never 5xx | O |
| C17 | Fixture `payments`, `requests`, `settlement_operator_ids` may each be omitted (→ empty) | O |
| C18 | CHOICE: seeded payments/requests get `created_at` = reset time unless the fixture supplies a valid RFC 3339 `created_at` (then it is kept); listing order for equal timestamps is fixture order with later entries newer (stable internal sequence). Seeded request may carry `payment_id`, seeded payment may carry `request_id` and `note`/`visibility` defaults apply. Reason: spec gives no seeded timestamps; ordering must be deterministic | O |

## D. Errors (§5)

| # | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code","message"}}` | S + O on every rejection below |
| D2 | 400 `malformed_request`: unparseable body, body that is not a JSON object (CHOICE: arrays/scalars/empty body on a body-taking endpoint; `/requests/{id}/pay` with an empty body is treated as `{}` — CHOICE, reason: body is fully optional there), or a field of the wrong JSON type (e.g. `to_handle: 5`, `participant_handles: "a"`, `email: 1`) | S + O |
| D3 | Exceptions that are 422 not 400: any invalid `amount` (string, boolean, null, fraction, <1, >1e9); non-string `note` incl. `null`; any `visibility` other than exactly `public`/`private` (incl. `null`, `""`, `"Public"`, numbers) | S |
| D4 | Missing required field or query parameter → 422 `validation_failed` | S |
| D5 | 400 `missing_idempotency_key` when header absent or empty on the five idempotent paths | S + O (settlements) |
| D6 | `Idempotency-Key` longer than 255 characters → 422 `validation_failed` (10 kB header must not be dropped by the HTTP server) | S |
| D7 | 401 `unauthenticated`: missing, malformed (not `Bearer <token>`) or unknown token, on every authenticated endpoint | O: each endpoint without token, with `Basic x`, with `Bearer nope` |
| D8 | `limit` 1..200 default 50; `offset` ≥ 0 default 0; plain decimal digits only — `1e9`, `4.0`, `+4`, `-1`, `abc`, empty string, `0` (limit), `201` → 422 | S + O (`+4`, `4.0`, `1e1`, empty) |
| D9 | Never a 5xx, including under concurrency and hostile input (deep JSON, huge arrays, 1000 handles, invalid UTF-8, huge numbers like `1e400`, very long strings) | S + O fuzz |
| D10 | CHOICE — precedence on idempotent writes: 401 → (settlements only: 403 non-operator) → missing key 400 / key too long 422 → body parse 400 → claimed-key resolution (replay 200 / 409 reuse) → field validation (400 wrong type, then 422) → domain codes (`self_payment`/`self_request`) → 404 unknown handle/resource → 403 → 409 state → 409 `insufficient_funds`. Reason: §7 fixes key resolution after auth+parse and before validation; the rest follows "most specific last" and the table order | O |

## E. Authentication (§6)

| # | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; token works immediately | S |
| E2 | `POST /auth/login` → 200 same shape; a new token each time, earlier tokens stay valid (multiple concurrent sessions); tokens never expire | O |
| E3 | Email already registered → 409 `email_taken` (CHOICE: exact string match on the email; checked before `handle_taken`. Reason: spec says "already registered", no normalisation stated) | O |
| E4 | Password < 8 characters → 422; exactly 8 accepted | O |
| E5 | `email` not `local@domain` (no `@`, empty local, empty domain) → 422 | O |
| E6 | Wrong password or unknown email on login → 401 `unauthenticated` | O |
| E7 | Derived handle already taken → 409 `handle_taken`, no account created (same email can't log in; no balance row) | S |
| E8 | Missing `email`/`password`/`display_name` → 422; wrong type → 400 | O |
| E9 | Passwords stored only as bcrypt/scrypt/Argon2 (or equivalent) hashes — also in exports; never plaintext | O: inspect export + code review |
| E10 | All endpoints except `/health`, `/_test/*`, `/auth/signup`, `/auth/login` require a bearer token | O |

## F. Idempotency (§7) — applies to each of the five paths independently

| # | Requirement | Check |
|---|---|---|
| F1 | First use → 201; replay (same user, method, path, body) → 200 with the identical JSON body | S + O per path |
| F2 | Same key, different body → 409 `idempotency_key_reuse`, even when the new body is invalid (key resolution precedes validation) | S + O |
| F3 | Body equality is JSON-value equality: key order/whitespace irrelevant; `{}` ≠ `{"visibility":"public"}`. CHOICE: numbers compare by numeric value (`1000` = `1000.0`), unknown fields are part of the body. Reason: "same JSON value after parsing" | S + O |
| F4 | Key scoped to the authenticated user: two users, same key, no interaction | S |
| F5 | Same key + same body on a different path is a new request and succeeds (CHOICE: records keyed by user + method + path + key) | S + O incl. two different `/requests/{id}/pay` paths |
| F6 | A request that failed 4xx does not claim its key: reuse is a first use, with the same or a different body | S |
| F7 | N concurrent identical requests with a fresh key: exactly one 201, the rest 200 with the same body, effect applied once | O: 20-way race on each path |
| F8 | Replay returns the ORIGINAL response even after the resource changed (request later paid/cancelled, balance changed) and changes nothing | S + O |
| F9 | Replay of a successful pay on an already-paid request → 200 original payment, never `request_not_pending` | S |

## G. API (§8)

| # | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `user_id, display_name, handle, balance, currency, minor_units` exactly | S |
| G2 | `POST /payments` 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, settlement_id:null, created_at` | S + O (`settlement_id` present and null) |
| G3 | `note` default `""`, `visibility` default `"public"` on omission only | S |
| G4 | Balance below amount → 409 `insufficient_funds`, no trace in either wallet or the feed; paying exactly the balance succeeds | S |
| G5 | amount <1, >1000000000, non-integer → 422; exactly 1 and exactly 1000000000 in range | S |
| G6 | Own handle → 422 `self_payment` | S |
| G7 | `note` > 200 characters → 422; exactly 200 accepted; length counted in Unicode code points (200 emoji OK, 201 emoji rejected) | S |
| G8 | Unknown handle → 404 `not_found` (CHOICE: a handle string that cannot match the pattern, e.g. `""`, `"ADA"`, `"@ada"`, is also 404 — "no user has that handle") | S |
| G9 | `note` stored and returned verbatim, byte for byte: no trim, escape or Unicode normalisation (leading/trailing spaces, `<script>`, combining marks, emoji, `\u0000`-free control chars) | S + O |
| G10 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at`; caller is requester | S |
| G11 | Request rejections: amount range 422; own handle 422 `self_request`; note > 200 → 422; unknown handle 404; payer balance NOT checked | S |
| G12 | `POST /requests/{id}/pay`: payer only; body `visibility` optional default public; 201 with payment (`request_id` set); request becomes `paid` with `payment_id` | S |
| G13 | Pay rejections: unknown id 404; caller not payer 403 (requester and third party alike — CHOICE: 403 for any authenticated non-payer of an existing request, per the endpoint table); not pending 409 `request_not_pending`; short balance 409 `insufficient_funds` (request stays pending); bad visibility 422 | S + O |
| G14 | A request moves money at most once: concurrent pays with DIFFERENT keys → exactly one 201, others 409 `request_not_pending`; pay racing decline/cancel → exactly one wins | O |
| G15 | `POST /requests/{id}/decline`: payer only, no key needed, 200 with request `declined`; repeat → 200; `paid`/`cancelled` → 409 `request_not_pending`; not payer 403; unknown 404 | S + O |
| G16 | `POST /requests/{id}/cancel`: requester only, no key, 200 `cancelled`; repeat → 200; `paid`/`declined` → 409; not requester 403; unknown 404 | S + O |
| G17 | Decline/cancel accept a missing or empty body and ignore any `Idempotency-Key` | S + O |
| G18 | `GET /requests`: only caller's, newest first; `direction` incoming/outgoing/absent; `status` one of four/absent; unknown value → 422; `limit`/`offset` per D8; `has_more` true iff items exist beyond the page; body `{requests, has_more}` | S + O (offset beyond end → empty, `has_more:false`) |
| G19 | `POST /splits` 201 body: `split_id, amount, currency, note, shares[{handle,amount}], requests[...], created_at`; shares cover every participant incl. caller in given order and sum to amount; one pending request per participant except the caller, same order, caller as requester, request `note` = split note (CHOICE: note copied; reason: the request is the share of that split) | S + O |
| G20 | Caller may be included or omitted; when omitted the caller has no share and all participants get requests | O |
| G21 | Split rejections: amount range 422; `participant_handles` empty or with a duplicate → 422; missing → 422; not an array or non-string member → 400; note > 200 → 422; unknown handle → 404. Duplicate check precedes the unknown-handle check (CHOICE). No upper bound on participants is stated: 1000 handles must be validated, not crash | S + O |
| G22 | Caller-only split is valid: one share, `requests: []`. Splits never check balances. Zero share still creates a request (amount 0 request is legal only via a split) | S |
| G23 | Paying a zero-amount split request: CHOICE — succeeds with a zero-amount payment, request becomes `paid`. Reason: the request is legal and pending, and nothing in the pay table rejects it | O |
| G24 | A failed split creates no requests at all (atomic) | O |
| G25 | `GET /activity`: `{payments, has_more}`, newest first by `created_at`, C10 visibility, paging per D8, ignores `direction`/`status` | S |

## H. Money invariants (§1, §9)

| # | Requirement | Check |
|---|---|---|
| H1 | Sum of all balances always equals the seeded total (signups add 0) | S + O after every concurrency test |
| H2 | No balance negative, even transiently: N concurrent payments from one wallet that together exceed it → exactly floor(balance/amount) succeed, the rest 409 | S + O: 50-way burst, also cross-payments A↔B (deadlock check) |
| H3 | Equal-split rule: base = amount div n, first (amount mod n) participants get +1; table rows 1000/3, 1/3, 10/3, 999/3, 5/5 | S + O: property test over amounts and n |
| H4 | Different handle order moves the extra unit; shares independent of earlier splits | S |
| H5 | After splits are paid in full, balances still sum to the seeded total | O |

## I. Export / import (§10)

| # | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{...}}` | S |
| I2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically replaces all state; repeated import → same state, nothing duplicated | S + O |
| I3 | Import invalid JSON → 400; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid state (wrong types, dangling references, negative balance) → 422, destination unchanged | O |
| I4 | Preserved across export→reset→import and export→fresh container→import: accounts + password login, existing bearer tokens, currency/minor_units, balances, payments (ids, timestamps, notes, visibility, links), requests (status, payment_id), splits, settlement membership, operator ids, every completed idempotent request body with its original response | O: replay each of the five paths after import → 200 identical body; changed body → 409 |
| I5 | Nothing regenerated or replayed: ids and timestamps identical, balances not double-applied | O: deep-equal export A vs export after import |
| I6 | Failed-request keys remain reusable after import | O |
| I7 | Import removes all previous destination data and credentials (old tokens 401, old users can't log in) | O |
| I8 | Reset clears imported state | O |
| I9 | Export is an atomic read-only snapshot: a later write does not alter an export already taken; export under concurrent writes is internally consistent (balances sum to total) | O |
| I10 | No dependency on source process, files, volume, port or address: export from container A imports into a new container B | O |
| I11 | Export/import/reset each under 10 s for a few hundred users | O |
| I12 | `state` carries its own internal schema version so later stages can accept this stage's exports (design requirement for the stage-2 upgrade path; no stage-2 behaviour) | O: review |

## J. Settlements (§11)

| # | Requirement | Check |
|---|---|---|
| J1 | Fixture `settlement_operator_ids` (default `[]`) names operators | S |
| J2 | `POST /settlements`: no token 401; authenticated non-operator 403 `forbidden`; key required (400 when missing) | O |
| J3 | `transfers` is an array of 1..32 objects; missing, not an array, empty, 33+, or a non-object member → 422 `validation_failed` (batch shape) | O: 0, 1, 32, 33 |
| J4 | Each entry: `from_handle`, `to_handle`, `amount` (ordinary amount rules), optional `note` (default `""`, ≤ 200), optional `visibility` (default public); missing handle → 422; unknown handle (either side) → 404; `from_handle == to_handle` → 422 `self_payment`; unknown entry fields ignored | O |
| J5 | Entry errors are reported in input order (first bad entry wins) and always before `insufficient_funds` | O: bad entry 2 + unaffordable batch → entry-2 error; two bad entries → first one's code |
| J6 | Affordability is NET: every wallet's balance after all incoming and outgoing transfers ≥ 0; a wallet may pass through more than it holds (A→B 100, B→C 100 with B at 0 is fine); otherwise 409 `insufficient_funds` | S + O |
| J7 | All-or-nothing: on any failure no payment exists, no balance changed, key not claimed (reusable) | O |
| J8 | 201 body `{settlement_id, committed_at, payments[...]}` in input order; every member is an ordinary payment object with `settlement_id` set, `request_id: null`, `created_at` == `committed_at` (same value for all members); `from_*` is the transfer's sender, not the operator | S + O |
| J9 | Every payment anywhere in the API exposes `settlement_id` (null for non-members) | O |
| J10 | Members follow the ordinary feed rule (private member hidden from third parties and from the operator when not a party); the operator gains no access to other users' requests or private activity | O |
| J11 | Replay → 200 with the original complete response; different body same key → 409; concurrent identical → one 201 | O |
| J12 | The operator may settle across any wallets, including ones the operator is not a party to; an operator may also be a party | S + O |
| J13 | Reset/import preserve operator permissions, payments, requests, settlement membership and retry responses | O (with I4) |
| J14 | Concurrent settlements and payments over the same wallets keep H1 and H2 | O |
