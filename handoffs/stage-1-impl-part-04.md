@vibhor15/nightshift-implementer
Rows: all stage-1 rows · Revision: head of main (base for stage-1) · Files: stage-1/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-1 HANDOFF PART 4/7 — SPECIFICATION stage-1.md (verbatim)

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
