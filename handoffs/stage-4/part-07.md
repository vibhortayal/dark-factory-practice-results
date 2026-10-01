@vibhor15/nightshift-implementer STAGE 4 HANDOFF — part 7 of 15: specification stage-2.md (verbatim; still applies), piece 1 of 2. Do not start until part 15 (FINAL).

# Pocketful — Stage 2: wallet screens and payment authorizations

The stage-1 requirements continue to apply, with the additions below. Numbered section
references such as §5 and §7 refer to `stage-1.md`.

Users can manage payments, requests and bill splits in a browser. They can also reserve
money for a recipient to collect later, in one or more captures.

The following screens must be reachable by URL. Other screens must be reachable through
the UI. Server-side and client-side rendering are both permitted.

| Route | Screen |
|---|---|
| `/` | Balance, pay form, request form and the activity feed |
| `/requests` | Incoming and outgoing requests, with pay, decline and cancel |
| `/split` | Split form |
| `/signup` | Signup |
| `/login` | Login |

The browser and the API share `/requests`. Return the UI for `Accept: text/html`; API requests
without that header receive JSON.

The UI must expose the `data-testid` attributes listed below for integration testing.
Additional elements are permitted, and the visual implementation is the team's choice subject
to the product-quality requirements below.

## Product and visual direction

The browser experience must feel like a coherent, presentation-ready consumer finance product,
not a test harness with controls attached. Aim for a calm, trustworthy character. Available funds
must be the clearest monetary value once holds exist, with total and held funds visibly secondary.
Payments, requests, splits and authorisations should be easy to scan, and status, direction,
privacy and money movement should be understandable without interpreting raw API data.

Use a consistent visual system for typography, spacing, colour, controls and feedback. Primary
actions must be easy to identify. Available, held, pending, loading, successful, refused and
uncertain states must be visually distinct as well as satisfying the behavioural requirements
below. Format people, amounts and timestamps for people first; expose technical identifiers only
where they help the user.

The required flows must remain clear and usable at a 375 CSS-pixel viewport and at conventional
desktop widths, without horizontal page scrolling. Inputs need visible labels, keyboard focus must
be apparent, and text and controls need sufficient contrast. Provide considered empty, loading and
error states, and keep navigation consistent across the required routes. A custom illustration,
brand asset or exact visual match to a reference is not required.

## Signup and login

| `data-testid` | Element |
|---|---|
| `signup-email`, `signup-password`, `signup-display-name` | Inputs |
| `signup-submit` | Button |
| `login-email`, `login-password`, `login-submit` | Inputs and button |
| `auth-error` | Error message. Present only when there is one |
| `current-user` | Visible on every screen when signed in. Text contains the display name |
| `current-handle` | Text is exactly the caller's handle, with no `@` and no surrounding words |
| `logout-button` | Button |

## Balance and pay — `/`

| `data-testid` | Element |
|---|---|
| `wallet-balance` | Text is exactly the formatted amount. Carries `data-amount="{minor units}"` |
| `pay-handle`, `pay-amount`, `pay-note` | Inputs. `pay-amount` is a **decimal** string as a person would type it, e.g. `15.00` |
| `pay-visibility` | Selects `public` or `private`. Option values are those two strings |
| `pay-submit` | Button |
| `pay-error` | Error message, when the payment is refused — including insufficient funds |
| `request-handle`, `request-amount`, `request-note`, `request-submit` | The request form |
| `request-error` | Error message, when the request is refused |

Keep the pay form's values after success. Submitting it again without changing a field
must not send another payment: `wallet-balance` falls once, the feed contains one payment
and `pay-error` is absent. Changing a field makes the next submission a new payment request.
Retries follow §7.

**Formatted amount.** `wallet-balance` is the decimal with exactly `minor_units` decimal places, a
single space, then the currency code: `100.00 EUR`. For a `minor_units` of `0` there is no decimal
point at all: `1200 JPY`. Balances are never negative, so there is no sign.

The form accepts decimal amounts and submits minor units to the API. With `minor_units: 2`,
`15.00` and `15` both submit `1500`; `15.5` submits `1550`. Nonnumeric input or more than
`minor_units` decimal places must show the form's error element without sending a request.
For example, `15.005` is rejected rather than rounded.

## Activity feed — `/`

| `data-testid` | Element |
|---|---|
| `activity-list` | Container. Its children are newest first in the DOM |
| `activity-item-{payment_id}` | One per visible payment. Carries `data-visibility="public"` or `data-visibility="private"` |
| `activity-parties-{payment_id}` | Text contains both handles |
| `activity-amount-{payment_id}` | Text is exactly the formatted amount |
| `activity-note-{payment_id}` | Text is exactly the note. Present even when the note is empty |
| `empty-activity` | Shown instead of the list when nothing is visible |

Two payments with equal timestamps may appear in either order.

## Requests — `/requests`

| `data-testid` | Element |
|---|---|
| `incoming-list`, `outgoing-list` | Containers |
| `request-item-{request_id}` | One per request. Carries `data-status="{status}"` |
| `request-amount-{request_id}` | Text is exactly the formatted amount |
| `request-pay-{request_id}` | Button. Present only on a `pending` incoming request |
| `request-decline-{request_id}` | Button. Present only on a `pending` incoming request |
| `request-cancel-{request_id}` | Button. Present only on a `pending` outgoing request |
| `request-error` | Shown when a pay, decline or cancel is refused |
| `empty-requests` | Shown when both lists are empty |

