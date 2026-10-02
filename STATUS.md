# Status — Tablekeeper dark-factory run

Dispatch received: 2026-10-02T20:27Z. Scope of this dispatch: stage 1 only.

| Unit | State | Accepted revision | BLOCK rounds | Elapsed |
|---|---|---|---|---|
| stage-1 | DONE | `eb1de488e1d191439f3607f1589d17e4fd0b1d5d` | 0 / 5 | 0h33 (accepted 2026-10-02T21:00Z) |

States: PLANNED, BUILDING, VERIFYING, BLOCKED, DONE.

Verifier verdict: PASS for `eb1de488e1d191439f3607f1589d17e4fd0b1d5d`, recorded in
`verification/stage-1/VERDICT.md` (verdict commit `9b907d17cbec9823bf75309ea47f5074cbcf6f21`,
which touches only `verification/stage-1/`). `stage-1/` is unchanged since `eb1de488`.

## Check results for the accepted revision

| Run | Mode | Result | Output |
|---|---|---|---|
| Supplied checks, Verifier | host | 120 / 120 passed, 0 failed/errors/skipped; stage 2 fails; `claimed stage: 1` | `band-work/checks/ver-01` |
| Supplied checks, Verifier | isolated | 120 / 120 passed, same zero counts; `claimed stage: 1` | `band-work/checks/ver-final-01` |
| Supplied checks, Architect (final) | isolated | 120 / 120 passed, 0 failed/errors/skipped; stage 2 fails; `claimed stage: 1` | `band-work/checks/arch-final-01` |
| Verifier's own list, port-mapped, `--cpus 2 --memory 2g` | — | 121 / 121; 5,338 requests, slowest 1.29 s, zero 5xx | `band-work/checks/ver-own-01`, `verification/stage-1/evidence/` |
| Verifier's own list, docker `--internal` network (no outbound) | — | 121 / 121; slowest 1.34 s, zero 5xx | same |
| Implementer's own suite | — | 29 / 29 (as reported by the Implementer) | `stage-1/tests/` |

## Log

- 2026-10-02T20:27Z — Task received. Spec `tablekeeper/spec/stage-1.md` and the supplied
  stage-1 checks read in full.
- 2026-10-02T20:32Z — Acceptance map written (`ACCEPTANCE-stage-1.md`, rows A1–M1, decisions
  X1–X10). Both seats confirmed in the room. Five-part handoff (`handoff/stage-1/`) sent to
  Implementer (build) and Verifier (prepare checks).
- 2026-10-02T20:40Z — Implementer committed `eb1de488` (Python standard library service,
  in-memory state, Docker) and handed it to the Verifier.
- 2026-10-02T20:58Z — Verifier PASS for `eb1de488` (first verdict; no BLOCK rounds).
- 2026-10-02T21:00Z — Architect confirmed `stage-1/` unchanged since `eb1de488`, ran the
  final isolated check (`arch-final-01`, 120/120, `claimed stage: 1`) and accepted the unit.

## Verifier notes (copied from the verdict; none blocking)

1. Maintainability: about 1,150 lines in 16 modules, matching the RUN.md module table. One
   global lock is correct and fast enough at the stated limit (slowest request 1.34 s with
   50 in flight), but it would serialise work beyond that limit.
2. `MAX_BODY` is 64 MiB and the body is read into memory. 50 such requests in flight would
   need about 3.2 GiB, more than the 2 GiB limit. The spec sets no body-size limit and no
   ordinary user sends that much.
3. A repeated query parameter uses its first value; the spec does not cover this.
4. A stale Authorization header on the public endpoints is ignored (check E8b, passed).

Remaining risk the Verifier could not test:

- The supplied checks are a partial sample; the full suite may probe orderings the spec
  leaves open (decisions X1/X4/X5).
- The cutoff was checked about one minute either side of the boundary, not to the second.
- DST was checked only for the transitions §9 lists, plus fixed offsets in four other zones.
- Load was tested at exactly 50 in flight, not beyond.
- Container restart was not tested; the spec does not require state to survive one.

Implementer judgement calls (listed in `stage-1/RUN.md`): float `party_size` → 422; a body
id longer than 64 characters → 422.
