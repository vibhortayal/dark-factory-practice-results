# Acceptance map: Pocketful stage 1

Source of truth: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (§ numbers below refer to it).
Every row is checked against the built image over HTTP only. "Supplied" = the shipped harness
suite covers at least part of the row; every row also needs the Implementer's own test and the
Verifier's independent check. Rows marked **[choice]** record an Architect decision where the
specification is silent; the reason is given.

## A. Delivery and runtime (§2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` has `Dockerfile`, `RUN.md`, source; no nested `.git`, no symlinks/submodules; `RUN.md` gives one command that builds and starts the service with no manual setup | Follow RUN.md verbatim from a clean clone; `docker build` from scratch |
| A2 | Image runs alone with `-e PORT=<port>` + port mapping; listens on `0.0.0.0:$PORT`, default 8080; compose not needed | `docker run` with PORT set and unset |
| A3 | No outbound network at run time; all deps/seed/init inside the image | Harness `--mode isolated`; `docker run --network none` smoke |
| A4 | Limits: 2 vCPU, 2 GiB, first healthy response ≤ 60 s, 50 requests in flight, each ≤ 5 s (reset/export/import ≤ 10 s) | Run with `--cpus 2 --memory 2g`; 50-way concurrent load with timings |
| A5 | `GET /health` → 200 `{"status":"ok"}` once ready | Direct call |
| A6 | `POST /_test/reset` → 204, empty body; replaces **all** state (users, tokens, payments, requests, splits, settlements, idempotency records, operators); unauthenticated; repeatable | Reset twice with different fixtures; old tokens → 401, old ids gone |
| A7 | Reset fixture: `currency`, `minor_units` ∈ {0,2,3}, `users` (id, email, password, display_name, handle, balance), `payments`, `requests`, optional `settlement_operator_ids` (default `[]`); `payments`/`requests` may be absent | Seed EUR/JPY/BHD; seeded login works immediately; seeded payments and requests readable with their fixture ids |
| A8 | Seeded `balance` is final: seeded payments are **not** replayed against balances | Seed payment + balance, `GET /me` equals fixture balance |
| A9 | Negative fixture balance → 422 `validation_failed`, previous state untouched. **[choice]** any structurally invalid fixture (bad minor_units, duplicate id/handle/email, handle not matching the pattern, payment/request referencing an unknown user, unknown status/visibility, operator id not a user) is also 422 with no change; unparseable body is 400 `malformed_request` (reason: §5 general rule, reset must stay atomic) | Bad fixtures after a good reset, then confirm old state |
| A10 | Responses are `application/json; charset=utf-8`; timestamps RFC 3339 with explicit offset; unknown body fields and unknown query params ignored; ids opaque, ≤ 64 chars | Header and regex checks on every endpoint; extra field/param probes |
| A11 | Every 4xx/5xx body is `{"error":{"code","message"}}`, including unknown routes (404 `not_found`) and wrong methods **[choice]** (404 or 405 with the same envelope) | Probe unknown path/method |
| A12 | No 5xx ever, including under concurrent load and hostile input (huge key, 1000 handles, deep/odd JSON, invalid UTF-8) | Fuzz + load, assert status < 500 |
| A13 | Stage-1 folder must not implement later stages (no browser UI/HTML routes, no authorizations/captures or other stage 2+ surface) | Harness prints `claimed stage: 1`; read stage-2 spec headings, probe `/`, `/login`, `/split` return the 404 envelope |

## B. Money invariants (§1, §4, §9)

| Row | Requirement | Check |
|---|---|---|
| B1 | Sum of all wallet balances always equals the seeded total | Sum `GET /me` over all users after every scenario and after load |
| B2 | No balance ever negative, even transiently | Concurrent overdraft race: N payments of the whole balance → exactly the affordable number succeed, rest 409 |
| B3 | A request moves money at most once | Concurrent pays of one request with different keys → one 201, others 409 `request_not_pending`; same key → one 201, rest 200 |
| B4 | Amounts are exact integers; integral JSON numbers `1000`, `1000.0`, `1e3` are valid and equal; booleans/strings are not numbers; max 1000000000; balances exact up to ±2^53 | `1e9` accepted (→ insufficient_funds or success), `1.5`, `"100"`, `true`, `0`, `-1`, `1000000001` → 422; seed balances near 2^53 and move money exactly |
| B5 | Response amounts and balances are JSON integers (never `10.0`, never strings) | Type check on every money field |

