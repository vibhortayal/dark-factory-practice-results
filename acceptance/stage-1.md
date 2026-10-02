# Acceptance map: stage 1 (Pocketful: payments and settlements)

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (sha256 f5e4c644…c438a6).
Target folder: `stage-1/`. Every row must hold. "Harness" = supplied checks
(`harness run --track pocketful --stage 1`), which cover only part of the map; "Own" = a check the
Implementer and the Verifier each write from the specification against the running container.

## A. Delivery and runtime (§1, §2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds the service source, a `Dockerfile` and a `RUN.md` whose command builds and starts the service with no manual setup. No nested `.git`. | Own: follow RUN.md literally from a clean clone; `docker build` from clean cache |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; listens on `0.0.0.0:$PORT`, default 8080 when PORT unset. No compose needed. | Own: run with PORT set and unset |
| A3 | No outbound network at run time; all dependencies, init and seed inside the one container. | Harness `--mode isolated`; Own: `docker run --network none`-style internal network |
| A4 | `GET /health` → 200 `{"status":"ok"}` within 60 s of container start. | Harness; Own: time to first 200 |
| A5 | Works within 2 vCPU / 2 GiB, 50 requests in flight, each request ≤ 5 s (reset/export/import ≤ 10 s). | Own: run with `--cpus 2 --memory 2g`, 50-way bursts, record max latency |
| A6 | No request produces a 5xx, including under concurrent load and for malformed input. | Harness; Own: fuzz of bad bodies/params + bursts, assert no status ≥ 500 |
| A7 | Responses are `application/json; charset=utf-8` (204 has no body). | Own: header check on every endpoint incl. errors |
| A8 | Response timestamps are RFC 3339 with explicit offset (e.g. `+00:00`). | Own: regex on every `created_at` / `committed_at` |
| A9 | Unknown request-body fields are ignored; unknown query parameters are ignored. | Harness (partly); Own on every endpoint |
| A10 | IDs are opaque strings ≤ 64 chars (generated ids; fixture ids kept as given). | Own |
| A11 | Out of scope and absent: deposits, top-ups, withdrawals, cards, bank, directory/user search, admin balance endpoint, email verification, password reset, refresh tokens, role management. Nothing from stage 2+ (no UI, no stage-2/3/4 endpoints). | Own: review routes; harness stage-2 suite must not fully pass on `stage-1/` |
| A12 | No source code, API docs or schemas from existing products in this domain are used. | Review |

## B. Invariants (§1) at all times, incl. concurrency and retries

| Row | Requirement | Check |
|---|---|---|
| B1 | Sum of all wallet balances always equals the total seeded by the last reset (or imported). | Harness; Own: conservation after every burst |
| B2 | No balance negative, even transiently. | Own: 50 concurrent drains of one wallet → successes × amount ≤ balance, readers during burst never see < 0 |
| B3 | A payment request moves money at most once. | Own: 50 concurrent `pay` of one request with distinct keys → exactly one 201, rest 409 `request_not_pending`; same key → one 201, rest 200 |
| B4 | Amounts are exact integers; no float rounding; balances exact up to ±2^53. | Own: large-value fixtures (balances near 2^53), `minor_units` 0/2/3 |
| B5 | Debit and credit are one atomic step; a failed payment leaves no trace in either wallet or in the feed. | Own |
| B6 | Money cycles (A→B→C→A) under 50 in flight do not deadlock or 5xx; conservation holds. | Own |

## C. Reset and fixture (§3.3, §4)

