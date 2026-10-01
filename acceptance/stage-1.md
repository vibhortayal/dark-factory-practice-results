# Acceptance map — Pocketful stage 1

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (kickoff checkout, read-only).
Target folder: `stage-1/`. Every row must hold for the revision under review.
"Check" says how the row is verified. `H` = supplied harness suite covers part of it;
`T` = Implementer's own automated test required; `V` = Verifier's independent probe required.
The supplied harness is a partial sample: a green harness run does not close a row marked T or V.

## A. Delivery and runtime (§2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds source, a `Dockerfile` and a `RUN.md` whose command builds and starts the service with no manual setup. No `.git`, submodule or symlink inside the folder. | V: follow RUN.md verbatim from a clean clone; `find stage-1 -name .git -o -type l` empty |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose needed; all dependencies, init and seed inside the single container. | H (harness builds and starts image); V: `docker run -e PORT=9123 -p 9123:9123` |
| A3 | No outbound network at run time (build may fetch). | H `--mode isolated`; V: `docker run --network none` + exec health, or isolated run |
| A4 | Listens on `0.0.0.0`, port from `PORT`, default `8080` when unset. | V: run without `-e PORT`, map 8080 |
| A5 | `GET /health` → 200 `{"status":"ok"}` within 60 s of start, once the store can serve. | H; V: time from `docker run` to first 200 |
| A6 | Works within 2 vCPU / 2 GiB, 50 requests in flight, each request < 5 s (reset/export/import < 10 s). | H isolated; T/V: 50-way concurrent load, no timeouts, no 5xx |
| A7 | State is ephemeral; nothing requires a volume or survives-restart behaviour. | V: inspect Dockerfile/RUN.md |
| A8 | Responses are `application/json; charset=utf-8` (204 has no body). Requests are JSON. | T; V: header check on 2xx and 4xx |
| A9 | Timestamps are RFC 3339 with explicit offset (e.g. `+00:00`), never naive. | T; V: regex on `created_at`, `committed_at` |
| A10 | Unknown body fields ignored; unknown query parameters ignored (never an error). | H; T on every write path and both list endpoints |
| A11 | IDs are opaque strings ≤ 64 chars. Seeded ids are kept exactly as given in the fixture. | T; V |
| A12 | No request yields 5xx, including malformed input and concurrent load. Unknown routes/methods return a 4xx with the §5 error body. | H; T fuzz of types on every field; V |
| A13 | Implementation is original: no source, API docs or schemas copied from existing products. | V: review |
| A14 | Stage-1 folder does not implement stage 2 (harness overshoot line for suite 2 reads fail; `claimed stage: 1`). | H: harness output |

## B. Reset and fixture (§3.3, §4 fixture format)

| Row | Requirement | Check |
|---|---|---|
| B1 | `POST /_test/reset` with a fixture → 204, no auth needed; all state replaced (users, tokens, payments, requests, splits, settlements, idempotency records, operators). | H; T: token from before reset is 401 after |
| B2 | Repeated resets supported; after 204 only the fixture is visible. | H; T |
| B3 | Fixture `currency`, `minor_units` (0, 2 or 3; EUR/JPY/BHD) drive `/me` and every `currency` field. | H; T for all three |
| B4 | Seeded users log in immediately with the given password; id, email, display_name, handle, balance taken verbatim. | H; T |
| B5 | Seeded `balance` is final; seeded payments are NOT replayed against balances. | H; T: balances after reset equal fixture values |
| B6 | Seeded payments appear in `/activity` under the feed contract with their id, parties, amount, note, visibility; `request_id` null unless linked, `settlement_id` null. | H; T |
| B7 | Seeded requests keep id, parties, amount, note, status; visible to both parties only; a seeded `pending` one is payable, a non-pending one gives 409 `request_not_pending`. | H; T |
| B8 | A negative `balance` in the fixture → 422 `validation_failed` and the previous state is unchanged (old tokens, balances still valid). | H; T |
| B9 | `payments`, `requests`, `settlement_operator_ids` are optional in the fixture (default `[]`). | T |
| B10 | Unparseable reset body → 400 `malformed_request`; structurally invalid fixture → 4xx with §5 body, never 5xx, state unchanged. | T; V |
| B11 | Sum of balances always equals the total seeded by the last reset (invariant 1). | H (`conservation`); T after every scenario and under load |

