# Acceptance map — Pocketful stage 1

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (§ numbers below). Target: `stage-1/`.
"Check" names how each row is verified: **H** = supplied harness suite, **T** = own HTTP test against the
running container, **C** = concurrency test (burst of parallel clients), **I** = inspection of source/image.
Every row must be checked by the Implementer (self-check) and independently by the Verifier.

## A. Delivery and runtime (§2, §3)
| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds the service source, a `Dockerfile` and a `RUN.md` whose command builds and starts it with no manual setup; no nested `.git` | I + run the RUN.md command |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; listens on `0.0.0.0:$PORT`, default 8080; no compose needed | T: run with PORT set and unset |
| A3 | No outbound network at run time; all deps, init and seed data inside the one container | H `--mode isolated`; T: `docker run --network none` starts healthy |
| A4 | Within 2 vCPU / 2 GiB; first healthy response < 60 s; 50 requests in flight; each request < 5 s (reset/export/import < 10 s) | H isolated; C with 50 clients, timing recorded |
| A5 | `GET /health` → 200 `{"status":"ok"}`, no auth | T |
| A6 | `POST /_test/reset` → 204, no auth, enabled in the image; replaces ALL state (users, tokens, payments, requests, splits, settlements, idempotency records, operators); repeatable; after 204 only the fixture is visible | T: reset twice, old tokens 401, old data gone |
| A7 | Responses are `application/json; charset=utf-8`; 204 has no body | T: header check on success and error |
| A8 | Response timestamps RFC 3339 with explicit offset (`+00:00` form) | T: regex on every `created_at` / `committed_at` |
| A9 | Unknown body fields ignored; unknown query parameters ignored | T |
| A10 | IDs are opaque strings ≤ 64 chars; seeded ids are kept as given | T |
| A11 | Stage 1 only: no UI, no authorizations/captures, nothing from later stages | I + T: `GET /` and `/authorizations` are 404 |

## B. Model and invariants (§1, §4)
| Row | Requirement | Check |
|---|---|---|
| B1 | Sum of all wallet balances always equals the seeded total, under concurrency and retries | C: mixed burst, then sum of `/me` |
| B2 | No balance ever negative, even transiently | C: N clients drain one wallet; successes × amount ≤ balance; no negative `/me` |
| B3 | A request moves money at most once | C: concurrent pays of one request with distinct keys → exactly one 201 |
| B4 | Amounts are exact integers; JSON `1000`, `1000.0`, `1e3` are the same valid amount; booleans, strings, null, non-integral numbers are invalid; responses emit integers; balances exact up to ±2^53 | T |
| B5 | One currency + `minor_units` (0, 2 or 3) from the fixture; EUR/JPY/BHD; echoed by `/me` and every payment/request/split | T/H |
| B6 | Handle: unique, `^[a-z0-9_]{1,20}$`, immutable; seeded users take the fixture handle | T |
| B7 | Signup handle derived from email: local part → lowercase → every char outside `[a-z0-9_]` becomes `_` → truncate to 20 | T/H: `Dee.Ann+tag@…` → `dee_ann_tag`; 30×`a` → 20×`a` |
| B8 | New users start at balance 0 and can immediately receive money and be requested | T/H |
| B9 | Request lifecycle: `pending` → exactly one of `paid` / `declined` / `cancelled`; only payer pays or declines; only requester cancels | T |
| B10 | A request may exceed the payer's balance; it stays pending; paying while short is 409 `insufficient_funds` and changes nothing; payable later once funded | T/H |
| B11 | Visibility belongs to the payment (chosen by payer when money moves), one value seen identically by all; requests carry none | T |
| B12 | Feed rule: a payment is in a caller's `/activity` iff it is `public` or the caller is sender or receiver. Requests and splits never appear | T/H, incl. seeded payments and settlement members |

## C. Fixture / reset (§4, §11)
| Row | Requirement | Check |
|---|---|---|
| C1 | Fixture: `currency`, `minor_units`, `users[] {id,email,password,display_name,handle,balance}`, `payments[] {id,from_user_id,to_user_id,amount,note,visibility}`, `requests[] {id,requester_id,payer_id,amount,note,status}`, optional `settlement_operator_ids` (default `[]`); `payments`/`requests` may be absent or empty | T |
| C2 | Seeded users can log in immediately with the given password | H/T |
| C3 | `balance` is already net of seeded payments — never replay seeded payments onto balances | T: seeded payment present, `/me` equals fixture balance |
| C4 | Negative seeded balance → 422 `validation_failed`, previous state untouched | H/T |
| C5 | Any other invalid fixture → 422 `validation_failed`, unparseable body → 400 `malformed_request`; in both cases previous state untouched | T |
| C6 | Seeded payments appear in `/activity` under the feed rule with full payment shape (`request_id` null, `settlement_id` null, server `created_at`); seeded requests appear in `/requests` with any seeded status and are actionable per lifecycle | H/T |

