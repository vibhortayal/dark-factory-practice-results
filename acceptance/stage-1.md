# Acceptance map — Pocketful stage 1

Source: `dark-factory-wearedevs/pocketful/spec/stage-1.md` (complete). Target: `stage-1/`.
"Supplied" = harness suite (`python -m harness run --track pocketful --stage 1`), which samples
only part of the spec. "Own" = a test written from the spec by the Implementer (in `stage-1/`)
and independently by the Verifier. Every row must be checked; the supplied checks alone never
close a row.

## A. Delivery and runtime (§1, §2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` has a `Dockerfile` and a `RUN.md` whose command builds and starts the service with no manual setup | Clean `docker build`; follow RUN.md verbatim |
| A2 | Image runs alone with `-e PORT=<port>` + port mapping; no compose needed; listens on `0.0.0.0`; default port 8080 | `docker run` with and without PORT |
| A3 | No outbound network at run time; all deps, init, seed inside the image | Supplied run `--mode isolated`; `docker run --network none` smoke |
| A4 | `GET /health` → 200 `{"status":"ok"}` within 60 s of start | Timed start |
| A5 | Works within 2 vCPU / 2 GiB; 50 in-flight requests; each request < 5 s (reset/export/import < 10 s) | `docker run --cpus 2 --memory 2g`, 50-concurrent load, latency recorded |
| A6 | No request yields 5xx, including under concurrent load and for malformed input | Fuzz of bad bodies/headers + load run, count 5xx = 0 |
| A7 | Responses are `application/json; charset=utf-8`; timestamps RFC 3339 with explicit offset | Header + regex checks on every endpoint |
| A8 | Unknown body fields ignored; unknown query parameters ignored | Own, on each endpoint |
| A9 | IDs are opaque strings ≤ 64 chars (generated ids; seeded ids kept as given) | Own |
| A10 | Only HTTP API; no deposits/top-ups/withdrawals/admin balance endpoint; no later-stage features (stage-2+ spec endpoints absent) | Route listing vs. spec; Verifier step 5 |
| A11 | Code is split into small modules; RUN.md says where each part lives; no nested repo; folder self-contained | Read |

## B. Invariants (§1)

| Row | Requirement | Check |
|---|---|---|
| B1 | Sum of balances always equals the total seeded by the last reset — under concurrency and retries | Sum via `/me` for all users after concurrent payment/pay/settlement storms |
| B2 | No balance negative, even transiently | Concurrent overspend: N parallel payments from a wallet that affords k → exactly k succeed, rest 409, balance ≥ 0 |
| B3 | A request moves money at most once | Concurrent pay of one request with different keys → exactly one 201, others 409 `request_not_pending`; concurrent pay/decline/cancel races leave one terminal state |
| B4 | Amounts are exact integers; balances up to ±2^53 exact, no float rounding | Seed balances near 2^53, move 1 unit, exact compare |

## C. Reset and fixture (§3.3, §4)

| Row | Requirement | Check |
|---|---|---|
| C1 | `POST /_test/reset` → 204, no auth; replaces all state (users, tokens, payments, requests, splits, settlements, idempotency records, operators) | Reset twice with different fixtures; old tokens 401; old data gone |
| C2 | Seeded users log in immediately with the fixture password; `/me` shows seeded id, display_name, handle, balance, currency, minor_units | Supplied + own |
| C3 | `balance` is post-payment; seeded payments are not replayed | Balance equals fixture value exactly |
| C4 | Seeded payments appear in `/activity` under the feed rule with full payment shape (`request_id`, `settlement_id` null, handles, currency, `created_at`); seeded requests appear in `/requests` with given status | Own + supplied seeded-state tests |
| C5 | Negative fixture `balance` → 422 `validation_failed`, nothing changes (previous state intact) | Own |
| C6 | `minor_units` 0, 2 or 3 (EUR/JPY/BHD); currency echoed on `/me`, payments, requests, splits | Three fixtures |
| C7 | `settlement_operator_ids` optional, default `[]` | Fixture with and without |
| C8 | Unparseable reset body → 400 `malformed_request`; state unchanged | Own |

