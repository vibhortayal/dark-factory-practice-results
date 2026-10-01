# Acceptance map — Pocketful stage 1 (payments and settlements)

Specification: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (kickoff checkout, read-only).
Target folder: `stage-1/` in this repository.

How to read this: every row is one requirement, rule, rejection case or boundary from the
specification, with the way it is checked. Check kinds:

- **H** — covered (at least partly) by the shipped harness suite `pocketful/test/stage_1`.
- **V** — the Verifier must exercise it with its own request against the running container
  (the shipped suite is only a portion of the judged suite).
- **I** — inspection of the files in `stage-1/` (source, Dockerfile, RUN.md).

A row is accepted only when the stated check has been run on the exact revision under review.
Rows marked **D** carry an Architect decision where the specification leaves a choice open;
the decision and its reason are listed in section D at the end and are binding for this unit.

## A. Delivery and deployment (§2)

| # | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds the service source, a `Dockerfile` and a `RUN.md` | I |
| A2 | `RUN.md` gives a command that builds and starts the service with no manual setup | V: follow RUN.md verbatim from a clean clone; `GET /health` is 200 |
| A3 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose needed | V: `docker run -e PORT=9123 -p 9123:9123`; H (harness starts it this way) |
| A4 | No outbound network at run time; all deps, init and seed work inside the one container | H in `--mode isolated`; V: `docker run --network none` style start still healthy |
| A5 | Works within 2 vCPU / 2 GiB | H isolated mode applies these limits |
| A6 | Start to first healthy response within 60 s | V: time from `docker run` to first 200 on `/health` |
| A7 | Up to 50 requests in flight without 5xx or invariant break | H (`test_one_wallet_under_ten_clients`); V: own 50-way burst |
| A8 | Per-request 5 s; reset/export/import 10 s | V: time the slowest calls under the burst and a large reset fixture |
| A9 | State is ephemeral; no dependency on host files or volumes | I; V: fresh container starts empty and healthy |
| A10 | Folder is self-contained: no `.git` inside `stage-1/`, no symlinks, no submodules | I: `find stage-1 -type l`, `find stage-1 -name .git` |
| A11 | Stage boundary: no stage 2+ features (no HTML UI/pages, no `/authorizations`, no `/statement`, no refunds/corrections, no as-of `GET /me`) | I; H: harness prints `claimed stage: 1`; V: `GET /`, `/authorizations`, `/statement` are 404 |
| A12 | No source code, API docs or schemas from existing products in this domain | I |

## B. Runtime contract (§3)

| # | Requirement | Check |
|---|---|---|
| B1 | Listens on `0.0.0.0`, port from `PORT`, default `8080` | V: run with and without `-e PORT` |
| B2 | `GET /health` → 200 `{"status":"ok"}`, no auth | H; V |
| B3 | `POST /_test/reset` with fixture → 204, empty body, no auth; state replaced entirely | H; V: state from before reset (users, tokens, payments, requests, idempotency records, operators) is gone |
| B4 | Repeated resets supported; after 204 only that fixture is visible | H; V: reset twice with different fixtures |
| B5 | Responses are `application/json; charset=utf-8` | V: check `Content-Type` on success and error responses |
| B6 | Timestamps are RFC 3339 with explicit offset | V: regex on `created_at`, `committed_at` |
| B7 | Unknown body fields ignored | H (`test_unknown_fields_are_ignored`); V on the other write paths |
| B8 | Unknown query parameters ignored | H (`test_activity_ignores_request_only_parameters`); V |
| B9 | IDs are strings of at most 64 characters | V: every generated id; generated ids never collide with fixture ids |

## C. Model (§4)