## D. Errors (§5)
| Row | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code","message"}}`, incl. unknown route (404 `not_found`) and wrong method | T |
| D2 | 400 `malformed_request`: unparseable body, body that is not a JSON object, or a field of the wrong JSON type (other than the D4 fields) | T |
| D3 | 422 `validation_failed`: required field or query parameter missing; right type but invalid format / out of range / over length | T |
| D4 | Field rules that win over D2: invalid `amount` (string, boolean, null, fractional, <1, >1000000000), non-string `note` (incl. `null`), any `visibility` other than `"public"`/`"private"` (incl. `null`, `""`, `"Public"`, non-strings) → 422 `validation_failed`. Omitting `note`/`visibility` selects the default | H/T on every endpoint that takes them |
| D5 | Integer query parameters are plain decimal digits only: `1e9`, `4.0`, `+4`, `abc`, empty, `-1` → 422 | T on `/requests` and `/activity` |
| D6 | `limit` 1..200 (default 50), `offset` ≥ 0 (default 0); otherwise 422 | H/T |
| D7 | `Idempotency-Key` absent or empty → 400 `missing_idempotency_key`; longer than 255 characters → 422 `validation_failed`; exactly 255 accepted | H/T |
| D8 | 401 `unauthenticated` for missing, malformed or unknown bearer token on every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login` | T on each endpoint |
| D9 | No 5xx ever, including under concurrent load and hostile input (huge numbers, deep/odd JSON, 1000-element lists, 10 kB keys, invalid UTF-8) | C + T fuzz |

## E. Authentication (§6)
| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; no `handle` field in the body is used | T |
| E2 | `POST /auth/login` → 200 `{user_id, display_name, token}` | T |
| E3 | Email already registered → 409 `email_taken` | T |
| E4 | Password shorter than 8 characters → 422; `email` not `local@domain` → 422 | T |
| E5 | Wrong password or unknown email on login → 401 `unauthenticated` | T |
| E6 | Derived handle already taken → 409 `handle_taken`, and no account exists afterwards (login 401) | H/T |
| E7 | Tokens never expire; several tokens per account are valid at once | T: two logins, both tokens work |
| E8 | Passwords stored only as bcrypt/scrypt/Argon2 (or equivalent) hashes — also inside exports; hashing must not break the 5 s / 60 s / 50-in-flight limits | I + T |

## F. Idempotency (§7) — applies independently to the five paths `POST /payments`, `/requests`, `/requests/{id}/pay`, `/splits`, `/settlements`
| Row | Requirement | Check |
|---|---|---|
| F1 | First use → normal response 201 | H/T |
| F2 | Replay (same user, method, path, JSON-equal body) → 200 with a body equal to the original as a JSON value; no further state change | H/T on all five |
| F3 | Same key, different body (same user, same path) → 409 `idempotency_key_reuse` | H/T on all five |
| F4 | "Same body" is JSON-value equality: key order and whitespace irrelevant; `{}` ≠ `{"visibility":"public"}` | T |
| F5 | Key scoped to the authenticated user: two users with the same key do not interact | H/T |
| F6 | Same key + same body on a different path is a new request and succeeds normally (incl. `/requests/a/pay` vs `/requests/b/pay`) | H/T |
| F7 | A request that failed with 4xx does not claim the key; the key is then a first use | H/T |
| F8 | Concurrent identical requests with an unused key: exactly one 201, all others 200 with the same body, effect applied once | C on all five |
| F9 | Replay returns the original response even after the resource later changed (e.g. request paid/cancelled since) | T |
| F10 | Once body parsed as a JSON object and caller authenticated, a claimed key is resolved BEFORE field validation and resource checks: a successful request re-sent with an invalid body under the same key → 409 `idempotency_key_reuse` (not 422); pay replay on a paid request → 200 (not 409) | H/T |

## G. Endpoints (§8)
| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}` | H/T |
| G2 | `POST /payments` → 201 payment `{payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, settlement_id:null, created_at}`; `note` default `""`, `visibility` default `"public"` | H/T |
| G3 | Payment errors: balance < amount → 409 `insufficient_funds`; own handle → 422 `self_payment`; note > 200 characters → 422; bad visibility → 422; no such handle → 404 `not_found`; missing `to_handle`/`amount` → 422 | H/T |
| G4 | Debit and credit are one atomic step; a failed payment leaves no trace (no balance change, no feed item, no key claim) | T/C |
| G5 | `note` stored and returned verbatim (no trim/escape/normalisation; Unicode and emoji byte-exact); length counted in characters (200 emoji accepted, 201 rejected) | H/T |
| G6 | `POST /requests` → 201 request `{request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at}`; caller is requester; payer balance not checked | H/T |
| G7 | Request errors: amount rule → 422; own handle → 422 `self_request`; note > 200 → 422; unknown handle → 404 | H/T |
| G8 | `POST /requests/{id}/pay`: payer only; body `visibility` optional, default public; 201 with the payment (`request_id` set); request becomes `paid` with `payment_id` | H/T |
| G9 | Pay errors: unknown request → 404; caller not payer → 403 `forbidden`; not pending → 409 `request_not_pending`; short balance → 409 `insufficient_funds` (nothing changes) | H/T |
| G10 | `POST /requests/{id}/decline`: payer only, no key; 200 with request `status:"declined"`; already declined → 200; `paid`/`cancelled` → 409 `request_not_pending`; not payer → 403; unknown → 404 | H/T |
| G11 | `POST /requests/{id}/cancel`: requester only, no key; 200 `status:"cancelled"`; already cancelled → 200; `paid`/`declined` → 409; not requester → 403; unknown → 404 | H/T |
| G12 | `GET /requests` → `{requests, has_more}`: only requests where caller is requester or payer; newest first by `created_at`; `direction` incoming/outgoing/absent; `status` one of four or absent; unknown value of either → 422; `has_more` true iff items remain beyond the page | H/T |
| G13 | `POST /splits` → 201 `{split_id, amount, currency, note, shares[{handle,amount}], requests[], created_at}`; caller may be in the list or not; `shares` covers every listed participant in order and sums to `amount`; one pending request per participant except the caller, same order, caller as requester; share 0 still creates a request; caller-only split is valid with `requests: []`; no balance is checked | H/T |
| G14 | Split errors: amount rule → 422; `participant_handles` empty or with a duplicate → 422; note > 200 → 422; any unknown handle → 404; 1000 handles must not crash (404 or 422) | H/T |
| G15 | `GET /activity` → `{payments, has_more}`, feed rule B12, newest first by `created_at`, `limit`/`offset` exactly as `/requests`; `direction`/`status` there are just unknown params (ignored) | H/T |

