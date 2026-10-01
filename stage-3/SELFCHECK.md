# Stage 3 self-check (row by row)

Evidence at the reported revision (`stage-3/tests` against the built image, `docker run --cpus 2 --memory 2g`):
`test_stage3_api` (35 tests: PT, ME, ST, CO, KA, SN, HH, UP, fuzz, concurrency, a 20k-payment history),
`test_api` + `test_concurrency` + `test_stage2_api` (the stage-1 and stage-2 suites, adapted only where stage 3
changes behaviour: `GET /statement` / `as_of` are no longer 404, authorizations carry `closed_at`), `test_browser`
(34 Playwright tests, unchanged UI). Supplied harness: `claimed stage: 3`. Real stage-1 (8e43652) and stage-2
(f8086da) containers were exported and imported into stage 3 by hand (see below).

| Rows | How checked | Result |
|---|---|---|
| B3.1 | Supplied suites 1+2 (147 + 35 checks) pass against stage 3; own stage-1/2 suites rerun; browser suite rerun | OK |
| B3.2 B3.3 | Dockerfile/RUN.md; `git diff f8086da -- stage-1 stage-2` empty | OK |
| B3.4 | Refund/batch-correction routes 404 (`UiRouting.test_no_stage4_surface`) | OK |
| B3.5 | `Fuzz` (odd query values for every temporal parameter, odd correction bodies incl. huge exponents and surrogates, every field of revisions/snapshots/authorizations/clock mutated in an export) | OK |
| B3.6 | `Scale.test_20k_payments`: reset of 20k seeded payments, 1500 mixed historical reads 50-way in ~1.2 s, a correction on the big history < 4 s, snapshot pages unchanged | OK |
| PT1-PT5 | `Timestamps` (microsecond strictly increasing instants, as_of at exactly a payment's `created_at` includes it and excludes the next one, seeded verbatim/default/future/invalid) | OK |
| ME1-ME8 | `Timestamps`, `KnownAt`, `Signups` (as_of validation, `%2B` and raw `+`, echo exactly, opening balance, sums conserved in every view) | OK |
| ST1-ST10 | `Statements` (arithmetic, order by effective time then id, half-open window, paging keeps balances, pages beyond the end, own private payments, captures once with links, holds not entries) | OK |
| CO1-CO15 | `Corrections`, `Concurrency` (success/increase/decrease/zero/same amount, validation boundaries, 401/403/404/422 linked, stale, replay after newer revisions, key reuse, insufficient_funds before historical_overdraft, combined movements at one instant, activity unchanged, revisions endpoint visibility, 50 concurrent corrections with one expected revision -> one 201) | OK |
| KA1-KA4 | `KnownAt` | OK |
| SN1-SN6 | `Snapshots` (frozen pages after payments, corrections, lifecycle actions; 422/404 cases; 40 snapshot versions all reproducible with bounded pinning; survive export/import per S3-6), mixed 48-way load | OK |
| HH1-HH7 | `Holds`, `Corrections.test_hold_makes_available_negative` | OK |
| UP1 UP2 | Real stage-1 and stage-2 container exports imported (accounts, token, lost-payment replay 200, statements, opening balances derived so balances are unchanged, captures/settlements immutable); `Upgrade.test_stage2_shape_export`; harness `previous_api` | OK |
| UP3 | `Upgrade.test_stage3_round_trip` (views, replays, snapshots identical after import; 9 invalid states -> 422, destination unchanged) | OK |
| UP4 | `test_browser` upgrade test against the stage-3 image | OK |

Real-container upgrade output: stage-1 import 204, balance 9650 before and after, statement opening 10500, deltas -500,-300,-50,
closing 9650; replay of the lost payment 200; correction 201. Stage-2 import 204, held 300 / available 9250 preserved, capture
accounted as a payment entry.

Design: per payment an append-only revision list; per user a payment index and a cached timeline (effective-time order with
running balances) invalidated per change; snapshots store resolved parameters (caller, window, `known_at` capped at the read
instant) and reuse the frozen timeline of that version (bounded pinning; rebuilt from the log otherwise); holds keep creation,
capture, release and deadline events; instants are integer microseconds, strictly increasing server instants, imported
timestamps verbatim. Opening balance = seeded ending balance minus the net of original seeded payments (0 for signups; derived
on import). `historical_overdraft` walks every effective/event boundary at or after the changed instants for both users.

Known incomplete: none. Readings beyond S3-1..S3-11: a seeded payment without `created_at` gets the reset instant; seeded
authorizations without `created_at` are created at the reset instant (+ index microseconds); for a seeded closed authorization
`closed_at` is its `expires_at` (expired) or its `created_at`, and it holds nothing in any view; stage-2 imports
reconstruct captures from the capture payments' instants and the void time is approximated by the last capture or creation.