| # | Requirement | Check |
|---|---|---|
| C1 | One currency from the fixture; `minor_units` 0, 2 or 3 reported by `GET /me` and `currency` on payments/requests/splits | H (`test_minor_units_zero_service`, `_three_`); V |
| C2 | Amounts are integers of minor units; JSON `1000`, `1000.0`, `1e3` are the same valid amount; responses emit integers | H (`test_integral_json_number_at_maximum_is_valid`); V: send `1000.0`, `1e3`, read back `1000` |
| C3 | Booleans and strings are not amounts → 422 | H (string); V: `true`, `"10"`, `null`, `[]`, `{}`, `1.5`, `1e-1` |
| C4 | Handle unique, `^[a-z0-9_]{1,20}$`, immutable | V |
| C5 | Seeded users take the fixture handle and can log in with the fixture password immediately | H |
| C6 | Signup handle derived from email: local part, lowercased, chars outside `[a-z0-9_]` → `_`, truncated to 20 | H (two tests); V: `A.b-C+d@x.y` → `a_b_c_d` |
| C7 | New users start at balance 0 and can receive money and be requested immediately | H; V |
| C8 | Payment moves money immediately and atomically | H; V under concurrency |
| C9 | Request lifecycle: `pending` → exactly one of `paid`/`declined`/`cancelled`; only payer pays/declines; only requester cancels | H; V: every transition pair |
| C10 | Request above payer balance is created and stays `pending`; pay while short is 409 `insufficient_funds` and changes nothing; becomes payable after money arrives | H; V |
| C11 | Visibility belongs to the payment; requests carry none and never appear in anyone's feed | H; V: request JSON has no `visibility` |
| C12 | Feed rule: a payment is listed iff `public` or caller is sender or receiver; nothing else | H; V: private payment seen by both parties, not by a third party, not by an operator who is not a party |
| C13 | `GET /requests` returns only requests where caller is requester or payer | H; V |
| C14 | A split is not a feed item | H; V |
| C15 | `amount` ≤ 1000000000 per request; balances exact up to ±2^53, no rounding | H; V: balances near 2^53 in a fixture stay exact |
| C16 | Fixture format accepted as given (users, payments, requests, optional `settlement_operator_ids`); seeded ids preserved | H; V |
| C17 | Fixture `balance` is final; seeded payments are not replayed against balances | H (`test_seeded_state`); V |
| C18 | Negative fixture balance → 422 `validation_failed` from reset, nothing changes | H; V: previous state fully intact |
| C19 | Seeded payments obey the feed contract; seeded requests are visible to their two parties only, payable when pending, not payable otherwise | H |
| C20 | Invariant 1: sum of balances equals seeded total at all times | H; V after every scenario and after bursts |
| C21 | Invariant 2: no balance negative, even transiently | V: concurrent overspend burst, exactly the affordable number succeed |
| C22 | Invariant 3: a request moves money at most once | V: concurrent pays of one request with distinct keys → one 201, rest 409 `request_not_pending` |

## E. Errors (§5)

| # | Requirement | Check |
|---|---|---|
| E1 | Every 4xx/5xx body is `{"error":{"code","message"}}` | V on every error class incl. unknown route |
| E2 | Unparseable body → 400 `malformed_request` | H; V on every POST incl. reset/import/signup/login |
| E3 | Field of wrong JSON type (not covered by a specific rule) → 400 `malformed_request` | V: `to_handle: 5`, `participant_handles: "ada"`, `email: 7` (D4) |
| E4 | Missing/empty `Idempotency-Key` → 400 `missing_idempotency_key` | H (four paths); V on `/settlements` |
| E5 | Missing, malformed or unknown bearer token → 401 `unauthenticated` | V on every authenticated endpoint: no header, `Basic x`, `Bearer`, `Bearer nope` |
| E6 | 403 `forbidden` where authenticated but not permitted | H; V |
| E7 | 404 `not_found` for missing resource | H; V |
| E8 | 409 `idempotency_key_reuse` | H; V |
| E9 | 422 `validation_failed` for missing required field/param or rule violation | H; V |
| E10 | Invalid `amount` (incl. strings, booleans) → 422; non-string `note` incl. `null` → 422; `visibility` other than `public`/`private` (any type) → 422; omission selects defaults | H; V: `visibility: 1`, `note: 5` |
| E11 | Integer query parameter must be plain decimal digits: `1e9`, `4.0`, `+4` → 422 | V on `limit` and `offset` of both list endpoints |
| E12 | `Idempotency-Key` 1..255 chars, longer → 422 | H (10 kB); V: 255 ok, 256 → 422 |
| E13 | `limit` 1..200, `offset` ≥ 0, else 422 | H; V: 1, 200 ok; 0, 201, -1, `abc`, empty → 422 |
| E14 | No request produces 5xx, including under load | H; V: fuzzed bodies, huge inputs, concurrent bursts; grep responses for 5xx |

## F. Authentication (§6)

