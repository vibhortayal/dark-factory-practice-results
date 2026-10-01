@vibhor15/nightshift-implementer
Rows: all stage-1 rows · Revision: head of main (base for stage-1) · Files: stage-1/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-1 HANDOFF PART 7/7 — FINAL PART — ACCEPTANCE MAP acceptance/stage-1.md (verbatim)

| Q3 | `amount: null` is treated as an invalid amount (422), a missing `amount` is 422. | §5: invalid `amount` values → 422; missing required field → 422. |
| Q4 | Paying a share-0 request succeeds (201) and creates a payment of amount 0. | §9 makes a 0 request legal and §8 pay has no amount rule of its own; the request exists and is payable by its payer. |
| Q5 | Seeded payments/requests without a timestamp in the fixture get a server-assigned `created_at` at reset; fixture order is treated as oldest-first. | Fixture format has no timestamp; a valid RFC 3339 value is still required. |
| Q6 | A non-pending decline/cancel by the wrong party is 403 (permission before state). | "Only the payer / only the requester" is the gate on the resource. |
