# Run status

Run started: 2026-10-01T02:08Z. Track: pocketful. Acceptance maps: `acceptance/stage-N.md`.
Check output: `/home/ubuntu/nightshift-claude-run-2/band-work/checks/`.

| Unit | State | Accepted revision | Elapsed | Notes |
|---|---|---|---|---|
| stage-1 | BUILDING | — | — | handed to Implementer 2026-10-01T02:2xZ |
| stage-2 | PLANNED | — | — | |
| stage-3 | PLANNED | — | — | |
| stage-4 | PLANNED | — | — | |

## Decisions

- Architecture (Architect, stage 1): one process, all state in memory, every state transition
  applied synchronously in a single thread so each request is serialisable and no balance is
  ever transiently negative; export `state` carries its own schema version for later upgrades.
  Reason: the spec allows ephemeral state, forbids runtime network, and demands atomicity under
  50 concurrent requests; a single-writer in-memory ledger gives that without lock design risk.
- Points the specification leaves open are resolved in the acceptance map rows marked CHOICE.
