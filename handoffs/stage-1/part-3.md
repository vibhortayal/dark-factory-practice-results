@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier

Rows: all · Revision: n/a · Files: n/a · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer builds, Verifier prepares checks.

STAGE 1 HANDOFF — PART 3 of 5

## Specification, verbatim, continued: §9–§11 (end of specification)

## 9. Money and rounding

Shares must be whole minor units, sum exactly to `amount` and differ by at most one
minor unit. When the amount does not divide evenly, the larger shares go to the first
participants in `participant_handles` order.

| `amount` | `n` | Shares |
|---|---|---|
| 1000 | 3 | 334, 333, 333 |
| 1 | 3 | 1, 0, 0 |
| 10 | 3 | 4, 3, 3 |
| 999 | 3 | 333, 333, 333 |
| 5 | 5 | 1, 1, 1, 1, 1 |

Splitting the same amount among the same people in a different
`participant_handles` order gives the extra unit to a different person. A share of `0` is legal and
still produces a request for that participant.

Each split's shares are independent of previous splits. After any number of splits have
been paid in full, wallet balances must still sum exactly to the seeded total.

## 10. Export and import

The service must support `GET /_test/export` and `POST /_test/import`. Like reset, these
are unauthenticated test endpoints.
Exports may contain credentials and session tokens; handle them as private test artifacts.
Return 200 from export with a JSON object containing `track: "pocketful"`,
`format_version: 1` and `state` (an implementation-defined JSON object). The state format
is opaque to the caller and must be accepted unchanged by import.

Import takes that entire object and atomically replaces the service's state, returning
204. It must accept an unchanged export produced by this service. No dependency on the
source process, files, volume, port or network address is allowed. Import is replacement,
not merge; repeating it restores the exported state without duplicating anything. Invalid
JSON follows §5; missing fields, wrong track/version or an invalid state give 422
`validation_failed` without changing the destination. Test control calls have a 10-second
timeout. Export is an atomic, read-only snapshot; subsequent source writes do not change it.

Preserve accounts and hashed-password login, existing bearer tokens, currency, balances,
payments, requests, permissions, all completed idempotent request bodies and original
responses. Identities, timestamps and monetary records must not be regenerated or replayed
against an already-net balance. Failed request keys remain reusable. Existing receipts,
tokens and retries must remain valid after import; replacing the state with a fresh fixture
does not satisfy this requirement. Import removes all previous destination data and
credentials. Reset clears all state, including imported state. State need not survive an
abrupt container restart.

## 11. Atomic net settlements

The reset fixture may include `settlement_operator_ids`, an array of user ids, default [].
An operator may execute a settlement across any wallets. This permission does not grant
access to another user's requests or private activity items.

`POST /settlements` requires an operator and an idempotency key. No token gives 401;
authenticated non-operator gives 403 `forbidden`. Body:

```json
{"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
               {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}
```

transfers contains 1..32 objects. Each uses ordinary payment amount, note and visibility
rules (defaults: empty note, public). Unknown handle is 404; self-transfer is 422
`self_payment`; malformed batch shape is 422 `validation_failed`. Entry errors take precedence
in input order, before insufficient funds. Unknown fields are ignored.

A settlement is affordable when every wallet's balance after all incoming and outgoing
transfers is nonnegative. Insufficient collective funds gives 409 `insufficient_funds`.
Either all movements commit together or none do; failed
validation claims no idempotency key and creates no payment or revision.

Return 201 with `settlement_id`, `committed_at` and `payments` in input order. Every member is
an ordinary payment with `settlement_id` linking the batch; nonmembers expose null for that
field. Members have null request_id and the same server-assigned created_at, equal to
committed_at.

Constituents follow ordinary activity-feed visibility. The settlement response contains every
member's receipt. Replays return
200 with the original complete response. This is the fifth idempotent write path in stage 1.
A reset/import must preserve settlement operator permissions, original payments, requests,
settlement membership and retry responses.

--- END OF SPECIFICATION ---

## Acceptance map (ACCEPTANCE-MAP-stage-1.md), sections A–D

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
| C19 | Other malformed fixtures (unparseable → 400 `malformed_request`; structurally invalid → 4xx error body) never 5xx and change nothing | Send `[]`, `{}`, missing `users`, duplicate handles |

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

(end of part 3 of 5)