| # | Requirement | Check |
|---|---|---|
| F1 | `POST /auth/signup` → 201 `{user_id, display_name, token}` | H; V |
| F2 | `POST /auth/login` → 200 `{user_id, display_name, token}` | H; V |
| F3 | Email already registered → 409 `email_taken` | V |
| F4 | Password shorter than 8 characters → 422 | V: 7 → 422, 8 → 201 |
| F5 | `email` not `local@domain` → 422 | V: `nope`, `x@`, `a@b@c`, and an email with an empty local part |
| F6 | Wrong password or unknown email → 401 `unauthenticated` | H; V |
| F7 | Derived handle already taken → 409 `handle_taken`, no account created | H |
| F8 | All other endpoints need a bearer token, except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, signup, login | V |
| F9 | Tokens never expire; several valid tokens per account at once | V: two logins, both tokens work |
| F10 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent; never plaintext | I; V: export contains no plaintext password |

## G. Idempotency (§7)

| # | Requirement | Check |
|---|---|---|
| G1 | Five keyed paths: `/payments`, `/requests`, `/requests/{id}/pay`, `/splits`, `/settlements` | H; V |
| G2 | Key scoped to the authenticated user | H (`test_keys_are_scoped_per_user`) |
| G3 | Replay = same user, method, path, body; same key and body on a different path is a new request and succeeds | H; V: same key on `/requests/A/pay` and `/requests/B/pay` |
| G4 | First use → 201; replay → 200 with body equal as a JSON value | H; V on all five paths |
| G5 | Same key, different body → 409 `idempotency_key_reuse` | H; V on all five |
| G6 | Key whose original request failed 4xx is treated as first use | H; V on all five |
| G7 | Body equality is by parsed JSON value (key order/whitespace irrelevant) | V: reorder keys → 200; D8 on `1000` vs `1000.0` |
| G8 | Concurrent identical requests on an unused key: exactly one 201, others 200 same body, one effect | V: 20-way burst on each path |
| G9 | Replay returns original response even after resource changed/cancelled; no further state change | V: create request, cancel it, replay create → 200 original `pending` body |
| G10 | After auth and JSON-object parse, a claimed key is resolved before field validation and resource checks; valid→invalid body on same key is 409 `idempotency_key_reuse` | H (`test_the_key_outranks_the_status_on_pay`); V: invalid body on a claimed key |

## P. API (§8)

| # | Requirement | Check |
|---|---|---|
| P1 | `GET /me` → `user_id, display_name, handle, balance, currency, minor_units` | H |
| P2 | `POST /payments` 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id (null), created_at`, plus `settlement_id` (null) per §11 | H; V: exact key set |
| P3 | `note` defaults `""`, `visibility` defaults `"public"` | H |
| P4 | Balance below `amount` → 409 `insufficient_funds`, nothing moves, no trace | H; V: feed unchanged |
| P5 | `amount` < 1, > 1000000000, non-integer → 422 | H |
| P6 | `to_handle` is caller's own → 422 `self_payment` | H |
| P7 | `note` > 200 characters → 422; exactly 200 ok; 200 emoji ok (count code points) | H |
| P8 | Unknown handle → 404 `not_found` | H |
| P9 | Paying exactly the balance succeeds, leaving 0 | H |
| P10 | `note` stored and returned verbatim, byte for byte (Unicode, emoji, leading/trailing spaces, HTML chars) | H; V |
| P11 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status "pending", payment_id null, created_at` | H; V: exact key set |
| P12 | `POST /requests`: amount range 422; own handle → 422 `self_request`; note > 200 → 422; unknown handle → 404; payer balance not checked | H; V |
| P13 | `POST /requests/{id}/pay` → 201 with a payment exactly like `POST /payments`, `request_id` set; request becomes `paid` with `payment_id` | H |
| P14 | pay: body `visibility` optional default public; `{}` vs `{"visibility":"public"}` under one key is 409 reuse | H |
| P15 | pay: not pending → 409 `request_not_pending`; short → 409 `insufficient_funds`; not payer → 403; unknown → 404 | H; V |
| P16 | pay replay → 200 original payment even though request is now `paid`; no more money moves | H |
| P17 | `decline`: payer only, no key, 200 request with `declined`; twice → 200; `paid`/`cancelled` → 409 `request_not_pending`; not payer → 403; unknown → 404 | H; V |
| P18 | `cancel`: requester only, no key, 200 request with `cancelled`; twice → 200; `paid`/`declined` → 409; not requester → 403; unknown → 404 | H; V |
| P19 | `GET /requests`: only caller's; newest first; `direction` incoming/outgoing/absent; `status` filter; `limit` default 50; `offset` default 0; unknown `direction`/`status` → 422; `has_more` correct; body `{requests, has_more}` | H; V: has_more at exact boundary |
| P20 | `POST /splits` 201: `split_id, amount, currency, note, shares[{handle, amount}], requests[], created_at`; shares cover all listed participants in order and sum to amount; one pending request per participant except caller, in order, caller as requester | H; V: caller omitted from list (D9) |
| P21 | splits: amount range 422; empty or duplicate handles → 422; note > 200 → 422; unknown handle → 404; nobody's balance checked | H |
| P22 | split with only the caller: valid, one share, `requests: []` | H |
| P23 | `GET /activity`: `{payments, has_more}`, newest first, `limit`/`offset` exactly as `GET /requests` | H; V |