## D. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code","message"}}`, including 404 for unknown routes and 405-type cases | Own, each error path |
| D2 | Unparseable body, or body not an object, or field of wrong JSON type (not covered by D3) → 400 `malformed_request` | e.g. `to_handle: 5`, `participant_handles: "x"`, `email: 1`, `transfers: {}` per §11 is 422 (see I4) |
| D3 | Field-rule precedence: invalid `amount` (string, boolean, null, fractional, <1, >1e9) → 422; non-string `note` incl. `null` → 422; `visibility` not `public`/`private` (any type) → 422; omission selects defaults | Matrix on payments, requests, pay, splits, settlements |
| D4 | Amount accepts integral numeric JSON: `1000`, `1000.0`, `1e3` equal; `1000.5` → 422 | Own |
| D5 | Amount boundaries: 0 → 422, 1 ok, 1000000000 ok, 1000000001 → 422 | Own |
| D6 | `note` 200 chars ok, 201 → 422 (characters, not bytes); stored and returned verbatim incl. Unicode/emoji, whitespace, no trimming/escaping | Own |
| D7 | Missing required field or query parameter → 422 `validation_failed` | Own |
| D8 | Integer query params must be plain decimal digits: `1e9`, `4.0`, `+4`, `-1`, `abc`, empty → 422 | Own, on `/requests` and `/activity` |
| D9 | `limit` 1..200 (0 and 201 → 422; 1 and 200 ok), default 50; `offset` ≥ 0, default 0 | Own |
| D10 | `Idempotency-Key`: absent/empty → 400 `missing_idempotency_key`; 255 chars ok; 256 → 422 `validation_failed` | Own, on all five paths |
| D11 | 401 `unauthenticated` for missing, malformed or unknown bearer token on every protected endpoint; 401 precedes body/key checks | Own |

## E. Authentication (§6, §4 handles)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; new user balance 0; can be paid and requested immediately | Own |
| E2 | Handle derived from email: local part, lowercased, chars outside `[a-z0-9_]` → `_`, truncated to 20 | `A.b-C+tag@x.com` → `a_b_c_tag`; 25-char local part → 20 |
| E3 | Email already registered → 409 `email_taken`; derived handle taken (seeded or signed-up) → 409 `handle_taken`, no account created (login then 401) | Own |
| E4 | Password < 8 chars → 422 (7 fails, 8 ok); email not `local@domain` → 422 | Own |
| E5 | `POST /auth/login` → 200 `{user_id, display_name, token}`; wrong password or unknown email → 401 `unauthenticated` | Own |
| E6 | Tokens never expire; multiple valid tokens per account; concurrent sessions | Login twice, both tokens work |
| E7 | Passwords stored with bcrypt/scrypt/Argon2 or equivalent, never plaintext (also in export) | Code read + export inspection |
| E8 | Handles unique, match `^[a-z0-9_]{1,20}$`, immutable | Own |
| E9 | Only `/health`, `/_test/*`, signup, login are unauthenticated | Own |

## F. Idempotency (§7) — each of the five paths independently

| Row | Requirement | Check |
|---|---|---|
| F1 | First use → 201; replay (same user, method, path, JSON-equal body) → 200 with body identical as JSON value | Own ×5 |
| F2 | "Same body" is JSON-value equality: key order/whitespace irrelevant; `{}` vs `{"visibility":"public"}` differ | Own |
| F3 | Same key, different body → 409 `idempotency_key_reuse` | Own ×5 |
| F4 | Key scoped per user: two users, same key, no interaction | Own |
| F5 | Same key + same body on a different path is a new request and succeeds normally (e.g. pay on two different request ids) | Own |
| F6 | Key whose original request failed with 4xx is treated as first use (and claims nothing) | Own: fail insufficient_funds, then succeed with same key |
| F7 | Concurrent identical requests with an unused key: exactly one 201, others 200 same body, one effect | 20-way concurrent, ×5 paths |
| F8 | Successful replay returns the original response even after the resource changed (e.g. request later cancelled/paid); no further state change | Own |
| F9 | Once body parses as JSON object and caller is authenticated, a claimed key is resolved before field validation and resource checks: same key + now-invalid body → 409 `idempotency_key_reuse` | Own |
| F10 | Order: 401 → body parse (400) → key missing (400) / key length (422) → claimed-key resolution → validation | Own |

## G. Wallet endpoints (§8)

| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `user_id, display_name, handle, balance, currency, minor_units` | Supplied + own |
| G2 | `POST /payments` 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, settlement_id:null, created_at`; defaults note `""`, visibility `public` | Supplied + own |
| G3 | Payment errors: 409 `insufficient_funds` (balance < amount; balance == amount ok); 422 `self_payment`; 404 unknown handle; 422 amount/note/visibility | Own |
| G4 | Debit and credit atomic; failed payment leaves no trace in either wallet or the feed | Own |
| G5 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at`; caller is requester; payer balance not checked | Supplied + own |
| G6 | Request errors: 422 `self_request`; 404 unknown handle; 422 amount/note | Own |
| G7 | `POST /requests/{id}/pay`: payer only; body `visibility` optional default public; 201 with payment (as G2) with `request_id` set; request becomes `paid` with `payment_id` | Supplied + own |
| G8 | Pay errors: 404 unknown; 403 not payer (incl. requester and third party); 409 `request_not_pending`; 409 `insufficient_funds` changes nothing and request stays pending, payable later once funds arrive | Own |
| G9 | Replay of successful pay → 200 original payment, never `request_not_pending`, no extra money | Own |
| G10 | `POST /requests/{id}/decline`: payer only, no key; 200 request `declined`; repeat → 200; `paid`/`cancelled` → 409 `request_not_pending`; non-payer → 403; unknown → 404 | Own |
| G11 | `POST /requests/{id}/cancel`: requester only, no key; 200 `cancelled`; repeat → 200; `paid`/`declined` → 409; non-requester → 403; unknown → 404 | Own |
| G12 | `GET /requests`: only caller's (requester or payer); newest first; `direction` incoming/outgoing/absent; `status` four values/absent; unknown value → 422; `limit`/`offset` per D8/D9; `has_more` true iff items remain; shape `{requests, has_more}` | Own |
| G13 | `POST /splits` 201 body: `split_id, amount, currency, note, shares[{handle,amount}], requests[...], created_at`; shares cover all participants incl. caller in given order; requests for every participant except caller, same order, caller as requester; caller may be included or omitted | Supplied + own |
| G14 | Split errors: 422 amount/note; 422 empty or duplicate `participant_handles`; 404 any unknown handle; no balance check | Own |
| G15 | Caller-only split is valid: one share, `requests: []` | Own |
| G16 | `GET /activity`: payments only; visible iff public OR caller is sender or receiver; private hidden from third parties, visible to both parties with same `visibility` value; newest first; `{payments, has_more}`; limit/offset as G12 | Supplied + own |
| G17 | Requests and splits never appear in `/activity`; a request is never visible to third parties in `/requests` | Own |

