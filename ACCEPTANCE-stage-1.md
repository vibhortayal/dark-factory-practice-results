# Acceptance map — pocketful stage 1

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (sha256 f5e4c644…c438a6). Target: `stage-1/`.
Check kinds: **H** = supplied harness suite, **T** = own HTTP test against the running container, **C** = concurrency test (parallel clients), **I** = inspection of source/image. Every row needs T (or C/I) evidence; H alone never closes a row.

## A. Delivery and runtime (§1–§3)
| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds source, `Dockerfile`, `RUN.md` with one command that builds and starts the service, no manual setup; no nested `.git`, no symlinks/submodules | I + follow RUN.md verbatim |
| A2 | Image runs alone with `-e PORT=<port>` + port mapping; listens on `0.0.0.0:$PORT`, default 8080; compose not needed | T: run with PORT set and unset |
| A3 | No outbound network at run time; all deps, init and assets inside the image | H `--mode isolated`; T: `docker run --network none`-style check |
| A4 | Limits: 2 vCPU, 2 GiB, first healthy ≤60 s, 50 requests in flight, 5 s per request (10 s for reset/export/import) | C: 50 parallel clients, timings recorded |
| A5 | `GET /health` → 200 `{"status":"ok"}` once store is ready | T |
| A6 | `POST /_test/reset` (no auth) → 204, replaces ALL state (users, tokens, payments, requests, splits, settlements, idempotency records, operators); repeatable; later requests see only the fixture | T: reset twice, old tokens 401, old data gone |
| A7 | Responses `application/json; charset=utf-8`; timestamps RFC 3339 with explicit offset (emit `+00:00`, not bare/naive) | T: header + regex on every timestamp field |
| A8 | Unknown body fields ignored; unknown query params ignored | T on every endpoint |
| A9 | IDs opaque strings ≤64 chars; seeded ids kept as given | T |
| A10 | No request yields 5xx, including under concurrency and garbage input (bad JSON, wrong types, huge keys, unknown routes/methods → 4xx with error body) | C + T fuzz |
| A11 | Only stage 1 is implemented: no UI, holds or other stage-2+ surface; harness prints `claimed stage: 1` | H + I |

## B. Invariants (§1)
| Row | Requirement | Check |
|---|---|---|
| B1 | Sum of all wallet balances always equals the total seeded by the last reset | C: mixed burst (payments, pays, settlements), then sum `/me` |
| B2 | No balance ever negative, even transiently (check-and-debit atomic) | C: N clients overspend one wallet; successes × amount ≤ balance |
| B3 | A payment request moves money at most once (concurrent pay, pay vs decline/cancel race) | C: parallel pay with distinct keys → exactly one 201 |
| B4 | Amounts are exact integers; no float arithmetic; `amount` ≤ 1000000000; balances exact within ±2^53 | T: large seeded balances (e.g. 9007199254740000) + I |

## C. Model and fixture (§4)
| Row | Requirement | Check |
|---|---|---|
| C1 | One currency from fixture; `minor_units` 0, 2 or 3 (EUR/JPY/BHD); reported by `/me` and in `currency` fields | T with each currency |
| C2 | Amount accepts JSON `1000`, `1000.0`, `1e3` as the same value; rejects fractions, strings, booleans, null | T |
| C3 | Handles unique, `^[a-z0-9_]{1,20}$`, immutable; seeded handle from fixture | T |
| C4 | Signup handle derived: local part → lowercase → chars outside `[a-z0-9_]` become `_` → truncate to 20 | T: `Ada.Smith+x@…`, 30-char local part |
| C5 | New users start at balance 0 and can immediately receive money and be asked for money | T |
| C6 | Seeded users can log in immediately with fixture password | T |
| C7 | Fixture `balance` is final; seeded payments are NOT replayed against balances | T: seed payment, balances unchanged |
| C8 | Seeded payments appear in `/activity` under the feed rule with full payment shape; seeded requests appear in `/requests` to their two parties with given status and are payable when pending | T |
| C9 | Negative fixture balance → 422 `validation_failed`, state unchanged (previous tokens/balances still valid) | T |
| C10 | Fixture optional parts (`payments`, `requests`, `settlement_operator_ids`) may be absent → defaults empty | T |

## D. Errors (§5)
| Row | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code","message"}}` — including 404 unknown route and 405-style cases | T |
| D2 | 400 `malformed_request`: unparseable body, or field of wrong JSON type (e.g. `to_handle: 5`); body not a JSON object | T |
| D3 | 422 `validation_failed`: missing required field/query param, bad format, out of range, over max length | T |
| D4 | Field-rule precedence: invalid `amount` (incl. string/boolean), non-string `note` (incl. `null`), any `visibility` not `public`/`private` (incl. wrong type) → 422, not 400. Omission selects defaults | T |
| D5 | Integer query params are plain decimal digits: `1e9`, `4.0`, `+4`, `-1`, empty, `abc` → 422 | T on `/requests` and `/activity` |
| D6 | `limit` 1..200 (0, 201 → 422); `offset` ≥ 0 | T |
| D7 | `Idempotency-Key` absent/empty → 400 `missing_idempotency_key`; longer than 255 chars → 422 `validation_failed`; exactly 255 ok | T on all five paths |
| D8 | 401 `unauthenticated`: missing, malformed (no `Bearer `) or unknown token; 403 `forbidden`; 404 `not_found` | T |