## C. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| C1 | Every 4xx/5xx body is `{"error":{"code":...,"message":...}}`. | T: asserted in every negative test |
| C2 | 400 `malformed_request`: unparseable body, body that is not a JSON object, or a field of the wrong JSON type (except the endpoint-specific 422 rules in C6). | H; T |
| C3 | 400 `missing_idempotency_key`: header absent or empty on the five idempotent paths. | H; T all five |
| C4 | 401 `unauthenticated`: missing, malformed or unknown bearer token on every authenticated endpoint. | T on every endpoint; V |
| C5 | 422 `validation_failed`: missing required field or query parameter; correct type but bad format / out of range / too long. | H; T |
| C6 | Field rules that override C2: invalid `amount` incl. strings and booleans → 422; non-string `note` incl. `null` → 422; any `visibility` other than `public`/`private` (any type, incl. `null`) → 422. Omission selects defaults. | H; T matrix on payments, requests, pay, splits, settlements |
| C7 | Integer query parameters must be plain decimal digits: `1e9`, `4.0`, `+4`, `-1`, empty, `abc` → 422. | H; T |
| C8 | `Idempotency-Key` longer than 255 characters → 422 `validation_failed` (1..255 valid; 255 accepted, 256 rejected). | H; T boundary |
| C9 | `limit` 1..200 (0, 201 → 422), `offset` ≥ 0, on `/requests` and `/activity`. | H; T boundary 1, 200, 0, 201 |
| C10 | 403 `forbidden`, 404 `not_found`, 409 `idempotency_key_reuse` used as specified per endpoint. | rows E–J |

## D. Authentication and users (§4 users, §6)

| Row | Requirement | Check |
|---|---|---|
| D1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; new balance 0; can immediately receive money and be requested. | H; T |
| D2 | Handle derived from email: local part, lowercased, every char outside `[a-z0-9_]` → `_`, truncated to 20. Handle is unique, immutable. | H; T: `Foo.Bar+x@…` → `foo_bar_x`; 25-char local part truncated |
| D3 | Email already registered → 409 `email_taken`. | T |
| D4 | Derived handle already taken → 409 `handle_taken`, no account created (login with that email fails 401). | H; T |
| D5 | Password shorter than 8 characters → 422; exactly 8 accepted. | T |
| D6 | `email` not `local@domain` → 422. Missing fields → 422. Wrong JSON types → 400. | T |
| D7 | `POST /auth/login` → 200 `{user_id, display_name, token}`; wrong password or unknown email → 401 `unauthenticated`. | H; T |
| D8 | Tokens never expire; multiple tokens per account valid concurrently (two logins → both tokens work). | T |
| D9 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent; never plaintext (also inside export state). | V: source + export inspection |
| D10 | Every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login` requires `Authorization: Bearer <token>`. | T; V |
| D11 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}`. | H; T |
| D12 | Concurrent signups with the same email / same derived handle: exactly one 201. | T |

## E. Idempotency (§7) — applies independently to each of the five paths

Paths: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`.

| Row | Requirement | Check |
|---|---|---|
| E1 | First use → normal response, 201. | H; T ×5 |
| E2 | Replay (same user, method, path, JSON-equal body) → 200 with a body equal as a JSON value to the original; no further state change. | H; T ×5 |
| E3 | Same key, different body (same user, same path) → 409 `idempotency_key_reuse`. | H; T ×5 |
| E4 | "Same body" is JSON-value equality: key order and whitespace irrelevant; `{}` ≠ `{"visibility":"public"}`. | H; T |
| E5 | Key scoped to the authenticated user: two users, same key string, no interaction. | H; T |
| E6 | Same key + same body on a different path (incl. `/requests/a/pay` vs `/requests/b/pay`, `/payments` vs `/requests`) is a first use and succeeds. | H; T |
| E7 | A key whose original request failed with 4xx is treated as first use (not recorded); e.g. insufficient funds then funded → 201. | H; T |
| E8 | Concurrent identical requests with an unused key: exactly one 201, the rest 200 with the same body, effect applied once. | T: 20 parallel ×5 paths; V |
| E9 | Replay returns the original response even after the resource changed (request later paid/cancelled, etc.). | H; T |
| E10 | Order: auth (401) → key header present (400) → key length (422) → body parses as JSON object (400) → claimed-key resolution (200 / 409) → field validation and resource checks. So a claimed key with a now-invalid body → 409 `idempotency_key_reuse`, and a pay replay on an already-paid request → 200, never `request_not_pending`. | H; T |
| E11 | Failed validation or failed funds claims no key and leaves no payment, request, split or settlement. | T |

## F. Payments (§8 `POST /payments`)

| Row | Requirement | Check |
|---|---|---|
| F1 | 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id (null), settlement_id (null), created_at`. | H; T exact key set |
| F2 | `note` optional default `""`; `visibility` optional default `"public"`. | H; T |
| F3 | Balance below `amount` → 409 `insufficient_funds`, nothing changes; paying exactly the balance succeeds (balance → 0). | H; T |
| F4 | `amount` < 1, > 1000000000, non-integral (`10.5`), string, boolean, null → 422. `1000`, `1000.0`, `1e3` accepted and returned as integer. `1000000000` accepted. | H; T matrix |
| F5 | `to_handle` equal to caller's handle → 422 `self_payment`. | H; T |
| F6 | `note` > 200 characters → 422; exactly 200 accepted; length counted in characters (200 emoji accepted). | H; T |
| F7 | `note` stored and returned verbatim, byte for byte (unicode, emoji, whitespace, HTML-like text; no trimming or escaping). | H; T |
| F8 | Unknown `to_handle` → 404 `not_found`. Missing `to_handle`/`amount` → 422. `to_handle` of wrong JSON type → 400. | H; T |
| F9 | Debit and credit are one atomic step; no negative balance, even transiently (invariant 2). | H (ten clients, one wallet); T: 50 parallel overspend, exactly floor(balance/amount) succeed |
| F10 | Opposing concurrent transfers (A→B and B→A, many pairs) neither deadlock nor lose money. | T; V |