| Row | Requirement | Check |
|---|---|---|
| C1 | `POST /_test/reset` with a fixture → 204, no auth; replaces ALL state (users, tokens, payments, requests, splits, settlements, idempotency records, operators). Subsequent requests see only the fixture. Repeated resets work. | Harness; Own: old tokens → 401 after reset, old keys are first-use again |
| C2 | Fixture fields: `currency`, `minor_units` (0, 2 or 3), `users[]` (`id,email,password,display_name,handle,balance`), `payments[]` (`id,from_user_id,to_user_id,amount,note,visibility`), `requests[]` (`id,requester_id,payer_id,amount,note,status`), optional `settlement_operator_ids` (default `[]`). `payments`/`requests` may be absent or empty. | Own |
| C3 | Seeded users can log in with the given password immediately; passwords stored only hashed. | Harness; Own: export contains no plaintext password |
| C4 | `balance` is final; seeded payments are NOT replayed against balances. | Own: fixture with payments, `/me` equals fixture balance |
| C5 | Negative `balance` in fixture → 422 `validation_failed`, previous state untouched. | Harness |
| C6 | Other invalid fixtures (missing required parts, `minor_units` not 0/2/3, duplicate id/handle/email, handle not matching `^[a-z0-9_]{1,20}$`, payment/request referring to unknown user, unknown operator id, bad status) → 422 `validation_failed` and no change; unparseable body → 400 `malformed_request`. Never 5xx. | Own |
| C7 | Seeded payments appear in `/activity` under the feed contract with `request_id: null`, `settlement_id: null`, a valid `created_at`; seeded requests appear in `/requests` for their two parties only, with given status, and a pending one can be paid/declined/cancelled; non-pending cannot be paid (409). | Harness; Own |
| C8 | Reset completes within 10 s for ordinary fixtures (e.g. 50 users — password hashing cost must allow it under 2 vCPU). | Own: timed reset with 50+ users |

## D. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code":..., "message":...}}`, including unknown routes (404 `not_found`) and wrong methods. | Own |
| D2 | 400 `malformed_request`: unparseable body; body that is not a JSON object; field of wrong JSON type (except the precedence rules in D4). | Harness; Own |
| D3 | 422 `validation_failed`: required field or query parameter missing; correct type but invalid format / out of range / too long. | Harness; Own |
| D4 | Precedence: invalid `amount` (strings, booleans, non-integral, null, out of range) → 422; non-string `note` incl. `null` → 422; any `visibility` other than `"public"`/`"private"` (any type, incl. `null`) → 422. Omission selects defaults. | Harness; Own |
| D5 | `amount` accepts integral JSON numbers `1000`, `1000.0`, `1e3`; rejects `1.5`, `"100"`, `true`, `0`, `-1`, `1000000001`. Max `1000000000` valid. | Harness; Own |
| D6 | Integer query params must be plain decimal digits: `1e9`, `4.0`, `+4`, `abc`, `-1`, empty → 422. | Harness; Own |
| D7 | `limit` 1..200 (default 50), `offset` ≥ 0 (default 0), else 422, on every endpoint that takes them (`/requests`, `/activity`). | Harness; Own |
| D8 | `Idempotency-Key` absent or empty → 400 `missing_idempotency_key`; longer than 255 chars → 422 `validation_failed`; exactly 255 valid. On all five write paths. | Harness; Own |
| D9 | 401 `unauthenticated` for missing, malformed or unknown bearer token on every authenticated endpoint. | Own |