## E. Authentication (§6)
| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; no `handle` field in body is honoured | T |
| E2 | `POST /auth/login` → 200 same shape; wrong password or unknown email → 401 `unauthenticated` | T |
| E3 | Email already registered → 409 `email_taken`; derived handle taken → 409 `handle_taken` and no account created (login fails after) | T |
| E4 | Password shorter than 8 chars → 422; email not `local@domain` → 422 | T |
| E5 | All endpoints need bearer token except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, signup, login | T: each route without token → 401 |
| E6 | Tokens never expire; several valid tokens per account at once | T: login twice, both tokens work |
| E7 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent; never plaintext (also in export) | I + inspect export |

## F. Idempotency (§7) — each of `POST /payments`, `/requests`, `/requests/{id}/pay`, `/splits`, `/settlements`
| Row | Requirement | Check |
|---|---|---|
| F1 | First use → 201; replay (same user, method, path, JSON-equal body) → 200 with body identical as JSON value; no further state change | T per path |
| F2 | Same key, different body → 409 `idempotency_key_reuse` | T per path |
| F3 | Body equality is by parsed JSON value: key order/whitespace irrelevant; `{}` ≠ `{"visibility":"public"}` | T |
| F4 | Key scoped to the user: two users, same key, no interaction | T |
| F5 | Same key + same body on a different path is a new request and succeeds | T (e.g. pay two different requests with one key) |
| F6 | Key whose original request failed 4xx is unclaimed: reuse is a first use (even with a different body) | T |
| F7 | Concurrent identical requests on a fresh key: exactly one 201, rest 200 with same body, effect once | C |
| F8 | Replay returns original response even after the resource changed (e.g. request later paid/cancelled, balance now short) | T |
| F9 | Order: auth + body parsed as object → claimed key resolved BEFORE field validation and resource checks; successful key + now-invalid body → 409 `idempotency_key_reuse` | T |

## G. Endpoints (§8)
| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `user_id, display_name, handle, balance, currency, minor_units` | T |
| G2 | `POST /payments` → 201 payment: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, settlement_id:null, created_at`; defaults note `""`, visibility `public` | T |
| G3 | Payment errors: balance < amount → 409 `insufficient_funds`; amount <1, >1e9, non-integer → 422; own handle → 422 `self_payment`; note >200 chars → 422 (200 ok); bad visibility → 422; unknown handle → 404 | T incl. boundaries 1, 1000000000, exact-balance payment |
| G4 | Debit+credit atomic; failed payment leaves no trace (no feed item, no balance change) | T + C |
| G5 | `note` stored/returned verbatim: no trim/escape/normalise; Unicode + emoji round-trip; length counted in characters | T: leading/trailing spaces, emoji, combining chars, HTML |
| G6 | `POST /requests` → 201 request: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at`; caller is requester; payer balance NOT checked | T: request above payer balance |
| G7 | Request errors: amount range/type → 422; own handle → 422 `self_request`; note >200 → 422; unknown handle → 404 | T |
| G8 | `POST /requests/{id}/pay`: payer only; body `visibility` optional default `public`; 201 with payment (`request_id` set); request becomes `paid` with `payment_id` | T |
| G9 | Pay errors: not pending → 409 `request_not_pending`; short balance → 409 `insufficient_funds` changing nothing, request stays pending and is payable after money arrives; not payer → 403; unknown → 404 | T |
| G10 | Replay of a successful pay → 200 original payment, never `request_not_pending`, no extra money | T |
| G11 | `POST /requests/{id}/decline`: payer only, no key; 200 `status:"declined"`; already declined → 200; paid/cancelled → 409 `request_not_pending`; not payer → 403; unknown → 404 | T |
| G12 | `POST /requests/{id}/cancel`: requester only, no key; 200 `status:"cancelled"`; already cancelled → 200; paid/declined → 409; not requester → 403; unknown → 404 | T |
| G13 | `GET /requests`: only caller's requests; newest first; `direction` incoming/outgoing/absent; `status` one of four/absent; unknown value → 422; `limit` default 50, `offset` default 0; `{requests, has_more}` with `has_more` exact | T: pagination walk incl. boundary where remaining = 0 |
| G14 | `POST /splits` → 201 `split_id, amount, currency, note, shares[{handle, amount}], requests[], created_at`; caller may be in list or not; one pending request per participant except caller, caller as requester, in given order; shares cover every listed participant in order | T both variants |
| G15 | Split errors: amount range/type → 422; `participant_handles` empty or with duplicate → 422; note >200 → 422; any unknown handle → 404; no balance checks | T |
| G16 | Split with caller as only participant is valid: one share, `requests: []` | T |
| G17 | `GET /activity` → `{payments, has_more}`; a payment appears iff `public` OR caller is sender or receiver; newest first; limit/offset as G13 | T: third party sees public, not private; receiver sees private |
| G18 | Requests and splits never appear in `/activity`; requests never visible to third parties (third party on `/requests/{id}/*` gets 403 per endpoint tables) | T |

