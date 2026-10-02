@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier
STAGE 1 HANDOFF, part 3 of 5. Rows: all · Revision: no stage code yet (map commit at HEAD) · Files: stage-1/ · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer builds, Verifier prepares checks.

== Specification, verbatim, continued (POST /splits in section 8 to the end) ==

### `POST /splits`

**An idempotent write path.** Splits an amount the caller already paid, and asks each of the other
participants for their share by creating one `pending` request each.

```http
POST /splits
Idempotency-Key: 7a3e52...

{ "amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner" }
```

The caller may be included in `participant_handles` or omitted. Shares follow the equal-split
rule in §9, in the order the handles are given. **A request is created for every participant
except the caller**, each for that participant's share, with the caller as requester.

```json
201
{
  "split_id": "sp_2",
  "amount": 3000,
  "currency": "EUR",
  "note": "dinner",
  "shares": [ { "handle": "ada", "amount": 1000 },
              { "handle": "bob", "amount": 1000 },
              { "handle": "cy",  "amount": 1000 } ],
  "requests": [ { ...request for bob... }, { ...request for cy... } ],
  "created_at": "2026-09-24T11:11:00+00:00"
}
```

`shares` covers every participant including the caller, in the order given, and always sums to
`amount`. `requests` covers every participant except the caller, in the same order.

| Case | Response |
|---|---|
| `amount` below 1, above 1000000000, or not an integer | 422 `validation_failed` |
| `participant_handles` empty, or containing a duplicate handle | 422 `validation_failed` |
| `note` longer than 200 characters | 422 `validation_failed` |
| Any handle is unknown | 404 `not_found` |

A split whose only participant is the caller is **valid**: it computes one share, creates zero
requests, and returns `"requests": []`. Nothing about a split checks anyone's balance.

### `GET /activity`

```http
GET /activity?limit=50&offset=0
```

Payments visible to the caller by the feed contract in §4, newest first by `created_at`.

```json
{ "payments": [ { ...payment... } ], "has_more": false }
```

- The relative order of two payments created within the same second is unspecified.
  Stable pagination during concurrent writes is not required for this endpoint.
- `limit` and `offset` behave exactly as in `GET /requests`.

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

== END OF SPECIFICATION ==

== Acceptance map (acceptance/stage-1.md), verbatim, starts here ==

# Acceptance map: Pocketful stage 1

Source: `pocketful/spec/stage-1.md` in the kickoff checkout. Every row must hold for the
revision that is accepted. The supplied harness checks sample only part of this map.

Check kinds: **T** black-box HTTP test against the built container (status, `error.code`,
body, balances via `GET /me`) · **C** concurrency burst, up to 50 requests in flight, under
`--cpus 2 --memory 2g` · **D** docker build/run inspection · **R** source review.
Rows marked *(choice)* are Architect readings where the spec is silent; see "Choices".

## A. Delivery and runtime (§1 to §3)

- A01 [§2] `stage-1/` holds a complete service, a `Dockerfile` and a `RUN.md` with a command that builds and starts it with no manual setup. No nested `.git`. D: follow RUN.md from a clean clone.
- A02 [§2] Image runs alone with `-e PORT=<port>` and a port mapping; Compose is not needed. D.
- A03 [§2] No outbound network at run time; all dependencies, assets, initialisation in the image. D: run with `--network none` or internal network; harness `--mode isolated`.
- A04 [§2] Works within 2 vCPU, 2 GiB. First healthy response within 60 s of start. D: `docker run --cpus 2 --memory 2g`, time to `/health`.
- A05 [§2] 50 requests in flight, each answered within 5 s (reset, export, import within 10 s). C: mixed burst, record max latency. Includes 50 concurrent logins and a reset of a 50-user fixture.
- A06 [§3.1] Listens on `0.0.0.0`, port from `PORT`, default `8080`. D: run with and without `PORT`.
- A07 [§3.2] `GET /health` gives 200 `{"status":"ok"}` once ready; no auth. T.
- A08 [§3.3] `POST /_test/reset` with a fixture gives 204 with no body, replaces all state (users, tokens, payments, requests, splits, settlements, idempotency records, operators); afterwards only the fixture is visible; old tokens give 401; repeatable; no auth needed; a stale `Authorization` header on it is ignored. T.
- A09 [§3.4] Responses are `application/json; charset=utf-8`. T: header on success and error responses.
- A10 [§3.4] Response timestamps are RFC 3339 with explicit numeric offset (e.g. `+00:00`). T: regex and parse.
- A11 [§3.4] Unknown body fields ignored; unknown query parameters ignored (e.g. `direction` on `/activity`). T.
- A12 [§3.4] IDs are opaque strings of at most 64 characters, including fixture-supplied IDs kept as given. T.
- A13 [§2,§1] Only the HTTP API; no UI or later-stage features in `stage-1/`. R.

## B. Model and invariants (§1, §4)