## G. Requests (§4, §8)

| Row | Requirement | Check |
|---|---|---|
| G1 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at`. Caller is requester. | H; T exact key set |
| G2 | Amount / note rules as F4, F6, F7; `note` default `""`. | H; T |
| G3 | `payer_handle` is caller → 422 `self_request`; unknown handle → 404. | H; T |
| G4 | Payer's balance is not checked at creation; request above the balance is created `pending`. | H; T |
| G5 | `POST /requests/{id}/pay` by the payer → 201 with the payment (as F1) with `request_id` set; request becomes `paid` with `payment_id`; money moves payer → requester. | H; T |
| G6 | Pay body carries optional `visibility` only (default `public`); visibility is the payer's choice and lives on the payment. | H; T |
| G7 | Pay: unknown request → 404; caller not the payer (requester or third party) → 403 `forbidden`; not `pending` → 409 `request_not_pending`; balance short → 409 `insufficient_funds` and the request stays `pending` and becomes payable once funded. | H; T |
| G8 | A request moves money at most once (invariant 3): concurrent pays with different keys → exactly one 201, others 409 `request_not_pending`; concurrent pay vs decline/cancel → exactly one wins. | T; V |
| G9 | `POST /requests/{id}/decline`: payer only, no key needed, 200 with request `declined`; already declined → 200; `paid`/`cancelled` → 409 `request_not_pending`; not payer → 403; unknown → 404. | H; T |
| G10 | `POST /requests/{id}/cancel`: requester only, no key needed, 200 with request `cancelled`; already cancelled → 200; `paid`/`declined` → 409; not requester → 403; unknown → 404. | H; T |
| G11 | `GET /requests`: only requests where caller is requester or payer; newest first by `created_at`; body `{requests, has_more}`. | H; T |
| G12 | `direction` = `incoming` (caller is payer) / `outgoing` (caller is requester) / absent = both; `status` one of the four or absent; unknown value of either → 422. | H; T |
| G13 | `limit` default 50, 1..200; `offset` default 0, ≥ 0; `has_more` true iff items exist beyond the last returned. | H; T |
| G14 | A request never appears in `/activity` and never in a third party's `/requests` under any filter; operator status grants no access to others' requests. | H; T |

## H. Splits (§8, §9)

| Row | Requirement | Check |
|---|---|---|
| H1 | `POST /splits` 201 body: `split_id, amount, currency, note, shares[{handle, amount}], requests[...], created_at`. | H; T |
| H2 | Caller may be in `participant_handles` or omitted; n = number of handles given. One `pending` request per participant except the caller, caller as requester, amount = that participant's share, note = split note. | H; T |
| H3 | `shares` covers every participant incl. caller, in input order, sums to `amount`; `requests` covers all but the caller, same order. | H; T |
| H4 | Equal-split rule: base = amount div n, first (amount mod n) participants get +1. Table: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333×3; 5/5 → 1×5. | H; T all five |
| H5 | Different handle order moves the extra unit; a share of 0 is legal and still creates a request. | H; T |
| H6 | Only participant is the caller → valid, one share, `"requests": []`. | H; T |
| H7 | Empty `participant_handles` or a duplicate handle → 422; any unknown handle → 404; missing field → 422; not an array / non-string member → 400 or 422, never 5xx. Amount/note rules as F4, F6. | H; T |
| H8 | No balance is checked by a split. Very large lists (1000 handles) are validated, not crashed. | H; T |
| H9 | Split creation is atomic: either all requests exist or none (e.g. unknown handle in last position leaves no requests). | T |
| H10 | After splits are paid in full, balances still sum to the seeded total. | T |

## I. Activity feed (§4 feed contract, §8)

| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /activity` → `{payments, has_more}`, payments only, newest first by `created_at`. | H; T |
| I2 | A payment is visible iff `visibility` is `public` OR caller is sender or receiver. No other rule. | H; T: third party sees public, not private; both parties see private |
| I3 | Visibility is one value seen identically by all viewers of that payment. | T |
| I4 | `limit`/`offset`/`has_more` exactly as `/requests`; parameters such as `direction`/`status` are ignored here. | H; T |
| I5 | Operators get no extra visibility into private payments they are not party to. | T |
| I6 | Payments created by pay-request and by settlements appear under the same rule with `request_id` / `settlement_id` populated. | T |

