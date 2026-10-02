@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier

Rows: all · Revision: n/a · Files: n/a · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer builds, Verifier prepares checks.

STAGE 1 HANDOFF — PART 5 of 5 — FINAL PART

## Acceptance map, continued: sections H–L (end of map)

## H. Money and rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| H1 | Shares are whole units, sum to amount, differ by ≤ 1; extra units go to the first participants in given order: (1000,3)→334,333,333; (1,3)→1,0,0; (10,3)→4,3,3; (999,3)→333,333,333; (5,5)→1,1,1,1,1 | Table-driven + property sweep over amounts/n |
| H2 | Different handle order gives the extra unit to a different person | Same people, permuted |
| H3 | A share of 0 is legal and still creates a request (amount 0, `pending`); a 0-amount split request can be paid (moves 0), declined, cancelled without error | (1,3) split, then pay the 0 request |
| H4 | Shares independent of previous splits; after paying splits in full, balances sum to seeded total | Many splits paid, C1 check |

## I. Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{…}}`; atomic read-only snapshot | HTTP; export during writes is internally consistent (balances sum to total) |
| I2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically REPLACES state (not merge); repeating import does not duplicate | Export → mutate → import → state equals export; import twice |
| I3 | Import works in a different fresh container (no dependency on source process, files, volume, port, address) | Export from container A, import into new container B, compare all reads |
| I4 | Preserved: accounts, hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests (status, payment_id), splits' requests, ids, timestamps, operator permissions, settlement membership | Compare `/me`, `/activity`, `/requests` for all users before/after; old tokens still work |
| I5 | Preserved: all completed idempotent request bodies and original responses → replays after import return 200 original body; changed body → 409; failed keys remain reusable | Each of five write paths |
| I6 | Balances are not regenerated or replayed (payments not re-applied to net balances) | Balances identical after import |
| I7 | Import removes all previous destination data and credentials (old destination tokens → 401) | HTTP |
| I8 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid state → 422 `validation_failed`; destination unchanged in all these cases | HTTP, then verify old state intact |
| I9 | Reset clears everything including imported state; ids generated after import do not collide with imported ids | HTTP |
| I10 | Export/import/reset complete within 10 s at ordinary populated state | Time them |

## K. Atomic net settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| K1 | No token → 401; authenticated non-operator → 403 `forbidden`; operator needs idempotency key (F rows) | HTTP |
| K2 | Operator may move money across any wallets (not only their own); permission grants no access to others' requests (pay/decline/cancel → 403; `GET /requests` unchanged) or private activity | HTTP |
| K3 | `transfers` has 1..32 objects: 1 and 32 OK; 0, 33, missing, non-array, non-object element → 422 `validation_failed` | Boundary |
| K4 | Each entry uses payment rules: amount (G4/D4), note (≤200, default `""`, verbatim), visibility (default public) → 422; unknown handle (from or to) → 404; from == to → 422 `self_payment`; unknown entry fields ignored | Per-entry parametrised |
| K5 | Entry errors take precedence in input order and before insufficient funds: first bad entry decides the error | Batch with entry 0 unknown handle + entry 1 invalid amount → 404; reversed → 422; bad entry + unaffordable → entry error |
| K6 | Affordable iff every wallet's balance after ALL transfers is nonnegative (net): chain A→B→C where B starts at 0 succeeds; else 409 `insufficient_funds` | Net-chain and cycle cases |
| K7 | All-or-nothing: failure moves nothing, creates no payments, claims no key (key reusable) | Balances, feed, key reuse after failure |
| K8 | 201 body: `settlement_id`, `committed_at`, `payments` in input order; each member is an ordinary payment with `settlement_id` = batch id, `request_id` null, `created_at` == `committed_at` (same for all); non-members expose `settlement_id: null` everywhere | HTTP |
| K9 | Members follow ordinary feed visibility (private member hidden from third parties and from operator if not party; visible to its parties); the settlement response itself contains every member | `/activity` as each party |
| K10 | Replay → 200 with original complete response; different body → 409; concurrency per F9; conservation C1/C2 under concurrent settlements + payments | HTTP + race |
| K11 | Reset replaces operators; export/import preserves operators, settlement membership and retry responses | With I rows |