## C. Errors and precedence (§5)

| Row | Requirement | Check |
|---|---|---|
| C1 | 400 `malformed_request`: unparseable body, or a field of the wrong JSON type (except the endpoint-specific rules in C3). **[choice]** a body that parses but is not a JSON object (array, string, number, null) and an empty body where one is required are also 400 `malformed_request`; an empty body on `/requests/{id}/pay` is treated as `{}`; decline/cancel ignore any body (reason: these are "bodies that do not parse" as a request; pay's body is wholly optional) | Raw-content requests per endpoint |
| C2 | 422 `validation_failed`: required field or query parameter missing; correct type but invalid format/out of range/too long | Omit each required field in turn |
| C3 | Endpoint-specific overrides: invalid `amount` of any type (string, bool, null, fraction, out of range) → 422; non-string `note` including `null` → 422; any `visibility` other than `"public"`/`"private"` (wrong case, empty, null, number) → 422; omission selects the default | Matrix per endpoint that takes these fields |
| C4 | Other wrong types → 400: e.g. `to_handle`/`payer_handle` not a string, `participant_handles` not an array or holding a non-string, `email`/`password`/`display_name` not a string | Matrix |
| C5 | Handle supplied as a string that no user has (including strings that cannot be a handle: `""`, `"ADA"`, `"@ada"`) → 404 `not_found` **[choice]** (reason: "No user has that handle"; supplied checks accept 404 or 422) | Probe |
| C6 | `Idempotency-Key`: absent or empty → 400 `missing_idempotency_key`; longer than 255 characters → 422 `validation_failed` (255 ok, 256 not) | Boundary probes on all five write paths |
| C7 | `limit` 1..200 (default 50), `offset` ≥ 0 (default 0); must be plain decimal digits: `1e9`, `4.0`, `+4`, `-1`, `abc`, empty → 422; 0 and 201 → 422; 1 and 200 ok | Both list endpoints |
| C8 | 401 `unauthenticated`: missing, malformed (no `Bearer `, empty token) or unknown token on every authenticated endpoint | Probe each endpoint |
| C9 | **[choice]** Precedence on a write: 401 → idempotency-key header (400/422) → body parse (400) → claimed-key resolution (200 replay / 409 reuse) → field type/validation (400/422) → 404 → 403 → `self_*` → state 409 (`request_not_pending` before `insufficient_funds`). Reason: §7 fixes "authenticated + parsed object, then key resolution, then field validation and resource checks"; the rest follows the table order of each endpoint and "auth before anything" | Combination probes; §7's own example (successful key then invalid body → 409 reuse) |

## D. Authentication (§6, §4 handles)

| Row | Requirement | Check |
|---|---|---|
| D1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; new user balance 0; can immediately receive money and be asked for money | Signup then pay/request them |
| D2 | Handle derived from email: local part, lowercased, every char outside `[a-z0-9_]` → `_`, truncated to 20; shown by `GET /me`; never changes | `Jo.Anne+x@ex.com` → `jo_anne_x`; 30-char local part → first 20 |
| D3 | Email already registered → 409 `email_taken`; derived handle taken → 409 `handle_taken` and no account is created (email stays free, login fails). Email check first. **[choice]** emails compare case-insensitively (reason: one mailbox, and avoids two accounts differing only by case) | `ada@other.com` vs seeded `ada`; then login 401 |
| D4 | Password shorter than 8 characters → 422 (8 ok, 7 not); `email` not `local@domain` (no `@`, empty local or domain) → 422; missing field → 422; wrong type → 400 | Boundary probes |
| D5 | `POST /auth/login` → 200 same shape; wrong password or unknown email → 401 `unauthenticated` | Probe |
| D6 | Tokens never expire; several valid tokens per account, concurrent sessions; each login issues a usable token and does not invalidate earlier ones | Login twice, use both |
| D7 | Passwords stored only as bcrypt/scrypt/Argon2 (or equivalent) hashes; fixture passwords hashed on reset; export never contains a plaintext password | Read source; grep export for the password |
| D8 | Hashing cost must still meet A4 (reset with many users ≤ 10 s, login ≤ 5 s under 50 concurrent logins on 2 vCPU) | Reset with 200 users timed; 50 concurrent logins |
| D9 | All endpoints except `/health`, `/_test/*`, `/auth/signup`, `/auth/login` require a bearer token | C8 probes |

## E. Idempotency (§7): each of POST `/payments`, `/requests`, `/requests/{id}/pay`, `/splits`, `/settlements`

| Row | Requirement | Check |
|---|---|---|
| E1 | First use → 201; replay (same user, method, path, JSON-equal body) → **200** with a body equal as a JSON value to the original | Replay each path; reorder keys/whitespace in the replay |
| E2 | Same key, different body (same user and path) → 409 `idempotency_key_reuse`, even if the new body is invalid or the resource changed; `{}` vs `{"visibility":"public"}` differ | Probes incl. §7 last paragraph |
| E3 | Key scoped per user: two users, same key, no interaction | Probe |
| E4 | Same key + same body on a **different path** is a new request and succeeds normally (e.g. pay rq_A then pay rq_B with one key; `/payments` vs `/requests`) | Probe |
| E5 | A key whose request failed with 4xx is not claimed: reuse is a first use (e.g. insufficient funds, then funded, same key → 201) | Probe on each path |
| E6 | Concurrent identical requests on an unused key: exactly one 201, the rest 200 with the same body, one effect | 50-way burst per path, check balances and record counts |
| E7 | A replay returns the original response even after the resource changed (request later paid/cancelled, etc.) and changes nothing; replayed pay of an already-paid request is 200, never `request_not_pending` | Probe |
| E8 | **[choice]** "Same body" compares parsed JSON values with numbers by numeric value (`100` ≡ `100.0` ≡ `1e2`), objects order-insensitive, arrays order-sensitive, unknown fields included in the comparison (reason: §7 "same JSON value after parsing") | Probe |

## F. Endpoints (§8)

| Row | Requirement | Check |
|---|---|---|
| F1 | `GET /me` → `user_id, display_name, handle, balance, currency, minor_units` | Each currency |
| F2 | `POST /payments` 201 body has exactly the documented fields incl. `request_id: null`, `settlement_id: null`, `currency`, both ids and handles, `created_at`; debit+credit atomic; `note` default `""`, `visibility` default `"public"` | Shape + balances |
| F3 | Payment errors: balance < amount → 409 `insufficient_funds` (balance == amount succeeds); amount rules (B4); own handle → 422 `self_payment`; note > 200 **characters (Unicode code points)** → 422, 200 ok, 200 emoji ok; bad visibility → 422; unknown handle → 404; failed payment leaves no trace (no feed item, balances unchanged) | Matrix |
| F4 | `note` stored and returned verbatim: no trim, escape or normalisation; Unicode/emoji, leading/trailing spaces, combining characters, `<script>`, quotes round-trip byte for byte, also through feed, replay, export/import | Round-trip probes |
| F5 | `POST /requests` 201 body exactly as documented (`status: "pending"`, `payment_id: null`); caller is requester; payer balance not checked (amount > payer balance is fine); errors: amount rules, own handle → 422 `self_request`, note > 200 → 422, unknown handle → 404 | Matrix |
| F6 | `POST /requests/{id}/pay`: only payer; body `visibility` only (default public); 201 with a payment as F2 with `request_id` set; request becomes `paid` with `payment_id`; errors: not pending → 409 `request_not_pending`; short → 409 `insufficient_funds` and nothing changes, later payable; not payer (requester or third party) → 403 `forbidden`; unknown id → 404 | Matrix; pay-after-funding |
| F7 | `POST /requests/{id}/decline`: only payer, no key needed; 200 with request `declined`; again → 200 current state; paid or cancelled → 409 `request_not_pending`; not payer → 403; unknown → 404 | Matrix |
| F8 | `POST /requests/{id}/cancel`: only requester; 200 `cancelled`; again → 200; paid or declined → 409; not requester → 403; unknown → 404 | Matrix |
| F9 | Request lifecycle: `pending` then exactly one of `paid`/`declined`/`cancelled`, also under races (pay vs cancel vs decline concurrently → one winner, money moves iff pay won) | Race probe |
| F10 | `GET /requests`: only requests where caller is requester or payer; newest first by `created_at`; `direction` incoming/outgoing/absent; `status` one of four/absent; unknown value → 422; `limit`/`offset` (C7); `has_more` true iff items exist beyond the last returned; body `{requests, has_more}` | Filters, paging edges (exact multiple of limit, offset past end → `[]`, false), third-party isolation, operator isolation |
| F11 | `POST /splits`: 201 `{split_id, amount, currency, note, shares, requests, created_at}`; `shares` cover every listed participant in given order and sum to amount; one `pending` request per participant except the caller, same order, caller as requester, request note = split note **[choice]**; caller may be included or omitted (omitted: n = listed participants, every one gets a request); only-caller split valid with `requests: []`; no balance checks | Shape + cases |
| F12 | Split errors: amount rules; `participant_handles` missing/empty/duplicate → 422; note > 200 → 422; any unknown handle → 404; validation (422) before 404; a failed split creates no requests | Matrix |
| F13 | §9 rounding: floor share, the first `amount mod n` participants get +1; table 1000/3, 1/3, 10/3, 999/3, 5/5; order changes who gets the extra unit; a `0` share is legal and still creates a request with `amount: 0`. **[choice]** paying a 0-amount request succeeds and yields a payment of amount 0 (reason: balance is not below amount; nothing forbids it) | Table + reorder + property test over many (amount, n) |
| F14 | `GET /activity`: payments only; visible iff `visibility == "public"` or caller is sender or receiver; private hidden from third parties **and from operators**, visible to its receiver; same `visibility` value for everyone; newest first; `{payments, has_more}`; paging as C7; includes seeded and settlement payments; requests and splits never appear | Three-party matrix, paging |
| F15 | Seeded records served through the same shapes: seeded payments have `request_id: null`, `settlement_id: null`, handles, a `created_at`; seeded requests of any status listed and actionable (pending → payable/declinable/cancellable; non-pending → 409) with `payment_id: null` unless paid here | Seed all four statuses |

## G. Export / import (§10)

| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /_test/export` → 200 `{track: "pocketful", format_version: 1, state: {...}}`, unauthenticated, atomic read-only snapshot (later writes do not alter an export already returned) | Export, mutate, compare |
| G2 | `POST /_test/import` with an unchanged export → 204; atomically **replaces** all state (previous data, users and tokens gone); importing twice does not duplicate; works in a fresh container of the same image (no dependency on source process, files, port, network) | Export from container A, import into container B, compare a full read of every endpoint |
| G3 | Preserved across import: accounts and password login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits' requests, operator permissions, settlement membership, ids and timestamps unchanged, completed idempotency records (replay → 200 original body; changed body → 409), failed keys still reusable; balances not replayed | Before/after diff of all reads; replays after import |
| G4 | Import errors: unparseable JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid state → 422 `validation_failed`, destination unchanged | Probes then confirm state |
| G5 | Reset after import clears imported state; export/import complete within 10 s | Probe, timing |

## H. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| H1 | `POST /settlements`: no token → 401; authenticated non-operator → 403 `forbidden`; operator set comes from fixture `settlement_operator_ids` (default none); requires idempotency key (E rows apply) | Probes |
| H2 | Body `transfers`: 1..32 objects (0 and 33 → 422; missing, not an array, non-object member → 422 `validation_failed` "malformed batch shape"); each uses payment rules for `amount`, `note`, `visibility` (defaults `""`, public); unknown handle → 404; `from_handle == to_handle` → 422 `self_payment`; unknown fields ignored | Matrix with boundaries 1, 32, 33 |
| H3 | Entry errors reported in input order (first bad entry's error wins), and before `insufficient_funds` | Two-bad-entry probes |
| H4 | Affordable iff every wallet's **net** balance after all transfers is ≥ 0 (a chain ada→bob→cy where bob starts at 0 is fine); otherwise 409 `insufficient_funds`; all-or-nothing; a failure claims no key and creates no payment | Net-chain case, unaffordable case, then balances/feed unchanged, key reusable |
| H5 | 201 `{settlement_id, committed_at, payments}` in input order; each member is an ordinary payment with `settlement_id` set, `request_id: null`, `created_at == committed_at` for all; non-member payments everywhere expose `settlement_id: null` | Shape |
| H6 | Operator may move money between any wallets (need not be a party) but gains no access to others' requests or private activity; members follow ordinary feed visibility; replay → 200 original complete response; concurrent settlements keep B1/B2 | Operator isolation probes; concurrent settlement load |
| H7 | Reset/import preserve operator permissions, payments, requests, settlement membership and retry responses (G3) | Export/import with a settlement |

## I. Supplied checks

| Row | Requirement | Check |
|---|---|---|
| I1 | Shipped stage-1 suite: every check passes, none skipped/errored; `claimed stage: 1 on the shipped checks` | `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>` (host mode while iterating) |
| I2 | Final check in isolated mode on the accepted revision | Same command with `--mode isolated` and a new `--out` |