## M. Money and rounding (§9)

| # | Requirement | Check |
|---|---|---|
| M1 | Shares are whole units, sum to amount, differ by at most 1; larger shares go to the first participants | H; V: all five table rows (1000/3, 1/3, 10/3, 999/3, 5/5) |
| M2 | Different handle order moves the extra unit | H |
| M3 | A share of 0 is legal and still creates a request | H; V: such a request can be paid, declined, cancelled without 5xx (D10) |
| M4 | Splits independent of previous splits; after paying splits in full balances still sum to seeded total | V |

## X. Export and import (§10)

| # | Requirement | Check |
|---|---|---|
| X1 | `GET /_test/export` → 200 object with `track: "pocketful"`, `format_version: 1`, `state` object; no auth | H; V |
| X2 | `POST /_test/import` with an unchanged export → 204; atomic replacement, not merge; no auth | H; V |
| X3 | Repeating import restores without duplicating anything | V: import twice, compare exports |
| X4 | Invalid JSON → 400 `malformed_request`; missing fields, wrong `track`/`format_version`, invalid `state` → 422, destination unchanged | V: each case, then compare export before/after |
| X5 | Export is an atomic read-only snapshot; later writes do not change it | V |
| X6 | Import depends on nothing from the source process: export from container A imports into fresh container B | V: two containers |
| X7 | Preserved: accounts, hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests, operator permissions, settlement membership, ids and timestamps unchanged | H (partly); V: full comparison of `/me`, `/activity`, `/requests` before/after |
| X8 | Preserved: completed idempotent request bodies and original responses on all five paths — replay after import is 200 original, changed body is 409; failed keys stay reusable | V |
| X9 | Monetary records are not replayed against balances on import | V: balances identical, conservation holds |
| X10 | Import removes all previous destination data and credentials (old tokens → 401) | V |
| X11 | Reset clears all state including imported state | V |
| X12 | Export/import complete within 10 s | V |

## S. Atomic net settlements (§11)

| # | Requirement | Check |
|---|---|---|
| S1 | Fixture `settlement_operator_ids` (default `[]`) names operators | H; V |
| S2 | No token → 401; non-operator → 403 `forbidden`; key required (400 when absent) | V |
| S3 | `transfers` has 1..32 objects; malformed batch shape → 422 | V: missing, not array, `[]`, 33 entries, non-object entry |
| S4 | Each transfer uses payment rules for `amount`, `note`, `visibility` (defaults `""`, `public`) | V |
| S5 | Unknown handle → 404; self-transfer → 422 `self_payment`; unknown entry fields ignored | V |
| S6 | Entry errors take precedence in input order, and before insufficient funds | V: entry 0 unknown handle + entry 1 bad amount → 404; swapped → 422; either with unaffordable batch → the entry error |
| S7 | Affordable iff every wallet's balance after all transfers is ≥ 0 (net, not sequential): a wallet may pass through money it receives in the same batch | H; V: bob with 0 receives 100 and sends 50 → 201 |
| S8 | Unaffordable → 409 `insufficient_funds`, nothing moves | V |
| S9 | All-or-nothing; failed validation claims no key, creates no payment | V: retry same key with fixed body → 201 |
| S10 | 201 body: `settlement_id`, `committed_at`, `payments` in input order | H; V |
| S11 | Every member is an ordinary payment with `settlement_id` set, `request_id` null, `created_at` == `committed_at` for all; non-members expose `settlement_id: null` | V: check ordinary and request-paid payments too |
| S12 | Members follow normal feed visibility; operator who is not a party does not see private members in `/activity`, and gains no access to others' requests | V |
| S13 | Response contains every member receipt (including private ones) | V |
| S14 | Replay → 200 with the complete original response; changed body → 409 | V |
| S15 | Operator may move money between wallets that are not the operator's own | V |
| S16 | Reset/import preserve operator permissions, payments, requests, settlement membership and retry responses | V: export → reset → import → replay settlement key → 200 original |