## E. Authentication (§6) and handles (§4)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` `{email,password,display_name}` → 201 `{user_id, display_name, token}`; new balance 0; can receive money and be asked for money at once. | Harness |
| E2 | Handle derived from email: local part, lowercased, every char outside `[a-z0-9_]` → `_`, truncated to 20. `GET /me` shows it. No `handle` field in the signup body is honoured. | Harness; Own: `A.B+c@x.io` → `a_b_c`, 25-char local part |
| E3 | Email already registered → 409 `email_taken`. | Own |
| E4 | Derived handle already taken → 409 `handle_taken` and no account created (login with that email → 401). | Harness |
| E5 | Password shorter than 8 chars → 422; exactly 8 accepted. `email` not `local@domain` → 422. | Own |
| E6 | `POST /auth/login` → 200 same shape; wrong password or unknown email → 401 `unauthenticated`. | Own |
| E7 | Tokens never expire; several valid tokens per account; each login issues a working token; concurrent sessions. | Own |
| E8 | All endpoints except `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, `/auth/signup`, `/auth/login` require a bearer token. | Own |
| E9 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent; never plaintext (also not in export). | Review + export inspection |
| E10 | Handles unique, match `^[a-z0-9_]{1,20}$`, never change. | Own |

## F. Idempotency (§7): each of POST /payments, /requests, /requests/{id}/pay, /splits, /settlements

| Row | Requirement | Check |
|---|---|---|
| F1 | First use → normal response 201. | Harness |
| F2 | Replay (same user, method, path, same JSON value regardless of key order/whitespace) → 200 with body identical to the original as a JSON value; no state change; holds even after the resource later changes (request cancelled/paid). | Harness; Own on all five paths |
| F3 | Same key, different body → 409 `idempotency_key_reuse`. `{}` vs `{"visibility":"public"}` are different. | Harness |
| F4 | Key scoped to the authenticated user: two users, same key string, no interaction. | Harness |
| F5 | Same key + same body on a different path is a first use and succeeds. | Harness |
| F6 | Key whose original request failed with 4xx is treated as first use (failed requests claim no key). | Harness |
| F7 | N concurrent identical requests with an unused key: exactly one 201, others 200 with the same body, effect once. | Own: 50-way burst on each path |
| F8 | Once body parsed as JSON object and caller authenticated, a claimed key is resolved BEFORE field validation and current-resource checks: successful request then invalid body with same key → 409 `idempotency_key_reuse` (not 422); replay of a paid request's pay → 200 (not 409 `request_not_pending`). | Harness; Own |
| F9 | Body equality is by parsed JSON value including unknown fields (a body differing only in an ignored field is a different body → 409). | Own (decision D-7) |

## G. API (§8)

| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}`. | Harness |
| G2 | `POST /payments` `{to_handle, amount, note?, visibility?}` → 201 with `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, settlement_id:null, created_at`. Defaults `note:""`, `visibility:"public"`. | Harness |
| G3 | Payments errors: balance < amount → 409 `insufficient_funds` (paying exactly the balance succeeds); amount invalid → 422; own handle → 422 `self_payment`; note > 200 chars → 422 (200 accepted; length counted in Unicode code points — 200 emoji accepted, 201 rejected); bad visibility → 422; unknown handle → 404 `not_found`; missing `to_handle`/`amount` → 422. | Harness; Own |
| G4 | `note` stored and returned verbatim, byte for byte (no trim/escape/normalisation; Unicode, emoji, leading/trailing spaces, combining chars). | Harness; Own |
| G5 | `POST /requests` `{payer_handle, amount, note?}` → 201 with `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at`. Caller is requester. Payer balance NOT checked. | Harness |
| G6 | Requests errors: amount invalid → 422; own handle → 422 `self_request`; note > 200 → 422; unknown handle → 404. | Harness; Own |
| G7 | `POST /requests/{id}/pay` body `{visibility?}` (default public) → 201 with the created payment exactly as `POST /payments` returns one, `request_id` set; request becomes `paid` with `payment_id`; money moves payer → requester; payment note = request note. | Harness; Own |
| G8 | Pay errors: unknown request → 404; caller not payer → 403 `forbidden`; not pending → 409 `request_not_pending`; payer balance < amount → 409 `insufficient_funds` and nothing changes (request stays pending; payable later once funded, also with the same key). | Harness; Own |
| G9 | `POST /requests/{id}/decline`: payer only, no key needed; 200 with request `status:"declined"`; already declined → 200 current state; `paid`/`cancelled` → 409 `request_not_pending`; not the payer → 403; unknown → 404. | Harness; Own |
| G10 | `POST /requests/{id}/cancel`: requester only, no key; 200 `status:"cancelled"`; already cancelled → 200; `paid`/`declined` → 409; not the requester → 403; unknown → 404. | Harness; Own |
| G11 | Request lifecycle: `pending` then exactly one of `paid`/`declined`/`cancelled`; concurrent pay vs decline vs cancel → exactly one wins, money moves iff pay won. | Own: race bursts |
| G12 | `GET /requests`: only requests where caller is requester or payer; newest first by `created_at`; `direction` incoming/outgoing/absent; `status` pending/paid/declined/cancelled/absent; unknown value of either → 422; `limit`/`offset` per D7; `{requests:[...], has_more}` with `has_more` true iff items exist beyond the last returned. | Harness; Own |
| G13 | `POST /splits` `{amount, participant_handles, note?}` → 201 `{split_id, amount, currency, note, shares:[{handle,amount}], requests:[...], created_at}`; `shares` covers every participant incl. caller in given order and sums to `amount`; `requests` covers every participant except the caller in the same order, each `pending`, caller as requester, amount = that share, note = split note. Caller may be included or omitted (omitted: n = number of handles given, caller has no share). | Harness; Own |
| G14 | Splits errors: amount invalid → 422; `participant_handles` empty or with a duplicate → 422; note > 200 → 422; any unknown handle → 404; missing fields → 422. 1000 handles → 404 or 422, never 5xx. No balances checked. Split with only the caller → 201, one share, `requests: []`. | Harness; Own |
| G15 | `GET /activity` → `{payments:[...], has_more}`; a payment appears iff `visibility` is `public` OR caller is sender or receiver; newest first by `created_at`; `limit`/`offset` per D7; requests and splits never appear; request-only params (`direction`, `status`) ignored. | Harness; Own |
| G16 | Visibility is one value on the payment, identical for both parties; private payment visible to its sender and receiver, hidden from third parties (incl. settlement operators). | Harness; Own |
| G17 | Requests are never visible to third parties under any filter, nor actionable by them (403/404). | Harness |