## H. Rounding (§9)
| Row | Requirement | Check |
|---|---|---|
| H1 | Shares are whole units, sum exactly to `amount`, differ by at most 1; larger shares go to the first participants in given order: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333,333,333; 5/5 → 1×5 | H/T, all five table rows |
| H2 | Different handle order moves the extra unit; each split independent of earlier ones; after paying splits in full, balances still sum to the seeded total | T |

## I. Export / import (§10)
| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` → 200 `{track:"pocketful", format_version:1, state:{…}}`, no auth; atomic read-only snapshot unaffected by later writes | T |
| I2 | `POST /_test/import` with an unchanged export → 204; atomically REPLACES state (not merge); repeating it duplicates nothing; removes all previous destination data and credentials | H/T |
| I3 | Import works in a different container of the same image (no dependency on source process, files, volume, port, address) | T: export from container A, import into fresh container B |
| I4 | Preserved byte-for-value: accounts and password login, existing bearer tokens, currency/minor_units, balances, payments (ids, timestamps, visibility, request_id, settlement_id), requests, operator permissions, settlement membership, and every completed idempotent request body + original response (replay still 200, changed body still 409) | T |
| I5 | Nothing regenerated or replayed: ids and timestamps identical, balances not re-applied | T: `/activity` and `/me` equal before/after |
| I6 | Keys of failed requests remain reusable after import | T |
| I7 | Unparseable body → 400 `malformed_request`; missing fields, wrong `track`, wrong `format_version`, or invalid `state` → 422 `validation_failed`; destination unchanged in every case | T |
| I8 | Reset clears everything including imported state; control calls finish < 10 s | T |

## J. Settlements (§11)
| Row | Requirement | Check |
|---|---|---|
| J1 | Fixture `settlement_operator_ids` (default `[]`) names the operators; operator status grants no access to others' requests or private payments | T |
| J2 | `POST /settlements`: no token → 401; authenticated non-operator → 403 `forbidden`; idempotency key required | T |
| J3 | Body `{"transfers":[{from_handle,to_handle,amount,note?,visibility?}]}` with 1..32 objects; malformed batch shape (missing/non-array `transfers`, 0 or >32 entries, non-object entry) → 422 `validation_failed`; unknown fields ignored | T |
| J4 | Each entry uses ordinary payment rules for amount, note, visibility (defaults `""`, `public`); unknown handle → 404; `from_handle == to_handle` → 422 `self_payment` | T |
| J5 | Entry errors are reported in input order (the first bad entry decides) and before `insufficient_funds` | T |
| J6 | Affordability is judged on NET effect: every wallet's balance after all transfers ≥ 0; otherwise 409 `insufficient_funds`. A wallet may pass through money it does not hold (ada→bob 100, bob→cy 100 with bob at 0 is fine) | H/T |
| J7 | All movements commit together or none; a failed settlement creates no payment and claims no key | T/C |
| J8 | 201 `{settlement_id, committed_at, payments[]}` in input order; each member is an ordinary payment with `settlement_id` set, `request_id` null, `created_at` == `committed_at` (same value for all members); every non-member payment exposes `settlement_id: null` | T |
| J9 | Members follow the ordinary feed rule; the settlement response itself shows the operator every member's receipt | T |
| J10 | Replay → 200 with the original complete response; this is the fifth idempotent path (all F rows apply) | T/C |
| J11 | Reset/import preserve operators, payments, requests, settlement membership and retry responses | T |
| J12 | Concurrent settlements and payments on the same wallets keep B1 and B2 | C |

## Decisions where the specification leaves a choice (recorded by the Architect)
| # | Choice | Reason |
|---|---|---|
| K1 | Processing order on idempotent paths: 401 auth → (settlements: 403 non-operator) → `Idempotency-Key` absent/empty 400 → key length 422 → body parse / not-an-object 400 → claimed-key resolution (200 or 409) → field validation (400/422) → resource checks (404, 403, self_*) → state checks (409) | §7 last paragraph fixes key resolution after auth + object parse and before validation; the rest follows §5/§11 wording |
| K2 | Field precedence inside one body: wrong-type 400 / validation 422 first, then 404 unknown handle, then `self_*`, then `insufficient_funds` | §11 "entry errors … before insufficient funds"; same rule reused for single payments |
| K3 | A handle string that cannot match the pattern (`"ADA"`, `"@ada"`, `""`) → 404 `not_found` | endpoint tables: "No user has that handle → 404"; supplied checks accept 404 or 422 |
| K4 | Non-string handle fields, non-array `participant_handles`, non-string array members → 400 `malformed_request`; a non-object JSON body → 400 | §5 "field of the wrong JSON type" |
| K5 | Settlement: non-array `transfers` or non-object entry → 422 | §11 "malformed batch shape is 422" is the more specific rule |
| K6 | Pay order: 404 unknown → 403 not payer → 409 not pending → 409 insufficient | a non-party must learn nothing about state |
| K7 | Emails are compared exactly as given (no case folding); `local@domain` means exactly one `@` with non-empty sides; `email_taken` is checked before `handle_taken`; missing `display_name` → 422, non-string → 400 | spec states no normalisation |
| K8 | Lengths (note 200, password 8, key 255, handle 20) count Unicode code points | supplied check: 200 emoji accepted |
| K9 | Timestamps are UTC written with `+00:00`, sub-second precision kept so ordering is strict; ties broken by creation sequence, newest first | §3.4 example uses a numeric offset |
| K10 | Seeded payments/requests get the reset time as `created_at`, ordered so later array entries are newer. `created_at` is not a fixture field: if a fixture entry carries one it is an unknown field — a valid RFC 3339 string may be kept, anything else is ignored, and it is never a reset error (revised after verifier round 1) | §3.4 unknown body fields are never an error; §4 fixture format lists no `created_at` |
| K11 | Every payment object carries `settlement_id` (null unless a settlement member) | §11 "nonmembers expose null" |
| K12 | Import of parseable JSON that is not the export object (array, missing keys) → 422; reset likewise | §10 wording |
