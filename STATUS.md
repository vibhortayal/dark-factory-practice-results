# Run status

Run started: 2026-10-01T02:08Z. Track: pocketful. Acceptance maps: `acceptance/stage-N.md`.
Check output: `/home/ubuntu/nightshift-claude-run-2/band-work/checks/`.

| Unit | State | Accepted revision | Elapsed | Notes |
|---|---|---|---|---|
| stage-1 | DONE | `3e764a06d469734a17ac70f0eb70c47341859a1b` | 02:08Z → 02:35Z verdict (≈27 min); recorded 03:15Z | Verifier PASS on head; isolated harness 147/147 (`checks/s1-ver-iso-02`), stage-2 probe fails, claimed stage 1. First revision `e088cca` BLOCKed (F1: reset rejected large balances), fixed in `3e764a0`. Open advisory F2 (amount literals non-integral beyond double precision) is carried into stage 2 as map row K6 |
| stage-2 | DONE | `95f1446015263a7fb1bd5983adf3a627a97ab219` | 03:15Z → 04:23Z (≈68 min) | Verifier PASS on head (`checks/verdicts/stage-2-95f1446….md`); isolated harness stage 1 147/147, stage 2 35/35 (`checks/s2-ver-iso-02`), stage-3 probe fails, claimed stage 2. First revision `2ca222e` also PASSed but with three advisory observations (wallet vs stage-1 `/me`, retry identity on parsed body, list refresh discarding typed input); the Architect required fixes before acceptance (rows R13, N8, V10) |
| stage-3 | BUILDING | — | started 04:25Z | handed to Implementer (handoffs/stage-3, 13 parts). Revision `b97e12f` BLOCKed 04:57Z (F1: service clock runs ahead under load); routed back with row AC12. Revision `1c4e50a` BLOCKed 05:14Z (F1 fixed; F2: client-now instants refused as future); routed back with row AC13 |
| stage-4 | PLANNED | — | — | |

## Decisions

- Architecture (Architect, stage 1): one process, all state in memory, every state transition
  applied synchronously in a single thread so each request is serialisable and no balance is
  ever transiently negative; export `state` carries its own schema version for later upgrades.
  Reason: the spec allows ephemeral state, forbids runtime network, and demands atomicity under
  50 concurrent requests; a single-writer in-memory ledger gives that without lock design risk.
- Points the specification leaves open are resolved in the acceptance map rows marked CHOICE.
- Stage 1 accepted with advisory F2 open (stage-1 Verifier judged a held-back check for it
  unlikely); rather than reopen an accepted folder, the fix is required from stage 2 onward.
- Stage 2 map review against the shipped checks changed three rows before handoff: `/login`
  and `/signup` always render their forms even when signed in (L3); list containers on
  `/requests` and `/authorizations` are always in the DOM (Q1, V6); the authorise form is on
  both `/` and `/authorizations` because the spec does not place it (V2).
- Stage 2 UI: no framework, no build step, assets served from the image; reason: zero runtime
  dependencies already, no outbound network at run time, smallest surface to verify.
- Verdicts are also written by the Verifier to `checks/verdicts/stage-N-<hash>.md`, because room
  messages reach the Architect late while it is mid-turn; acceptance reads that file and the
  harness report for the same revision.
- Stage 2 was not accepted on its first PASS: with 65% of the graded suite held back and most of
  it browser-driven, the Verifier's three advisory observations were made requirements. Cost: one
  extra build-verify cycle (≈16 min).
- Stage 3 design: append-only revision and hold-event history beside the incrementally maintained
  current balances; every temporal read is a pure function of that history; knowledge is ordered
  by a sequence number rather than clock comparison; statement snapshots are stored parameters
  recomputed through the same function. Reason: frozen results cannot drift, constant memory per
  token, tokens exportable for the stage-4 upgrade.
