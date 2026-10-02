# Factory status

Run started: 2026-10-01T21:14Z (human dispatch). Run ended: 2026-10-02T00:25Z. Track: pocketful.

| Unit | State | Accepted revision | Fix rounds | Started | Finished | Elapsed |
|---|---|---|---|---|---|---|
| stage-1 | BLOCKED | none | 5 of 5 used | 2026-10-01T21:14Z | 2026-10-02T00:25Z | 3 h 11 min |
| stage-2 | PLANNED (not started: builds on stage-1) | — | 0 | — | — | — |
| stage-3 | PLANNED (not started) | — | 0 | — | — | — |
| stage-4 | PLANNED (not started) | — | 0 | — | — | — |

Nothing was accepted. `stage-1/` is in the repository at its last revision
`09358e2b31176e2b8889e27539f167d8745e539f`; it builds, and the supplied checks pass on it in
isolated mode (147 of 147, `claimed stage: 1`), but the Verifier's verdict on it is BLOCK, so it is
not an accepted unit.

Acceptance map: `acceptance/stage-1.md`. Handoff text: `handoffs/stage-1/`.
Check output (outside the repository): `../checks/` — `s1-impl-*` (Implementer harness runs),
`s1-verifier-*` (Verifier harness runs), `arch-probe-s1/` and `arch-gate-s1/` (Architect probes).

## Open finding that blocks stage-1 (Verifier, on 09358e2)

Import accepts values that reset rejects (spec §10 "an invalid state give 422 validation_failed
without changing the destination"; §1 invariant 2; §3.4 ids at most 64 characters; rows K8, F9, A11).
Take an export, set `state.requests[0].amount = -100000`, import → 204; paying that request then
returns 201 with a negative amount and drives a balance negative. Also accepted: negative or 10^30
amounts on stored payments/requests, 1000-character ids and token keys, counters of 10^100 (the next
generated id is over 64 characters). Cause: `validate_state` in `stage-1/app/service.py` checks types
and key sets but not ranges or lengths. Not fixed: the five fix rounds were used up.

## Stage-1 revisions and verdicts

Every Verifier verdict was BLOCK. The supplied isolated check passed 147/147 with `claimed stage: 1`
on every revision the Verifier ran.

| Fix round | Revision verified | Findings (all routed to the Implementer) |
|---|---|---|
| initial | 2bafe2e | login racing reset gives live token / 500; deep JSON nesting 500; reset 500 on invalid fixture; import invalid-state handling; integers over 4300 digits; large offset rejected |
| 1 | c66eb9f | login overlapping an import of the same account returns 401 |
| 2 | 75b8d54 | idempotency compares numbers lossily (over-long integers, huge floats, 2^53+1 vs its float form) |
| 2 | 1bef6b4 (withdrawn before the verdict arrived) | one very long number stalls every client and OOM-kills the container; import accepts unrepresentable numbers then export 500; numbers still compared as doubles |
| 3 | c85a1e7 (withdrawn before the verdict arrived) | large array bodies stall every client past 5 s; import/export finding as above |
| 4 | 205f609 | 50 concurrent 2 MiB array bodies OOM-kill the container |
| 4 | deb24e1 (withdrawn before the verdict arrived) | number cache leaks about 2 MiB per request until OOM; 50 concurrent 1 MiB float bodies take 17.8 s; forgeable canonical stand-in object |
| 5 | c187beb (withdrawn before the verdict arrived) | number cache leak; capacity estimate undercounts escaped strings (134 MiB export that import refuses); forgeable stand-in |
| 5 | 5085e8d (withdrawn before the verdict arrived) | capacity undercount only |
| 5 | 09358e2 (Architect-gated, final) | import accepts out-of-range amounts, over-long ids and unbounded counters |

Unverified intermediate revision: bd0b644 (tree was dirty; the Verifier did not start).

## How the rounds were counted (Architect decision, open to challenge)

A fix round is one Architect fix request and the revisions made in response to it. Handoffs and
withdrawals repeatedly crossed in the room, so the Verifier completed runs on revisions that had
already been superseded; I folded those findings into the round in progress instead of opening a new
round. Counted strictly by Verifier verdicts on fix revisions, the limit of five was reached at
205f609. I announced in the room that the verdict on the gated revision 09358e2 would be final for
round 5; it was BLOCK, so the unit is recorded as blocked and later stages were not started.

## Decisions recorded by the Architect

- D-1..D-8 in `handoffs/stage-1/00-task.md` (error precedence, wrong-type handling, exact amounts).
- Operating envelope (the specification names neither status): API bodies over 128 KiB or 16,384
  JSON separators → 413; state over a 40 MiB export-size budget → 429 `capacity_exceeded`;
  reset/import bodies up to 64 MiB. Reason: the specification requires 2 GiB / 5 s / 50 in flight and
  no 5xx, which a finite service can only guarantee inside stated limits. Documented in
  `stage-1/RUN.md`.
- Password storage: scrypt once per distinct password per reset plus per-user HMAC; work factor
  steps down from n=2^14 to n=2^10 as the number of distinct fixture passwords grows; more than 4000
  distinct passwords in one fixture → 422. Reason: the 10 s reset limit.
- Hand-over protocol after four revisions moved under a running verification: candidate branch,
  Architect gate, Verifier idle line, single fast-forward, frozen repository until the verdict.

## Log

- 2026-10-01T21:17Z acceptance map and handoff committed (c6e8ea6); handoff sent in six parts.
- 21:24Z Implementer reported 2bafe2e. 21:36Z BLOCK, round 1. 21:48Z BLOCK on c66eb9f, round 2.
- 21:55Z–22:26Z rounds 2–4: verdicts on 75b8d54, 1bef6b4, c85a1e7, 205f609 as tabled above.
- 22:39Z Architect probe of deb24e1: 50×1 MiB float bodies 23.8 s; 3000-user reset 10.15 s; 142 MB
  export; 10 concurrent exports OOM-killed the container. Round 5 (operating envelope) requested.
- 23:13Z Architect probe of 5085e8d: those four failures gone.
- 2026-10-02T00:10Z Architect gate passed on candidate 09358e2 (103 unit tests, isolated harness
  147/147 claimed stage 1, capacity/import/keep-alive/password/memory probes).
- 00:24Z Verifier BLOCK on 09358e2 (import value ranges). Stage-1 recorded BLOCKED; run ended.
