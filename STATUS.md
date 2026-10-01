# Factory status

Run started: 2026-10-01T19:05Z (dispatch). Run ended: 2026-10-01T20:42Z. Track: pocketful.

| Unit | State | Accepted revision | Fix rounds | Started | Finished | Elapsed |
|---|---|---|---|---|---|---|
| stage-1 | BLOCKED | none | 5 of 5 used | 2026-10-01T19:05Z | 2026-10-01T20:42Z | 1 h 37 min |
| stage-2 | PLANNED (not started: builds on blocked stage-1) | — | 0 | — | — | — |
| stage-3 | PLANNED (not started) | — | 0 | — | — | — |
| stage-4 | PLANNED (not started) | — | 0 | — | — | — |

Acceptance maps: `acceptance/stage-N.md`. Check output: `../checks/` (outside the repository).
Handoff and fix-request texts sent by the Architect: `../handoffs/s1/` (outside the repository).

## Stage 1: why it is blocked

No revision received a Verifier PASS within the five permitted fix rounds. The last reviewed
revision is `ee42fd2a387a3a6c51f3db6a6f432e2e5ee1ee70` (verdict BLOCK). One finding is open:

- Rows A6, A7; spec §2 "Concurrent requests: up to 50 in flight", "Per-request timeout: 5 s".
  50 concurrent `POST /payments` with a valid 506 KB body made of 2000 groups of 126 nested
  brackets all answer 413, but the slowest takes 5.28–5.67 s (4 to 7 of 50 over the limit, six of
  six runs, container run with `--cpus 2 --memory 2g --memory-swap 2g`). Cause named by the
  Verifier: `_OPEN_RUN_RE.search(structural)` in `parse_body` (server.py L71, L141-150) runs
  before the 16 KiB structure-length check. Suggested fix (not applied, not verified): apply the
  length check first, or use a plain byte search.

What the Verifier confirmed on that same revision: supplied checks in isolated mode after a
`--no-cache` build, `../checks/s1-verifier-06`: 147 collected / 147 passed / 0 failed / 0 errors /
0 skipped, claimed stage 1 (stage 2 suite fails, as it should); healthy with `--network none`;
Implementer's 24 own tests pass; 13,415 own assertions with no defect other than the finding
above; no 5xx; export/import across containers; idempotency on all five paths; memory flat at
about 33 MiB after 3,000 accepted 512 KiB requests.

Non-blocking notes left open by the Verifier (implementation limits, not spec contradictions, but
a hidden check expecting the exact spec result would fail): the 512 KiB body cap and 16 KiB
structure cap answer 413 for a 20,007-digit `amount` (spec: 422) and a 20,000-handle split (spec:
404); signup maximums (email 320, display name 1,000, password 1,024 characters) answer 422;
reset time is linear in users (2000 users: 7.5 s against the 10 s limit).

## Round history (stage 1)

| Round | Revision reviewed | Verdict | Findings |
|---|---|---|---|
| initial | 32a1948f13bd883c7d9d92fc8b1fbbee5a44e091 | BLOCK | huge JSON numbers answered 400; `limit=5%0A` accepted (regex `$`) |
| fix 1 | e047133c4a837b39cb4a9c413b5903cb16d65f8d | BLOCK | bodies nested 3400–10000 deep stall 50-way load (16–19 s) |
| fix 2 | 3ea47602c33682d86355c69b0f638198ce7fb782 | BLOCK | own export over 8 MiB refused (413); 8 MiB bodies take 5–8 s |
| fix 3 | 76ab4760f2f0e2d41398bd16b017e81eaabadf10 | BLOCK | 50 near-cap bodies of decimal numbers take up to 49.7 s |
| fix 4 | b039f347405e488fea7112848a877e94f3f80e6b | BLOCK | unterminated-string body freezes service (quadratic regex); OOM after about 1,780 at-cap requests |
| fix 5 | ee42fd2a387a3a6c51f3db6a6f432e2e5ee1ee70 | BLOCK | 50 bracket-heavy 506 KB bodies: slowest 5.28–5.67 s |

Each round fixed the findings of the round before; every new finding was in hostile-input
resource behaviour (§2 limits), not in the payments, requests, splits, feed, idempotency,
export/import or settlement rules.

## Architect's assessment of the factory failure

- Three of the five rounds were spent on regressions introduced by approach decisions the
  Architect made in the fix requests (arbitrary nesting depth in round 1, a single 8 MiB body cap
  in round 2, storing body text per idempotency record in round 4). Bounding the body size and
  structure up front, in the first handoff, would have avoided them.
- When the stop was issued the working tree held an uncommitted change to `stage-1/server.py`
  made by the Implementer after the fifth verdict. It is unreviewed and is not part of any
  reported revision.

## Log

- 2026-10-01T19:05Z dispatch received; stage-1 acceptance map written; handed to Implementer.
- 2026-10-01T19:16Z Implementer committed 32a1948; Verifier BLOCK; fix rounds 1–5 followed.
- 2026-10-01T20:42Z fifth fix round BLOCK; stage 1 recorded BLOCKED; seats told to stop; stages 2–4 not started.