## L. Architect decisions where the specification is silent or two rules meet

These are the readings the band builds and verifies against. Reason given for each.

| Row | Decision | Reason |
|---|---|---|
| L1 | Check order on the five idempotent paths: (1) auth → 401; (2) `/settlements` only: operator → 403; (3) key absent/empty → 400 `missing_idempotency_key`; (4) key > 255 → 422; (5) body parse / not an object → 400 `malformed_request`; (6) claimed key: same body → 200 replay, different → 409 reuse; (7) field types and field validation (400/422); (8) handle lookups → 404; (9) self → 422 `self_payment`/`self_request`; (10) state checks (403 not payer, 409 not pending, 409 insufficient funds) | §7 fixes (6) before (7)–(10); the rest follows §5/§6 with cheapest-first ordering |
| L2 | For pay/decline/cancel on a request: unknown id → 404, then caller role → 403, then status → 409, then funds → 409. Any existing request gives 403 to every non-permitted caller (also third parties) | §8 tables: "caller is not the request's payer → 403", "Unknown request → 404" |
| L3 | A handle value that is a string but matches no existing user (any content, incl. `""`, uppercase, invalid characters) → 404 `not_found`; lookups are exact, no case folding or trimming | Endpoint rule "No user has that handle → 404" is the more specific rule (§5 "unless an endpoint specifies a different error") |
| L4 | Handle field of a non-string type → 400; `participant_handles` not an array or with a non-string element → 400; settlement `transfers` container shape (missing, not array, size 0 or > 32, element not an object) → 422; inside an entry, non-string handle → 400, missing handle → 422 | §5 wrong-type rule; §11 "malformed batch shape is 422" overrides it for the batch container |
| L5 | Idempotency body equality: numbers compare by numeric value (`1000` ≡ `1000.0` ≡ `1e3`); objects ignore key order; everything else exact, including unknown fields | §7 "same JSON value after parsing"; §4 says those spellings are the same amount |
| L6 | `POST /requests/{id}/pay`, decline and cancel with a zero-length body: pay treats it as `{}`; decline/cancel never read the body | Body is optional-content on pay; decline/cancel define no body |
| L7 | "Characters" (note 200, password 8, handle truncation 20, key 255) are Unicode code points | Only reading under which emoji notes behave as users expect |
| L8 | Signup: `email`, `password`, `display_name` required strings; email valid iff exactly one `@` with non-empty local and domain parts; emails compared exactly as given; order: types → missing → email format → password length → `email_taken` → `handle_taken` | §6 table order; no normalisation is stated |
| L9 | Seeded payments/requests get `created_at` = reset time; fixture array order is creation order (later = newer). Ties in `created_at` are broken by creation sequence, newest first, so pagination is deterministic. Seeded requests have `payment_id: null` | Fixture carries no timestamps; §8 says same-second order is unspecified |
| L10 | Unknown route or unsupported method → 404 `not_found` with the error body | §5 "Every 4xx … carries this body" |
| L11 | Request bodies are parsed as JSON regardless of the request `Content-Type` header | Spec defines no content-type rejection |
| L12 | Payment objects always include `settlement_id` (null unless a settlement member), in every representation (`/payments`, pay, `/activity`, settlement, replays) | §11 "nonmembers expose null for that field" |
| L13 | Password hashing cost must be chosen so that reset of 200 seeded users finishes within 10 s and 50 concurrent logins each finish within 5 s on 2 vCPU, without blocking other requests past their timeout | §2 limits + §6 hashing rule |

--- END OF ACCEPTANCE MAP · END OF HANDOFF (FINAL PART 5 of 5) ---
Implementer: build stage-1/ now, self-check every row, commit, hand the full revision to the Verifier. Verifier: prepare your check list and scripts from the specification; no verdict and no reply until a committed revision is handed to you.