## J. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| J1 | Fixture `settlement_operator_ids` (array of user ids, default `[]`) defines operators. | H; T |
| J2 | `POST /settlements`: no token → 401; authenticated non-operator → 403 `forbidden`; idempotency key required (400 when missing). | T |
| J3 | `transfers` is an array of 1..32 objects `{from_handle, to_handle, amount, note?, visibility?}`; not an array, 0 or 33 entries, missing, or non-object member → 422 `validation_failed`. 32 accepted. | T boundary |
| J4 | Each entry uses payment rules: amount (F4), note (F6, default `""`), visibility (default `public`); unknown handle → 404; `from_handle` == `to_handle` → 422 `self_payment`; unknown fields ignored. | T |
| J5 | Entry errors are reported in input order (first bad entry decides the error) and before insufficient funds. | T: entry 1 unaffordable + entry 2 unknown handle → 404 |
| J6 | Affordability is on the NET: every wallet's balance after all transfers ≥ 0. A chain ada→bob→cy where bob starts at 0 succeeds; otherwise 409 `insufficient_funds`. | T |
| J7 | All movements commit together or none; a failed settlement claims no key and creates no payment. | T; concurrent with ordinary payments keeps invariants B11/F9 |
| J8 | 201 body: `settlement_id, committed_at, payments` in input order. Each member is an ordinary payment object with `settlement_id` set, `request_id` null, `created_at` == `committed_at` for all members. | H; T |
| J9 | Every payment object everywhere carries `settlement_id` (null for non-members). | T |
| J10 | Members follow ordinary feed visibility; the settlement response still contains every member's receipt. | T |
| J11 | Replay → 200 with the original complete response (fifth idempotent path; rows E1–E11 apply). | T |
| J12 | Operator may move money between wallets they do not own, but gains no access to other users' requests or private activity. | T |

## K. Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| K1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{...}}`; atomic read-only snapshot. | H; T |
| K2 | `POST /_test/import` (no auth) with an unchanged export → 204; state atomically replaced (not merged); repeating the import duplicates nothing. | H; T |
| K3 | Import has no dependency on the source process/files/port: export from container A imports into fresh container B. | V: two containers |
| K4 | Preserved: accounts, hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits, settlement membership, operator permissions, ids, timestamps. Nothing regenerated; balances not re-derived by replay. | T: export → reset to other fixture → import → compare `/me`, `/activity`, `/requests`, old tokens |
| K5 | Completed idempotent request bodies and original responses preserved: replay after import → 200 original body; changed body → 409; no money moves. All five paths. | T |
| K6 | Failed-request keys remain reusable after import. | T |
| K7 | Import removes all previous destination data and credentials (pre-import tokens/users not in the export are gone). | T |
| K8 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, or invalid state → 422 `validation_failed`, destination unchanged. | T |
| K9 | Reset after import clears everything, including imported state. | T |
| K10 | Export/import/reset complete within 10 s on a populated state (thousands of records). | T/V timing |
| K11 | Export taken during concurrent writes is internally consistent (balances sum to seeded total inside the snapshot once imported). | T/V |

## Decisions recorded by the Architect

- D-1: caller who is neither party calling pay/decline/cancel on an existing request gets 403 `forbidden`
  (endpoint tables say "not the payer/requester → 403"; supplied checks accept 403 or 404).
- D-2: precedence on idempotent paths is the order in E10; missing key (400) is reported before body parsing.
- D-3: a JSON body that parses but is not an object is 400 `malformed_request`.
- D-4: wrong JSON type for fields not named in C6 (`to_handle`, `payer_handle`, `email`, `password`,
  `display_name`, `participant_handles` not an array) is 400; settlement batch shape problems are 422 per §11.
- D-5: precedence inside one request: field validation (422) → self-payment/self-request (422) →
  unknown handle (404) → state (409). In settlements the first entry in input order with any error decides.
