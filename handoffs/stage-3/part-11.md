@vibhor15/nightshift-implementer STAGE 3 HANDOFF — part 11 of 13: specification stage-1.md (verbatim; still applies), piece 2 of 2. Do not start until part 13 (FINAL).

## 8. API

### `GET /me`

```json
{ "user_id": "u_ada", "display_name": "Ada", "handle": "ada",
  "balance": 10000, "currency": "EUR", "minor_units": 2 }
```

### `POST /payments`

**An idempotent write path.** `Idempotency-Key` is required; see §7.

```http
POST /payments
Authorization: Bearer <token>
Idempotency-Key: 2f9c1a...

{ "to_handle": "bob", "amount": 1500, "note": "dinner", "visibility": "public" }
```

`note` is optional and defaults to `""`. `visibility` is optional and defaults to `"public"`.

```json
201
{
  "payment_id": "p_7",
  "from_user_id": "u_ada",
  "from_handle": "ada",
  "to_user_id": "u_bob",
  "to_handle": "bob",
  "amount": 1500,
  "currency": "EUR",
  "note": "dinner",
  "visibility": "public",
  "request_id": null,
  "created_at": "2026-09-24T11:04:03+00:00"
}
```

| Case | Response |
|---|---|
| The caller's balance is below `amount` | 409 `insufficient_funds` |
| `amount` below 1, above 1000000000, or not an integer | 422 `validation_failed` |
| `to_handle` is the caller's own handle | 422 `self_payment` |
| `note` longer than 200 characters | 422 `validation_failed` |
| `visibility` is neither `public` nor `private` | 422 `validation_failed` |
| No user has that handle | 404 `not_found` |

The debit and the credit are one atomic step. A payment is never visible in one wallet and not the
other, and a failed payment leaves no trace in either.

`note` is stored and returned verbatim: no trimming, no escaping, no normalisation. Unicode and
emoji survive a round trip byte for byte.

### `POST /requests`

**An idempotent write path.**

```http
POST /requests
Idempotency-Key: 9b1f04...

{ "payer_handle": "ada", "amount": 1200, "note": "taxi" }
```

The caller is the requester.

```json
201
{
  "request_id": "rq_4",
  "requester_id": "u_bob",
  "requester_handle": "bob",
  "payer_id": "u_ada",
  "payer_handle": "ada",
  "amount": 1200,
  "currency": "EUR",
  "note": "taxi",
  "status": "pending",
  "payment_id": null,
  "created_at": "2026-09-24T11:06:10+00:00"
}
```

| Case | Response |
|---|---|
| `amount` below 1, above 1000000000, or not an integer | 422 `validation_failed` |
| `payer_handle` is the caller's own handle | 422 `self_request` |
| `note` longer than 200 characters | 422 `validation_failed` |
| No user has that handle | 404 `not_found` |

**The payer's balance is not checked here.** A request for more than the payer holds is created
normally and sits `pending`.

### `POST /requests/{id}/pay`

**An idempotent write path.** Only the payer may call it.

```http
POST /requests/rq_4/pay
Idempotency-Key: c41d88...

{ "visibility": "private" }
```

The body carries `visibility` only, optional, default `"public"`. It is the payer's choice, not the
requester's. **A replay must send the identical body** — `{}` and `{"visibility": "public"}` are
different JSON values, so reusing a key across the two is `409 idempotency_key_reuse`, per §7.

Returns `201` with the created **payment**, exactly as `POST /payments` returns one, with
`request_id` set to this request. The request becomes `paid` and carries the new `payment_id`.

| Case | Response |
|---|---|
| The request is not `pending` | 409 `request_not_pending` |
| The payer's balance is below `amount` | 409 `insufficient_funds` |
| The caller is not the request's payer | 403 `forbidden` |
| Unknown request | 404 `not_found` |

Replaying a successful payment returns 200 with its original payment body, including
when the request is already `paid`. It moves no additional money and must not return
`409 request_not_pending`.

### `POST /requests/{id}/decline`

Only the payer. No idempotency key. Returns `200` with the request, `status: "declined"`. Declining
an already-declined request is `200` with the current state — declining twice is not an error.
A `paid` or `cancelled` request is `409 request_not_pending`. Not the payer is `403 forbidden`.

### `POST /requests/{id}/cancel`

Only the requester. No idempotency key. Returns `200` with the request, `status: "cancelled"`.
Cancelling an already-cancelled request is `200`. A `paid` or `declined` request is
`409 request_not_pending`. Not the requester is `403 forbidden`.

### `GET /requests`

```http
GET /requests?direction=incoming&status=pending&limit=50&offset=0
```

Requests where the caller is the requester or the payer, and no others. Newest first by
`created_at`.

- `direction` is `incoming` (the caller is the payer), `outgoing` (the caller is the requester) or
  absent for both.
- `status` is one of the four statuses, or absent for all.
- `limit` defaults to 50, range 1 to 200. `offset` defaults to 0 and must be 0 or more. Outside
  either range is 422 `validation_failed`. An unknown `direction` or `status` value is also 422.
- `has_more` is true when items exist beyond the last one returned.

```json
{ "requests": [ { ...request... } ], "has_more": false }
```

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