## H. Rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| H1 | Shares are whole minor units, sum to `amount`, differ by at most 1, larger shares to the first participants in given order: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333,333,333; 5/5 → 1×5. | Harness; Own table |
| H2 | Different handle order moves the extra unit; a share of 0 is legal and still creates a request (amount 0, pending, payable: a 0-amount request pay moves 0 and succeeds). | Harness; Own |
| H3 | Splits are independent of each other; after paying all split requests, balances still sum to the seeded total. | Own |

## I. Export / import (§10)

| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{...}}`; atomic read-only snapshot (later writes do not change an already returned export; export under concurrent writes is internally consistent: balances sum to total). | Harness; Own |
| I2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically REPLACES state (not merge); repeating it restores the same state with no duplicates; previous destination data and credentials are gone. | Harness; Own |
| I3 | Import works in a different fresh container of the same image (no dependency on source process, files, volume, port, address). | Own: export from container A, import into container B |
| I4 | After import: accounts + password login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits' requests, operator permissions, settlement membership, ids and timestamps are all preserved exactly (feed and request lists equal before/after as JSON). Nothing regenerated; payments not replayed against balances. | Own: full before/after diff |
| I5 | After import: completed idempotent requests replay with 200 and the original body on all five paths; same key + different body → 409; keys of failed requests remain reusable (first use). | Own |
| I6 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, or invalid state → 422 `validation_failed`, destination unchanged. | Own |
| I7 | Reset clears everything incl. imported state. Export/import each ≤ 10 s. | Own |

## J. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| J1 | Fixture `settlement_operator_ids` (default `[]`) names operators. `POST /settlements`: no token → 401; non-operator → 403 `forbidden`; key required (D8). | Harness; Own |
| J2 | Body `{transfers:[{from_handle,to_handle,amount,note?,visibility?}]}` with 1..32 entries; operator may move money between any wallets (not only their own). 32 accepted; 0 or 33, missing/non-array `transfers`, non-object entry → 422 `validation_failed`. | Own |
| J3 | Each entry uses payment rules: amount 1..1e9 integral else 422; note ≤ 200 string else 422; visibility public/private else 422; defaults `""`/`public`; unknown handle → 404; `from_handle == to_handle` → 422 `self_payment`; unknown fields ignored. Entry errors are reported in input order (first bad entry decides) and before `insufficient_funds`. | Own |
| J4 | Affordable iff every wallet's balance after ALL incoming and outgoing transfers is ≥ 0 (net, not sequential: A(0)→B 100 together with B→A 100 is affordable). Otherwise 409 `insufficient_funds`. | Harness; Own |
| J5 | All-or-nothing: on any failure no payment, no balance change, no key claimed (key reusable as first use). | Own |
| J6 | 201 `{settlement_id, committed_at, payments:[...]}` in input order; each member is an ordinary payment (same shape as G2) with `settlement_id` set, `request_id: null`, `created_at` identical across members and equal to `committed_at`. Non-member payments expose `settlement_id: null` everywhere (payments, pay, activity). | Harness; Own |
| J7 | Members follow ordinary feed visibility (operator sees a private member only if party to it; parties see theirs). Operator permission gives no access to others' requests or private activity. | Own |
| J8 | Replay → 200 with the original complete response; concurrent identical → one 201; concurrent different settlements under 50 in flight conserve money and never go negative. | Own |
| J9 | Reset/import preserve operator permissions, original payments, requests, settlement membership and retry responses (see I4/I5). | Own |

## Decisions on points the specification leaves open (record; change only via the Architect)

- D-1 Check order on idempotent write paths: (1) auth → 401; (2) `Idempotency-Key` absent/empty → 400, > 255 → 422; (3) body parse / not an object → 400; (4) claimed key → replay 200 or 409 reuse; (5) field type/validation → 400/422; (6) resource checks: 404 unknown handle/request → 403 forbidden → 422 `self_payment`/`self_request` → 409 `request_not_pending` → 409 `insufficient_funds`. Reason: §7 fixes (4) after auth+parse and before (5)/(6); §11 puts entry errors before insufficient funds; the rest is the least surprising order. For `/settlements`, the operator check (403) comes right after auth (§11: "requires an operator").
- D-2 A handle string that does not match the handle pattern (`"ADA"`, `"@ada"`, `""`) is treated as "no user has that handle" → 404 `not_found` (supplied checks accept 404 or 422). A handle field of the wrong JSON type → 400 `malformed_request`.
- D-3 `participant_handles` not an array, or containing a non-string → 400 `malformed_request` (wrong JSON type, §5); empty or duplicate → 422. Duplicate check precedes the unknown-handle check.
- D-4 Settlement "malformed batch shape" (422) = `transfers` missing, not an array, length outside 1..32, or an element that is not an object. A `from_handle`/`to_handle` of the wrong JSON type inside an entry → 400; missing → 422.
- D-5 A request addressed to a third party's request id (caller is neither payer nor requester): 403 `forbidden` (the tables say "not the payer/requester is 403"; supplied checks accept 403 or 404).
- D-6 Emails are compared exactly as given (no case folding stated). Signup order: validation (422) → `email_taken` → `handle_taken`. `email` valid iff exactly one `@` with non-empty local part and non-empty domain. `display_name` is a required string.
- D-7 Idempotency body equality is by parsed JSON value of the whole body, unknown fields included; numbers compare by numeric value (`1000` = `1e3`).
- D-8 Note length is counted in Unicode code points (200 emoji accepted per supplied checks).
- D-9 Seeded payments and requests have no timestamp in the fixture: the service assigns `created_at` at reset, keeping fixture array order as oldest → newest (strictly increasing or tie-broken by insertion sequence so listing is deterministic). All lists sort by `created_at` descending with insertion sequence as tie-break (newest first).
- D-10 Every payment object carries `settlement_id` (null for non-members) (§11 "nonmembers expose null for that field").
- D-11 A 0-amount request (zero share) is payable: pay succeeds with a 0-amount payment, request becomes `paid`. Reason: §9 calls the request legal; nothing excludes paying it; "amount below 1" rules apply to request bodies, not to pay.
