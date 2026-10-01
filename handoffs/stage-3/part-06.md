@vibhor15/nightshift-implementer STAGE 3 HANDOFF — part 6 of 13: specification stage-2.md (verbatim; still applies), piece 2 of 2. Do not start until part 13 (FINAL).

## API

### `GET /me`

```json
{ "user_id": "u_ada", "display_name": "Ada", "handle": "ada",
  "balance": 10000, "total": 10000, "available": 8000, "held": 2000,
  "currency": "EUR", "minor_units": 2 }
```

`balance` and `total` are always equal. `held` is the sum of open holds, and `available` is
`total − held`, never negative.

### `POST /authorizations`

`Idempotency-Key` is required. The caller is the payer.

```json
{ "to_handle": "bob", "amount": 2000, "note": "deposit", "visibility": "private" }
```

`note` and `visibility` are optional with the same defaults as `POST /payments`.

```json
201
{
  "authorization_id": "a_4",
  "from_user_id": "u_ada", "from_handle": "ada",
  "to_user_id": "u_bob", "to_handle": "bob",
  "amount": 2000,
  "captured_amount": 0,
  "currency": "EUR",
  "note": "deposit",
  "visibility": "private",
  "status": "open",
  "expires_at": "2026-09-24T13:20:00+00:00",
  "payment_id": null,
  "created_at": "2026-09-24T13:10:00+00:00"
}
```

`expires_at` is `created_at` plus `authorization_ttl_seconds`.

| Case | Response |
|---|---|
| The caller's `available` is below `amount` | 409 `insufficient_funds` |
| `amount` below 1, above 1000000000, or not an integer | 422 `validation_failed` |
| `to_handle` is the caller's own handle | 422 `self_payment` |
| `note` over 200 characters, or `visibility` neither `public` nor `private` | 422 `validation_failed` |
| No user has that handle | 404 `not_found` |

An open authorisation is **not** a feed item and never appears in `GET /activity`.

### `POST /authorizations/{id}/capture`

`Idempotency-Key` is required. Only the receiver (the `to` party) may capture.

```json
{ "amount": 1500 }
```

`amount` is optional and defaults to the authorisation's remaining amount. As on
`POST /requests/{id}/pay`, **a replay must send the identical body** — `{}` and `{"amount": 2000}`
are different JSON values even when they mean the same capture, so reusing a key across the two is
409 `idempotency_key_reuse` per `stage-1.md` §7.

Returns `201` with the created **payment**, in exactly the shape `POST /payments` returns, with
`authorization_id` set to this authorisation and `request_id: null`. The payment's `amount` is the
captured amount; its `note` and `visibility` are copied from the authorisation; it appears in the
activity feed by the ordinary visibility rule. Payments created without an authorisation
carry `authorization_id: null`; their existing `request_id` semantics are unchanged.

By default the authorisation becomes `captured`, carries `captured_amount` and `payment_id`, and **releases the
uncaptured remainder immediately**: capturing 1500 of 2000 returns 500 to the payer's `available` in
the same step.

**Default: one final capture per authorisation.** A second capture after a final capture is
`409 authorization_not_open`.

**Extended capture mode.** To keep the remainder held, send `{"amount": 700, "final": false}`.
`final` is boolean, default `true`, so earlier single-capture requests retain their behavior.
With `final: false` and an uncaptured remainder, status stays `open`; further captures are
allowed up to that remainder. Capturing the entire remainder closes it even with `final: false`.
A final capture closes it and releases any remainder. `capture_exceeds_authorization` compares
with the **remaining** amount; omitted amount defaults to that remainder. `captured_amount` is
cumulative; `payment_id` is the latest capture; `payment_ids` lists every capture in order.
Every authorization response adds `remaining_amount`: the amount still held, zero when closed.
Void and expiry can close a partially captured authorization, release only the remainder,
and preserve all capture records. New fields do not change idempotency body equality.

| Case | Response |
|---|---|
| The authorisation is not `open` | 409 `authorization_not_open` |
| `expires_at` is at or before now | 409 `authorization_expired` |
| `amount` above the authorisation's uncaptured remainder | 422 `capture_exceeds_authorization` |
| `amount` below 1, or not an integer | 422 `validation_failed` |
| The caller is not the receiver | 403 `forbidden` |
| Unknown authorisation | 404 `not_found` |

### `POST /authorizations/{id}/void`

**Only the payer may void** — the `from` party releasing their own hold. No idempotency key, like
decline and cancel.

`200` with the authorisation, `status: "voided"`, the hold released. Voiding an already-voided
authorisation is `200` with the current state. A `captured` or `expired` one is
`409 authorization_not_open`.

For an existing authorization, capture and void return 403 `forbidden` when the caller
is not the permitted party, including callers who are neither party. `GET /authorizations`
returns only authorizations involving the caller.

### `GET /authorizations`

```http
GET /authorizations?direction=outgoing&status=open&limit=50&offset=0
```

Authorisations where the caller is the payer or the receiver, and no others. Newest first by
`created_at`.

- `direction` is `outgoing` (the caller is the payer), `incoming` (the caller is the receiver), or
  absent for both.
- `status` is one of the four statuses, or absent for all. An authorisation expired by the clock
  matches `expired`, never `open`.
- `limit`, `offset` and `has_more` behave exactly as on `GET /requests`.

## UI

A new route `/authorizations`, and the wallet gains two numbers. The UI and the API share
`/authorizations`: serve HTML for `Accept: text/html` and JSON otherwise, as for `/requests`.

| `data-testid` | Element |
|---|---|
| `wallet-balance` | Formatted `total`, retaining the existing display and `data-amount` |
| `wallet-available` | Formatted `available`, with `data-amount`. **Present this as the headline number** — it is what the user can actually spend |
| `wallet-held` | Formatted `held`, with `data-amount`. Absent when `held` is zero |
| `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` | The authorise form. Same input rules as the pay form |
| `authorize-error` | Shown when the authorisation is refused, including insufficient available funds |
| `authorization-list` | Container on `/authorizations`. Children newest first in the DOM |
| `authorization-item-{authorization_id}` | Carries `data-status="{status}"` |
| `authorization-amount-{id}` | Text is exactly the formatted authorised amount |
| `authorization-captured-{id}` | Formatted captured amount. Present only when `status` is `captured` |
| `authorization-expires-{id}` | Text is the RFC 3339 `expires_at` |
| `authorization-capture-amount-{id}` | Decimal input, pre-filled with the remaining amount. Present only on an incoming `open` authorisation |
| `authorization-capture-{id}` | Button. Present only on an incoming `open` authorisation |
| `authorization-void-{id}` | Button. Present only on an outgoing `open` authorisation |
| `authorization-error` | Shown when a capture or a void is refused |
| `empty-authorizations` | Shown when the list is empty |

The UI must reflect seeded and newly created holds. Show available funds as the user's
spending balance, including immediately after reset with open holds.

## Concurrent operations

Concurrent requests must produce the same results as executing them one at a time in some
order, and the requirements above hold at every read.