## H. Rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| H1 | Shares are whole units, sum to `amount`, differ by ≤ 1, larger shares first in given order: 1000/3→334,333,333; 1/3→1,0,0; 10/3→4,3,3; 999/3→333×3; 5/5→1×5 | Own table test |
| H2 | Different order moves the extra unit; share 0 is legal and still creates a request (amount 0 request, payable as a 0-amount movement or at least representable) | Own |
| H3 | Shares independent across splits; after paying all splits the balance sum is unchanged | Own |

## I. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| I1 | `POST /settlements`: no token → 401; non-operator → 403 `forbidden`; needs idempotency key (F rows) | Own |
| I2 | Operator may move between any wallets, incl. ones it is not party to; grants no access to others' requests or private activity | Own |
| I3 | `transfers` 1..32 objects (0 and 33 → 422; 1 and 32 ok); each entry uses payment amount/note/visibility rules and defaults | Own |
| I4 | Malformed batch shape (missing/non-array `transfers`, non-object entry, out-of-range count) → 422 `validation_failed`; unknown handle → 404; self-transfer → 422 `self_payment`; entry errors take precedence in input order and before insufficient funds; unknown fields ignored | Own: batch with entry-2 unknown handle and entry-1 self-transfer → `self_payment`; unaffordable batch with a bad entry → entry error |
| I5 | Affordability is net: every wallet's balance after all transfers ≥ 0 (a wallet may pass through money it receives in the same batch); otherwise 409 `insufficient_funds` | Own: ada→bob 100, bob→cy 50 with bob at 0 succeeds |
| I6 | All-or-nothing; failed validation/409 claims no key, creates no payment | Own |
| I7 | 201 `{settlement_id, committed_at, payments}` in input order; each member is an ordinary payment with `settlement_id` set, `request_id` null, `created_at` == `committed_at`; non-members show `settlement_id: null` | Own |
| I8 | Members follow normal feed visibility; replay → 200 with the original complete response | Own |

## J. Export / import (§10)

| Row | Requirement | Check |
|---|---|---|
| J1 | `GET /_test/export` → 200 `{track:"pocketful", format_version:1, state:{...}}`, unauthenticated, atomic read-only snapshot | Own |
| J2 | `POST /_test/import` with unchanged export → 204; atomically replaces state (not merge); repeat import does not duplicate; removes previous data and credentials | Export A, reset to B, import A: B's users/tokens gone |
| J3 | Preserved: accounts + hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests, splits' requests, operator permissions, settlement membership, ids, timestamps, completed idempotency records (replay → 200 same body; different body → 409) | Own, import into a second fresh container |
| J4 | Failed-request keys remain reusable after import; no replay against balances | Own |
| J5 | Invalid JSON → 400 `malformed_request`; missing fields, wrong `track`, wrong `format_version`, invalid `state` → 422 `validation_failed`, destination unchanged | Own |
| J6 | No dependency on source process, files, port; works across containers; reset clears imported state; export/import/reset < 10 s | Own, two containers |

## Supplied checks

From `/home/ubuntu/nightshift-claude-bg-test/dark-factory-wearedevs`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>

Final run of the stage adds `--mode isolated`. Every run needs a new `--out` directory.

## Recorded choices

- Ambiguity "field of the wrong type" (400) vs endpoint field rules (422): amount/note/visibility
  wrong types are 422 (§5 bullet 1); other wrong types (e.g. non-string handle, non-array
  `participant_handles`, non-string email/password) are 400; §11 "malformed batch shape" is 422
  as that section states it specifically.
- A zero share creates a request with `amount: 0` (§9), although `POST /requests` itself rejects 0.
  Paying such a request is not forbidden by the spec; it should succeed as a zero-amount payment.
