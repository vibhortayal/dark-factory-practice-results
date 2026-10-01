@vibhor15/nightshift-implementer STAGE 2 HANDOFF — addendum 2 (one more acceptance-map row; parts 1–9 and addendum 1 stand). No reply needed; fold it into the build and into your Verifier handoff.

New row in `acceptance/stage-2.md`, section T:

| # | Requirement | Check |
|---|---|---|
| T14 | Internal bookkeeping only (never in any API response or in the UI): each authorization keeps, in the service state and therefore in the export, the instant it was voided (if it was), and each capture is linked to its payment (whose `created_at` is the capture instant). Reason: a later stage must account for imported authorizations over time, and an instant that was not recorded cannot be recovered. No `closed_at` or other new response field in stage 2 | O: export inspection + response-shape assertions |

In practice: when `POST /authorizations/{id}/void` first voids an authorization, store that instant on the internal record (same clock and precision as T13); a repeated void does not change it. Captures already create payments, so `payment_ids` plus each payment's `created_at` is enough. Do not add any field to the authorization or payment response shapes for this.