## D. Architect decisions on open points

These resolve points the specification leaves open. Each is the least surprising reading of
the text; the Verifier treats a different but spec-consistent behaviour as a finding only if
it contradicts the specification itself, and otherwise reports it as a note.

| # | Decision | Reason |
|---|---|---|
| D1 | Check order on a keyed write: (1) auth → 401; (2) operator check on `/settlements` → 403; (3) `Idempotency-Key` absent/empty → 400, longer than 255 → 422; (4) body parse, must be a JSON object → 400; (5) claimed-key resolution → 200 replay / 409 reuse; (6) field validation → 400/422; (7) resource lookups and permissions → 404/403; (8) state checks → 409 `request_not_pending`, then 409 `insufficient_funds` | §7 fixes (1),(4),(5) before (6)–(8); the rest follows the order of the §5 table and the shipped tests |
| D2 | A body that parses but is not a JSON object (array, string, number, `null`) → 400 `malformed_request` | §7 says "parsed as a JSON object"; §5 reserves 400 for wrong type |
| D3 | An empty request body is treated as `{}` on `/requests/{id}/pay`, `/decline` and `/cancel` only; on every other POST it is 400 | pay has only optional fields and decline/cancel take no body (shipped tests post them bodiless) |
| D4 | Wrong JSON type for `to_handle`, `payer_handle`, `from_handle`, `participant_handles` (or its elements), `email`, `password`, `display_name` → 400; `null` counts as wrong type. Missing → 422 | §5 "Other wrong JSON types follow the rule below" |
| D5 | A handle string that is well-typed but matches no user (including ones that cannot match the pattern, e.g. `ADA`, `""`) → 404 `not_found` | Endpoint table: "No user has that handle"; shipped tests accept 404 or 422 |
| D6 | Emails are compared exactly as given (no case folding or trimming); `local@domain` means exactly one `@`, non-empty local and domain, no whitespace | Spec states no normalisation of email |
| D7 | Signup check order: types (400) → missing/format/password length (422) → `email_taken` → `handle_taken`. `display_name` is required and must be a string | §6 table order |
| D8 | Idempotency body comparison is by JSON value with numbers compared numerically, so `1000` and `1000.0` are the same body | §4 says they "represent the same valid amount" |
| D9 | Split share count is the length of `participant_handles` as given; the caller is not added when omitted, and then every listed participant gets a request | §8 "shares covers every participant ... in the order given" |
| D10 | A zero-amount request (from a split) can be paid: it creates a payment of amount 0 and marks the request paid | Nothing forbids it; refusing would strand the request and risk a 5xx path |
| D11 | Unknown route or unsupported method → 404 `not_found` with the standard error body; authentication is checked first only on defined authenticated routes | §5 requires the error body on every 4xx |
| D12 | Third party (neither requester nor payer) acting on a request → 403 `forbidden` | §8 tables: "caller is not the request's payer" → 403 |
| D13 | Reset fixture validation: unparseable → 400; structurally invalid fixture (missing `users`, bad `minor_units`, negative or non-integer balance, duplicate id/email/handle, reference to an unknown user id, unknown operator id, bad status/visibility) → 422, state unchanged. Fixture passwords and seeded amounts are not subjected to signup/payment limits | §4 negative-balance rule generalised; fixtures are stated to be consistent |
| D14 | Seeded payments and requests without a timestamp get a server-assigned `created_at` at reset, increasing in fixture list order (later entry = newer); optional `created_at`, `payment_id`, `request_id`, `settlement_id` in fixture entries are honoured if present | Fixture carries no timestamps; list order is the only ordering information |
| D15 | Ordering ties in list endpoints are broken by creation sequence, newest first | Deterministic paging |
| D16 | Settlement entry check order inside one entry: shape/types and amount/note/visibility → unknown handle (404) → self-transfer (422); first failing entry in input order wins. Wrong-typed handle inside an entry → 400; non-object entry and bad `transfers` container → 422 | §11 "malformed batch shape is 422", "entry errors take precedence in input order" |
| D17 | Storage is in-process memory guarded so each money movement is one atomic step; password hashing must not make reset of a few hundred users exceed 10 s | §2 allows ephemeral state; invariants 1–3 |