## Split — `/split`

| `data-testid` | Element |
|---|---|
| `split-amount` | Decimal input, same rule as `pay-amount` |
| `split-handles` | Text input: handles separated by commas, in order |
| `split-note`, `split-submit` | Input and button |
| `split-preview` | Shows the computed shares before submitting. Contains one `split-share-{handle}` per participant |
| `split-share-{handle}` | Text is exactly the formatted share amount |
| `split-error` | Error message, when the split is refused |

`split-preview` must show the shares the server would compute, by the rule in `stage-1.md`
§9, before anything is posted. The preview and submitted split must have identical shares.

After any successful action, the balance, the feed and the request lists on the same page must
show the new state without a manual reload. Navigation must wait for the write to succeed before
it refreshes the data. Any mechanism is fine, including a full navigation. **There is no
live-update requirement here** — another client may change state, but this browser need only
refresh after its own action or an explicit refresh.

## Competing clients and uncertain outcomes

- Add `wallet-refresh`, a button on `/` that refreshes the balance and feed without clearing
  the pay form. **Latest refresh wins:** a delayed earlier read must not overwrite a later
  refresh, including when responses arrive out of order.
- Another client may spend the balance after this browser reads it. A refused payment shows
  `pay-error`, refreshes the balance/feed, and preserves all pay inputs. A request cancelled
  elsewhere while its pay button is visible must show `request-error` when payment is refused
  and refresh the request list so the stale pay button disappears.
- If a payment response is lost, including after `POST /payments` commits, show `pay-uncertain`
  (nonempty text), not `pay-error`. Keep the unchanged form retryable with the **same key and
  body**. Successful retry removes both error/uncertainty elements, refreshes the balance and
  feed, and moves money exactly once. Unknown outcomes are not confirmed rejections.

No background polling, live synchronization, or recovery across page reloads is required.
The same balance refresh rules apply to the available and held amounts introduced below.

## Existing clients after an upgrade

A stage-2 service must accept an export produced by the same team's stage-1 service. A
browser signed in before that export/import upgrade must remain signed in afterwards.
Existing pending requests remain payable through the request screen. A payment whose response
was lost before export remains retryable after import with the same body and key; the UI
must recover the original payment and refresh the imported balance. These requirements
apply when import completes between browser requests; migration during an in-flight request
is not required. No page reload or new screen is required. The form and pending retry
identity must survive the upgrade.

## Authorizations and captures

A payment may be **authorised** now and **captured** later, for the full amount or less. An
authorisation places a *hold* on the payer's wallet: it reserves money without moving it. Capturing
moves the money; a final capture also releases whatever was not captured. Nonfinal captures
keep the remainder held. An open authorisation expires and releases its remainder on its own.

1. The sum of all wallet `total` values always equals the total seeded by the last reset.
   A hold moves no money; payments, settlements and captures transfer money between wallets.
2. `available = total − held` must never be negative. Held funds cannot fund new payments,
   authorizations or settlement net debits. Captures may spend the money reserved for them.
3. Cumulative captures must not exceed the authorized amount. Each idempotent capture moves
   money once. A closed hold cannot be captured again.

The existing API changes as follows:

- `GET /me` keeps `balance`, and `balance` **equals `total`**. `available` and `held` are new
  fields beside it. With no open holds, `balance`, `total` and `available` agree and `held` is
  zero, and every earlier behaviour is unchanged.
- `POST /payments` remains an immediate transfer. It must not leave an intermediate hold
  or require a separate capture.
- Every `409 insufficient_funds` in stage 1 — on `POST /payments`,
  `POST /requests/{id}/pay` and settlements — is now evaluated against `available`.
  With no open holds, the result is unchanged.
- Paying a request remains immediate. Authorizing a request is out of scope.
- `POST /splits` is unchanged.
- There are now seven idempotent write paths: stage 1's five, authorizations and captures.
  The same replay rules apply independently to each.

## Model

The fixture gains a service-wide default lifetime and an `authorizations` array.

```json
{
  "currency": "EUR",
  "minor_units": 2,
  "authorization_ttl_seconds": 600,
  "users": [ { "id": "u_ada", "handle": "ada", "balance": 10000, "...": "..." } ],
  "authorizations": [
    { "id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
      "amount": 2000, "note": "deposit", "visibility": "public",
      "status": "open", "expires_at": "2026-09-24T13:20:00+00:00" }
  ]
}
```

- `authorization_ttl_seconds` applies to every authorisation created through the API. It defaults
  to 600 when omitted. If supplied, it must be a positive integer number of seconds.
  Seeded authorisations carry their own absolute `expires_at` instead.
- A user's seeded `balance` is still `total`. **`available` is derived, never seeded** — the service
  subtracts the seeded open holds itself.
- A sum of seeded unexpired open holds larger than that user's `balance` is a reset error:
  `422 validation_failed` from `POST /_test/reset`, changing nothing, exactly like a negative
  seeded balance.
- Seeded `status` is `open`, `captured`, `voided` or `expired`. Only `open` holds anything.
- An earlier fixture may omit `authorizations` altogether; omission means an empty list.

An authorization whose `expires_at` is at or before now is `expired` and holds no funds.
Reads and writes must reflect expiry even if no request occurred at the deadline.
`GET /authorizations` must show `status: "expired"`, and
`GET /me` must include the released remainder in `available`. Seeded expiry times are at
least an hour from reset time, in the past or future; newly created authorizations may
have shorter lifetimes.