- B01 [§1.1] Sum of all wallet balances always equals the total seeded by the last reset (or import). T+C: sum `/me` over all users after every scenario and burst.
- B02 [§1.2] No balance ever negative, including transiently. C: 50 clients drain one wallet; exactly the affordable number succeed, rest 409 `insufficient_funds`, final balance >= 0.
- B03 [§1.3] A request moves money at most once. C: 50 concurrent pays of one request with distinct keys give exactly one 201, others 409 `request_not_pending`; concurrent pay against decline/cancel has one winner.
- B04 [§4] One currency and `minor_units` (0, 2 or 3) from the fixture, shown in `/me` and every payment/request/split. T with EUR, JPY, BHD.
- B05 [§4] Amounts are integral JSON numbers: `1000`, `1000.0`, `1e3` are the same valid amount; booleans, strings, `null`, fractions are invalid. Responses emit amounts as JSON integers (`1000`, never `1000.0`). T.
- B06 [§4] `amount` max 1000000000 on any request; arithmetic exact up to ±2^53 (no floating-point balances). T: `1e9` and `1000000000` accepted as valid (409 if unfunded); `1000000001` rejected. R: integer arithmetic.
- B07 [§4] Handles: unique, `^[a-z0-9_]{1,20}$`, immutable. Seeded users keep the fixture handle. T.
- B08 [§4] Signup handle derived from email: local part, lowercased, every character outside `[a-z0-9_]` replaced by `_`, truncated to 20. T: `Dee.Ann+tag@example.com` gives `dee_ann_tag`; long local part truncated to 20.
- B09 [§4] New users start at balance 0 and can immediately receive money and be asked for money. T.
- B10 [§4] Request lifecycle: `pending`, then exactly one of `paid`, `declined`, `cancelled`; terminal states never change. T.
- B11 [§4] A request may exceed the payer's balance: created normally, stays `pending`; pay while short is 409 `insufficient_funds` and changes nothing; payable later once funded. T.
- B12 [§4] Visibility belongs to the payment; requests carry none and never appear in any feed. T.
- B13 [§4] Feed rule: a payment is visible to a caller iff it is `public` or the caller is its sender or receiver. No other rule. T: third party, sender, receiver, public and private; an operator gets no extra visibility.
- B14 [§4] Fixture: seeded users log in with the given password at once; ids, handles, display names kept; `balance` taken as given (seeded payments are not replayed against balances). T.
- B15 [§4] Seeded `payments` appear in the feed under the feed rule with their fixture id, `request_id` null, `settlement_id` null. Seeded `requests` are listed for their two parties with fixture id and status; a seeded `pending` request can be paid; a seeded non-pending one gives 409 `request_not_pending`. T.
- B16 [§4] A fixture user `balance` below zero gives 422 `validation_failed` from reset and changes nothing (previous state and tokens intact). T.
- B17 [§4] *(choice)* Other invalid fixtures (missing required field, wrong type, duplicate user id/handle/email, payment or request naming an unknown user, `minor_units` not 0/2/3, bad status or visibility, non-integer balance) give 422 `validation_failed` and change nothing; an unparseable body gives 400 `malformed_request`. `payments`, `requests`, `settlement_operator_ids` are optional and default to `[]`. Never 5xx. T.
- B18 [§4] No deposit, top-up, withdrawal or administrative balance endpoint exists. R+T: such paths give 404.

## C. Errors (§5)

- C01 Every 4xx/5xx body is `{"error":{"code":...,"message":...}}`, including 404 for unknown routes, 405, oversized or unparseable requests. T.
- C02 400 `malformed_request`: unparseable body (bad JSON, bad UTF-8, empty where a body is required, JSON that is not an object), or a field of the wrong JSON type (e.g. `to_handle: 5`, `participant_handles: "ada"`, `email: 5`). T.
- C03 422 `validation_failed`: required field or query parameter missing; correct type but invalid format or out of range; exceeding a stated maximum or length. T: missing `to_handle`, missing `amount`.
- C04 Endpoint field rules win over C02: invalid `amount` (string, boolean, null, fraction, 0, negative, above max), non-string `note` (including `null`), and any `visibility` other than exactly `public`/`private` (`"Public"`, `""`, `null`, number) are 422 `validation_failed`. Omission selects defaults. T on payments, requests, splits, pay, settlements.
- C05 401 `unauthenticated` for missing, malformed or unknown bearer token on every authenticated endpoint; checked before anything else on that endpoint. T on each endpoint.
- C06 403 `forbidden`, 404 `not_found` as listed per endpoint. T.
- C07 Integer query parameters are plain decimal digits only: `1e9`, `4.0`, `+4`, `-1`, `abc`, empty are 422. T on `limit` and `offset` of `/requests` and `/activity`.
- C08 `limit` integer 1 to 200 (default 50), `offset` integer >= 0 (default 0), otherwise 422. T: 0, 201, 200, 1; very large digit strings never 5xx.
- C09 `Idempotency-Key` 1 to 255 characters; longer is 422 `validation_failed` (a 10 000-character key must reach the handler and give 422, not a server-level 431/400); absent or empty is 400 `missing_idempotency_key`. T on all five paths.
- C10 No request produces a 5xx, including under 50 concurrent requests and awkward input (huge numbers such as `1e400`, deep or large bodies, 1000-element lists, lone surrogates, NUL characters). T+C.

== end of part 3 of 5; the acceptance map continues in part 4 ==
