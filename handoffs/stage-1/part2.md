@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: all of A1..L3 · Revision: 05b638dea1f421f2b9fffc161ad9ac63f39dc983 · Files: n/a · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer builds, Verifier prepares checks (see part 5).

STAGE 1 HANDOFF, part 2 of 5. SPECIFICATION, stage 1, complete text (part 2 of 3: sections 5 to 8, up to and including POST /requests).

## 5. Errors

Every 4xx and 5xx response carries this body:

```json
{ "error": { "code": "insufficient_funds", "message": "human readable, any wording" } }
```

Use the specified HTTP status and `code`. The human-readable `message` may use any wording.
Endpoint-specific errors are listed with each endpoint.

| Status | `code` | When |
|---|---|---|
| 400 | `malformed_request` | Unparseable body, or a field of the wrong JSON type |
| 400 | `missing_idempotency_key` | Required `Idempotency-Key` header absent or empty |
| 401 | `unauthenticated` | Missing, malformed or unknown bearer token |
| 403 | `forbidden` | Authenticated, but not permitted to touch this resource |
| 404 | `not_found` | No such resource, or not visible to this caller |
| 409 | `idempotency_key_reuse` | Key already used by this caller with a different request body |
| 422 | `validation_failed` | A required field or query parameter is missing, or a stated rule is violated with no more specific code |

A field of the correct JSON type with an invalid format or out-of-range value gives
422 `validation_failed`, unless an endpoint specifies a different error. This includes
invalid dates, negative counts and values exceeding a stated maximum or length. In addition:

- Endpoint-specific field rules take precedence: invalid `amount` values (including strings and
  booleans), non-string `note` values (including `null`), and any `visibility` other than
  `public` or `private` are 422 `validation_failed`. Omission alone selects the optional-field
  defaults. Other wrong JSON types follow the rule below.
- An integer-valued **query parameter** is written as plain decimal digits: `1e9`, `4.0` and `+4`
  are 422 `validation_failed` whatever their numeric value.
- Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type.

Shared ranges, enforced on every endpoint that takes them:

| Field | Valid | Otherwise |
|---|---|---|
| `Idempotency-Key` | 1 to 255 characters | 422 `validation_failed` |
| `limit` | integer 1 to 200 | 422 `validation_failed` |
| `offset` | integer 0 or more | 422 `validation_failed` |

Requests must not produce 5xx responses, including under concurrent load.

## 6. Authentication

Authentication supports signup and login. Email verification, password reset, refresh
tokens and role-management endpoints are out of scope. Permissions specified elsewhere
in these requirements still apply.

```http
POST /auth/signup
{ "email": "a@example.com", "password": "correct horse", "display_name": "Ada" }

->  201  { "user_id": "u_1", "display_name": "Ada", "token": "..." }
```

```http
POST /auth/login
{ "email": "a@example.com", "password": "correct horse" }

->  200  { "user_id": "u_1", "display_name": "Ada", "token": "..." }
```

| Case | Response |
|---|---|
| Email already registered | 409 `email_taken` |
| Password shorter than 8 characters | 422 `validation_failed` |
| `email` not of the form `local@domain` | 422 `validation_failed` |
| Wrong password or unknown email on login | 401 `unauthenticated` |
| The handle derived from the email (§4) is already taken | 409 `handle_taken`, and no account is created |

Every other endpoint requires a bearer token, except `/health`, `/_test/reset` and the two above.
Wallet API endpoints require authentication.

```http
Authorization: Bearer <token>
```

Tokens do not expire. An account may have multiple valid tokens and concurrent sessions.

Passwords must be stored using a password-hashing function such as bcrypt, scrypt or
Argon2, or an equivalent. Plaintext password storage is not permitted.

## 7. Idempotency

Five write paths require an idempotency key (§8 and §11): **`POST /payments`**, **`POST /requests`**,
**`POST /requests/{id}/pay`**, **`POST /splits`** and **`POST /settlements`**. Everything below applies to each of them
independently.

```http
Idempotency-Key: <client-chosen string, 1..255 characters>
```

The key is scoped to **the authenticated user**. Two different users may use the same key string
with no interaction between them.

A replay means the same user sending the **same method, the same path and the same body**. The
same key with the same body on a different path is a different request, not a replay, and must
succeed normally.

| Situation | Response |
|---|---|
| Header absent or empty | 400 `missing_idempotency_key` |
| First use of the key | The normal response, **201** |
| Replay: same key, same body | **200**, body identical to the original response as a JSON value |
| Same key, different body | 409 `idempotency_key_reuse` |
| Key reused after the original request failed with 4xx | Treated as a first use |

"Same body" means the same JSON value after parsing — key order and whitespace do not matter.

For concurrent identical requests with an unused key, exactly one returns 201.
The others return 200 with the same body. The operation takes effect only once.

A successful replay returns the original response, even after the resource changes or
is cancelled. It makes no further state changes.

After the body has parsed as a JSON object and the caller is authenticated, an already
claimed key is resolved before endpoint field validation or current-resource checks. Thus
changing a successful request to an invalid body with the same key still returns
`409 idempotency_key_reuse`.

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


(end of part 2 of 5; part 3 continues inside section 8 at POST /requests/{id}/pay)
