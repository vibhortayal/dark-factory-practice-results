# Acceptance map — pocketful stage 1

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (§ numbers below are that file's).
"Supplied" = covered at least partly by `harness run --stage 1`. "Own" = needs a test written from
the spec by the Implementer and an independent check by the Verifier. Every row needs both a
result from the Implementer's self-check and from the Verifier.

## Invariants (§1)

| Row | Requirement | Check |
|---|---|---|
| I1 | Sum of all wallet balances always equals the total seeded by the last reset (or imported state), incl. under concurrency and retries | Supplied (conservation) + Own: 50 in-flight mixed writes (payments, pays, settlements), then sum `GET /me` of every user |
| I2 | No balance negative, even transiently | Own: N concurrent payments draining one wallet; successes × amount ≤ start balance; every `/me` read during the burst ≥ 0 |
| I3 | A payment request moves money at most once | Own: concurrent `pay` of one request with different keys → exactly one 201, others 409 `request_not_pending`; same key → one 201, rest 200 |
| I4 | Amounts are exact integers; no float rounding; balances within ±2^53 exact | Own: amounts at 1000000000, JSON `1000.0`/`1e3` accepted, response amounts are JSON integers |

## Delivery (§2)

| Row | Requirement | Check |
|---|---|---|
| D1 | `stage-1/Dockerfile` builds the service; `stage-1/RUN.md` has one command that builds and starts with no manual setup | `docker build` from clean; follow RUN.md literally |
| D2 | Image runs alone with `-e PORT=<port>` + port mapping; no compose needed; no outbound network at run time; all deps/seed inside the image | Supplied isolated mode + Own: `docker run --network none`-equivalent / isolated harness run |
| D3 | Within 2 vCPU, 2 GiB; first healthy response ≤ 60 s; 50 concurrent in flight; each request ≤ 5 s (reset/export/import ≤ 10 s) | Own: `docker run --cpus 2 --memory 2g`, time to health, 50-way burst, max latency |
| D4 | State is ephemeral; nothing required to survive restart; no nested `.git`, no symlinks/submodules in `stage-1/` | Inspect folder |
| D5 | Stage 1 only: no stage-2+ surface (no UI screens, no `/authorizations`, etc.) | Inspect routes; harness prints `claimed stage: 1` |

## Runtime contract (§3)

| Row | Requirement | Check |
|---|---|---|
| R1 | Listens on `0.0.0.0:$PORT`, default 8080 | Own: run with and without `PORT` |
| R2 | `GET /health` → 200 `{"status":"ok"}`, no auth | Supplied/Own |
| R3 | `POST /_test/reset` with fixture → 204, no body, no auth; replaces ALL state (users, tokens, payments, requests, splits, idempotency records, operators); repeated resets work; old tokens stop working | Own: reset twice, old token → 401, old key reusable |
| R4 | Responses are `application/json; charset=utf-8`; timestamps RFC 3339 with explicit offset (e.g. `+00:00`) | Own: header and regex check on every `created_at`/`committed_at` |
| R5 | Unknown request-body fields ignored; unknown query parameters ignored | Supplied + Own on every endpoint |
| R6 | IDs opaque strings ≤ 64 chars; seeded ids kept as given | Own |

## Model and fixture (§4)

| Row | Requirement | Check |
|---|---|---|
| M1 | One currency from fixture; `minor_units` 0, 2 or 3 (EUR/JPY/BHD); `/me` and payments report it | Supplied (minor_units 0 and 3) |
| M2 | Amount must be integral numeric: `1000`, `1000.0`, `1e3` valid and equal; booleans, strings, `1.5`, null → 422 | Supplied + Own |
| M3 | Handle unique, `^[a-z0-9_]{1,20}$`, immutable; seeded users keep fixture handle | Own |
| M4 | Signup handle derived: email local part → lowercase → every char outside `[a-z0-9_]` becomes `_` → truncate to 20 | Supplied + Own (`A.B+c@x` → `a_b_c`, 25-char local part) |
| M5 | New users start with balance 0 and can immediately receive money and be asked for money | Supplied |
| M6 | Request lifecycle: `pending` → exactly one of `paid`/`declined`/`cancelled`; only payer pays/declines; only requester cancels | Supplied + Own |
| M7 | Request may exceed payer balance: created `pending`; pay while short → 409 `insufficient_funds`, nothing changes; payable later once funded | Supplied |
| M8 | Visibility is one value on the payment, chosen by the payer; requests carry none | Own |
| M9 | Feed rule: payment visible iff `public` OR caller is sender or receiver; nothing else. `private` visible to both parties, hidden from third parties | Supplied + Own (incl. operator not seeing others' private items) |
| M10 | Requests never in `/activity`; `GET /requests` only where caller is requester or payer; a split is not a feed item | Supplied |
| M11 | Seeded users can log in immediately with fixture password | Supplied |
| M12 | Fixture `balance` is final: seeded payments are NOT replayed against balances; seeded payments and requests are readable through `/activity` and `/requests` with all fields of the ordinary shape | Supplied + Own |
| M13 | Fixture with any `balance` < 0 → reset returns 422 `validation_failed` and changes nothing | Supplied |
| M14 | Fixture optional parts: `payments`, `requests`, `settlement_operator_ids` (default `[]`) may be absent; seeded request `status` may be any of the four | Own |

## Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| E1 | Every 4xx/5xx body is `{"error":{"code","message"}}`, incl. unknown routes (404 `not_found`) and wrong method | Own |
| E2 | 400 `malformed_request`: unparseable body, or a field of the wrong JSON type (other than the amount/note/visibility exceptions) e.g. `to_handle: 5`, body that is a JSON array | Supplied + Own |
| E3 | 400 `missing_idempotency_key` when header absent or empty on the five paths | Supplied + Own (all five) |
| E4 | 401 `unauthenticated`: missing, malformed (`Basic x`, `Bearer`), or unknown token — on every authenticated endpoint | Own |
| E5 | 403 `forbidden`, 404 `not_found` as per endpoint | Supplied + Own |
| E6 | 409 `idempotency_key_reuse` | Supplied |
| E7 | 422 `validation_failed`: missing required field / query param, bad format, out of range, over length | Supplied + Own |
| E8 | Field precedence: invalid `amount` (incl. strings, booleans), non-string `note` (incl. `null`), any `visibility` other than `public`/`private` (any JSON type) → 422, not 400. Omission selects defaults | Supplied + Own |
| E9 | Integer query parameters are plain decimal digits: `1e9`, `4.0`, `+4`, `-1`, empty, `abc` → 422 | Supplied + Own |
| E10 | `Idempotency-Key` 1..255 chars, longer → 422; `limit` 1..200 else 422; `offset` ≥ 0 else 422 — on every endpoint that takes them | Supplied + Own (255 ok, 256 → 422; limit 0, 201; offset -1) |
| E11 | No 5xx ever, including under 50 concurrent requests and hostile-but-ordinary input | Own: fuzz table of bad bodies on each endpoint + burst |

## Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| A1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; body has no `handle` | Supplied |
| A2 | `POST /auth/login` → 200 `{user_id, display_name, token}` | Supplied |
| A3 | Email already registered → 409 `email_taken` | Own |
| A4 | Password shorter than 8 chars → 422; `email` not `local@domain` → 422 | Own |
| A5 | Wrong password or unknown email → 401 `unauthenticated` | Own |
| A6 | Derived handle already taken → 409 `handle_taken`, no account created (login with that email → 401, email still free) | Supplied + Own |
| A7 | All endpoints except `/health`, `/_test/*`, signup, login require a bearer token | Own |
| A8 | Tokens never expire; multiple valid tokens per account at once (each login issues a new one, old ones stay valid) | Own |
| A9 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent; never plaintext (incl. in export state) | Inspect code + export |

## Idempotency (§7)

| Row | Requirement | Check |
|---|---|---|
| K1 | Applies independently to `POST /payments`, `/requests`, `/requests/{id}/pay`, `/splits`, `/settlements` | Own on all five |
| K2 | Key scoped to authenticated user; same key by two users does not interact | Supplied |
| K3 | Replay = same user, method, path, body; same key + same body on a different path is a first use and succeeds | Supplied |
| K4 | First use → 201; replay → 200 with body equal as a JSON value to the original | Supplied + Own on all five |
| K5 | Same key, different body → 409 `idempotency_key_reuse`; body equality is by parsed JSON value (key order/whitespace irrelevant) | Supplied + Own (reordered keys = replay) |
| K6 | Key whose original request failed with 4xx is not claimed: next use is a first use | Supplied |
| K7 | Concurrent identical requests on an unused key: exactly one 201, the others 200 same body, effect once | Own: 20 concurrent identical on each of the five paths |
| K8 | Successful replay returns the original response even after the resource changed (e.g. request later paid/cancelled) and makes no state change | Own |
| K9 | Once body parsed as a JSON object and caller authenticated, a claimed key is resolved BEFORE field validation and resource checks: success then same key with invalid body → 409 `idempotency_key_reuse`; replay of pay on a now-`paid` request → 200 not 409 `request_not_pending` | Supplied + Own |

## API (§8)

| Row | Requirement | Check |
|---|---|---|
| P1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}` | Supplied |
| P2 | `POST /payments` 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, created_at` (+ `settlement_id:null`, §11) | Supplied + Own |
| P3 | `note` default `""`, `visibility` default `"public"` | Supplied |
| P4 | Balance below amount → 409 `insufficient_funds`; paying exactly the balance succeeds; failed payment leaves no trace in either wallet or feed | Supplied |
| P5 | amount < 1, > 1000000000, non-integer → 422 | Supplied |
| P6 | `to_handle` is caller's own → 422 `self_payment` | Supplied |
| P7 | `note` > 200 characters → 422; exactly 200 (incl. 200 emoji, counted as characters not bytes) accepted | Supplied |
| P8 | Unknown handle → 404 `not_found` | Supplied |
| P9 | Debit and credit atomic | I1/I2 burst |
| P10 | `note` stored and returned verbatim: no trim, no escaping, no normalisation; Unicode/emoji byte-for-byte | Supplied + Own (leading/trailing spaces, `<b>`, combining chars, NFD) |
| Q1 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at` | Supplied |
| Q2 | amount rules → 422; `payer_handle` own → 422 `self_request`; note > 200 → 422; unknown handle → 404; payer balance NOT checked | Supplied |
| Q3 | `POST /requests/{id}/pay`: body `visibility` only (optional, default public); 201 with payment in `/payments` shape with `request_id` set; request becomes `paid` with `payment_id` | Supplied |
| Q4 | pay errors: not pending → 409 `request_not_pending`; payer short → 409 `insufficient_funds`; caller not payer → 403; unknown → 404 | Supplied |
| Q5 | pay replay: `{}` vs `{"visibility":"public"}` are different bodies → 409 reuse; successful replay → 200 original payment, no extra money | Supplied |
| Q6 | `POST /requests/{id}/decline`: payer only, no key; 200 request `declined`; already declined → 200; `paid`/`cancelled` → 409 `request_not_pending`; not payer → 403; unknown → 404 | Supplied + Own |
| Q7 | `POST /requests/{id}/cancel`: requester only, no key; 200 request `cancelled`; already cancelled → 200; `paid`/`declined` → 409; not requester → 403; unknown → 404 | Supplied + Own |
| Q8 | `GET /requests` → `{requests, has_more}`; only caller's; newest first by `created_at`; `direction` incoming/outgoing/absent; `status` one of four or absent; unknown value → 422; limit default 50, offset default 0; `has_more` true iff items exist beyond the last returned | Supplied + Own (paging across exactly limit items → false) |
| S1 | `POST /splits` 201: `split_id, amount, currency, note, shares[{handle,amount}], requests[...], created_at`; shares for every participant incl. caller in given order, sum = amount; one `pending` request per participant except caller, same order, caller as requester | Supplied |
| S2 | Caller may be in `participant_handles` or omitted (omitted: caller gets no share; n = number of handles) | Own |
| S3 | amount rules → 422; empty list or duplicate handle → 422; note > 200 → 422; any unknown handle → 404; no balance checks | Supplied |
| S4 | Only-the-caller split valid: one share, `requests: []` | Supplied |
| F1 | `GET /activity` → `{payments, has_more}`, feed rule M9, newest first, limit/offset exactly as `/requests`; request-only params ignored | Supplied |

## Money and rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| N1 | Shares whole units, sum = amount, differ by ≤ 1; larger shares to the first handles: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333×3; 5/5 → 1×5 | Supplied + Own (whole table) |
| N2 | Different handle order moves the extra unit; a 0 share is legal and still creates a request (amount 0, payable as a 0 movement or at least not a 5xx) | Supplied + Own |
| N3 | Shares independent of earlier splits; after splits are paid in full, balances still sum to seeded total | Own |

## Export / import (§10)

| Row | Requirement | Check |
|---|---|---|
| X1 | `GET /_test/export` → 200 `{track:"pocketful", format_version:1, state:{...}}`, no auth, atomic read-only snapshot | Supplied + Own |
| X2 | `POST /_test/import` with that whole object → 204; atomic replacement, not merge; repeating it duplicates nothing; removes all previous destination data and credentials | Own: export A, reset to B, import A, compare a second export to the first |
| X3 | Unparseable JSON → 400 `malformed_request`; missing fields, wrong `track`/`format_version`, invalid `state` → 422 `validation_failed`; destination unchanged | Own |
| X4 | Preserved: accounts, password-hash login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits' requests, operator permissions, settlement membership, ids, timestamps; nothing regenerated or replayed against balances | Own: field-by-field compare of `/me`, `/activity`, `/requests` before and after |
| X5 | Completed idempotency records preserved: replay after import → 200 original body, different body → 409; keys of failed requests remain reusable | Own on all five paths |
| X6 | Import works in a fresh container with no dependency on source process, files, port (import into a second container of the same image) | Own |
| X7 | Reset after import clears everything, including imported state | Own |
| X8 | Export/import/reset ≤ 10 s | Own |

## Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| T1 | Fixture `settlement_operator_ids` (default `[]`) names operators; operator may settle across any wallets, but gains no access to others' requests or private activity | Supplied + Own |
| T2 | `POST /settlements`: no token → 401; authenticated non-operator → 403 `forbidden`; key required (400 if absent/empty) | Own |
| T3 | `transfers` is 1..32 objects `{from_handle, to_handle, amount, note?, visibility?}`; note default `""`, visibility default public; ordinary amount/note/visibility rules → 422; malformed batch shape (missing, not array, 0 or 33 entries, non-object entry) → 422 `validation_failed`; unknown fields ignored | Own (boundaries 1, 32, 33) |
| T4 | Unknown handle → 404; `from_handle == to_handle` → 422 `self_payment`; entry errors reported in input order (first failing entry decides), and before insufficient funds | Own |
| T5 | Affordable iff every wallet's balance after ALL transfers is ≥ 0 (net, so a chain funded by an incoming transfer in the same batch is fine); otherwise 409 `insufficient_funds` | Supplied + Own (ada→bob 100, bob→cy 3000 with bob at 2500 → net check) |
| T6 | All-or-nothing; failed validation/funds claims no key, creates no payment | Own: balances and `/activity` unchanged, key reusable |
| T7 | 201 `{settlement_id, committed_at, payments[...]}` in input order; each member an ordinary payment with `settlement_id` set, `request_id` null, `created_at` == `committed_at` identical across members | Supplied + Own |
| T8 | Non-member payments (direct, request-paid, seeded) expose `settlement_id: null` everywhere a payment is returned | Own |
| T9 | Members follow ordinary feed visibility; response still contains every member's receipt | Own |
| T10 | Replay → 200 with original complete response; concurrent identical → one 201 | Own |
| T11 | Reset/import preserve operator permissions, membership and retry responses (X4/X5) | Own |

## Recorded decisions (Architect, from the spec text)

1. Check order on idempotent paths: authenticate (401) → for `/settlements` operator check (403) →
   `Idempotency-Key` present (400) and length (422) → body parses as a JSON object (400) → claimed key
   resolved (200 replay / 409 reuse) → field validation → resource and balance checks. Reason: §7
   fixes the last three steps; §5/§6 make authentication the outermost gate.
2. Idempotency record identity is (user, method, path, key). Reason: §7 "same key with the same
   body on a different path is a different request … must succeed normally".
3. `pay` check order after key resolution: 404 unknown → 403 not payer → 409 `request_not_pending`
   → 409 `insufficient_funds`. Reason: table order in §8 read from most to least fundamental; a
   non-party must not learn status.
4. Timestamps are emitted with `+00:00`. Reason: §3.4 "explicit offset" and every example.
5. Note length counts Unicode code points, not bytes or UTF-16 units. Reason: §8 "200 characters",
   and 200 emoji must be accepted.
6. A handle value that is a string but matches no user (any content) is 404 `not_found`; a handle
   of the wrong JSON type is 400 `malformed_request`. Reason: §8 tables, §5 type rule.
7. Seeded payments/requests get server-assigned `created_at` at reset, ordered so that list order
   is deterministic. Reason: fixture carries no timestamps; §8 leaves same-second order open.
8. Anything else the spec leaves open is the Implementer's choice and must be listed in the
   handoff with its reason.
