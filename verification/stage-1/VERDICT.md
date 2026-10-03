# Stage 1 — Verifier verdict, round 3: PASS

Rows: all stage-1 rows D1–S2 · Revision: a8301bb9379977851db1c64ff468cbddc30011ff · Files: stage-1/ (whole folder; diff since 0487a51: app/snapshot.py, app/auth.py, tests/test_service.py) · Command: `bash verification/stage-1/run.sh a8301bb9379977851db1c64ff468cbddc30011ff <evidence-dir>` plus harness host and isolated · Expected / actual: all checks pass / all checks pass · Repro: n/a · Next: Architect

Tree clean, HEAD = a8301bb. Image built `--no-cache` from `git archive` of the revision.

## Findings from earlier rounds
- F1 (reset wrong JSON type → 400): fixed, C3.4b–f pass.
- F2 (moves: cutoff before field errors): fixed, MV5.2e–f pass.
- F3 (seeded `party_size` "4" / true → 422): fixed, C3.5a–b pass.

## What was run
| What | Result |
|---|---|
| Clean `docker build --no-cache` of the exported `stage-1/` | OK |
| Start on an internal (no outbound) network, `--cpus 2 --memory 2g`, `-e PORT=9000` | healthy after 0.34 s; outbound unreachable |
| Start without `PORT` | healthy on 8080 |
| `-e PORT=9123 -p 127.0.0.1:19123:9123` | 200 `{"status": "ok"}` |
| RUN.md command as written (run in round 1; RUN.md command unchanged since) | `/health` 200 |
| Harness `--stage 1 --mode host --out ../band-work/checks/verifier-s1-r3-host` | stage 1: 120 passed, 0 skipped |
| Harness `--stage 1 --mode isolated --out ../band-work/checks/verifier-s1-r3-isolated` | stage 1: 120 passed, 0 skipped |
| Stage-2 suite on stage-1 (inside both harness runs) | fails (1 failed, UI route `/`), as row S1 requires; `/` and `/lookup` are 404 |
| Implementer's tests `python -m unittest discover -s tests` | 24 OK |
| Own probes: whole saved list (`CHECKS.md`, `probe.py`) | 392 checks, 392 pass, 0 fail |
| scrypt change | hashes are `scrypt$4096$8$1$<salt>$<digest>`; 1000 users with one password → 1000 distinct hashes; no plaintext in export; login 200, wrong password 401, login after import 200 |

No 5xx in any probe response, every request under 5 s (reset/export/import under 10 s), no
overlapping confirmed bookings after load, container not OOM-killed (194 MiB), empty stderr.

## Notes (not blocking)
1. Reset time grows with fixture users: 502 users 3.67 s, 1000 users 7.37 s under `--cpus 2`
   (limit 10 s); it would pass the limit near 1350 users. The spec states no fixture size.
2. scrypt cost is n=2^12, r=8, p=1 — a real password-hashing function as §6 requires, at a low
   work factor chosen for reset speed.
3. After a rejected reset the previous state stays in place (spec does not say).
4. Spec is silent on, and the service does: signup without `display_name` → 422; `x@localhost`
   accepted; emails case-insensitive; `PATCH {}` → 200 unchanged; wrong method → 405
   `method_not_allowed`; body over 8 MiB → 400; unparseable body without a token → 401.
5. PATCH error order follows the Architect's amended map (404 → body 400 → cancelled → cutoff →
   field validation); §8 itself states no order.
6. Maintainability: small modules with one job each, one global lock, shared validators,
   precedence documented in RUN.md and `bookings.py`. Nothing to change.

## Remaining risk not tested
- Exact cutoff equality (`now == starts_at − cutoff`) cannot be hit with real time; tested about
  1 h either side.
- The harness says its shipped suite is only part of the judging suite.
- Load ran on a 4-CPU host with the container limited to 2 CPUs, not on a 2-vCPU machine.