## H. Rounding (§9)
| Row | Requirement | Check |
|---|---|---|
| H1 | Shares are whole units, sum to `amount`, differ by ≤1, larger shares to first participants: 1000/3→334,333,333; 1/3→1,0,0; 10/3→4,3,3; 999/3→333×3; 5/5→1×5 | T table |
| H2 | Reordering handles moves the extra unit; share 0 is legal and still creates a request (amount 0, payable) | T |
| H3 | Splits independent of each other; after paying all split requests balances still sum to seeded total | T |

## I. Export / import (§10)
| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{…}}`; atomic read-only snapshot | T + C (export during writes is self-consistent: balances sum to total) |
| I2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomic replacement, not merge; repeat import → same state, no duplicates | T |
| I3 | Import works in a fresh container (no dependency on source process, files, port) | T: export from A, import into B |
| I4 | Preserved: accounts + password login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits' requests, operator permissions, settlement membership, ids and timestamps unchanged, completed idempotency records (replay → 200 original body; different body → 409) | T: full before/after diff |
| I5 | Failed-request keys stay reusable after import; balances not replayed/regenerated | T |
| I6 | Import removes all prior destination data and credentials (old tokens 401) | T |
| I7 | Invalid JSON → 400 `malformed_request`; missing fields, wrong `track`/`format_version`, invalid `state` → 422, destination unchanged | T |
| I8 | Reset clears everything including imported state | T |

## J. Settlements (§11)
| Row | Requirement | Check |
|---|---|---|
| J1 | Fixture `settlement_operator_ids` (default `[]`) names operators; operator status grants no access to others' requests or private activity | T |
| J2 | `POST /settlements`: no token → 401; non-operator → 403 `forbidden`; key required (D7, F1–F9) | T |
| J3 | `transfers` is an array of 1..32 objects; missing/non-array/empty/33+/non-object entry → 422 `validation_failed` | T: 0, 1, 32, 33 |
| J4 | Each entry: payment amount/note/visibility rules, defaults `""`/`public`; unknown handle → 404; `from_handle == to_handle` → 422 `self_payment`; unknown fields ignored | T |
| J5 | Entry errors take precedence in input order (first bad entry decides the code) and before `insufficient_funds` | T: entry 1 bad amount + entry 2 unknown handle → 422; reversed → 404 |
| J6 | Affordability is on NET balance after all transfers: a wallet may pass money on that it only receives within the batch (ada→bob 100, bob→cy 50 with bob at 0 is fine); any wallet net-negative → 409 `insufficient_funds` | T |
| J7 | All-or-nothing; failure claims no key and creates no payment | T + C |
| J8 | 201 `{settlement_id, committed_at, payments}` in input order; each member an ordinary payment with `settlement_id`, `request_id:null`, `created_at == committed_at` identical across members | T |
| J9 | Non-member payments expose `settlement_id: null` everywhere (payments, pay response, feed) | T |
| J10 | Members follow ordinary feed visibility (operator sees private members only if party); response still contains every member receipt | T |
| J11 | Replay → 200 original full response; survives export/import and operators survive import | T |

## Recorded decisions (spec silent or ambiguous)
1. Check order on idempotent writes: 401 → body must parse as a JSON object (else 400) → key absent/empty 400, >255 chars 422 → claimed-key resolution → field validation → resource checks. Only 2xx outcomes claim a key.
2. Wrong JSON type of a string/array field (`to_handle`, `payer_handle`, `participant_handles` or its elements, `email`, `password`, `display_name`, entry `from_handle`/`to_handle`) → 400; missing → 422. `amount`/`note`/`visibility` always 422. Batch shape of `transfers` → 422 (§11).
3. Field validation precedes resource lookups (422 before 404, self-target before unknown handle is moot since own handle exists); in settlements, entries are evaluated one at a time in input order, each fully (validation, then handles).
4. Emails compared exactly as given; handle uniqueness checked after email uniqueness.
5. Timestamps emitted in UTC as `+00:00`. Seeded payments/requests without timestamps get reset time, list order = fixture order reversed (last listed is newest), deterministic tie-break by insertion sequence everywhere.
6. Third-party access to an existing request's pay/decline/cancel → 403 (as the endpoint tables say), not 404.
