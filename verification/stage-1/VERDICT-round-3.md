Rows: C19, D4 (change); all rows A–L re-run · Revision: 76497f32a1e1cf9015d7b696827cfed4dfe81fcd · Files: stage-1/app/fixture.py (diff read); verification/stage-1/CHECKLIST.md, verification/stage-1/VERDICT-round-3.md · Command: verify.sh up|checks|down on a clean export of the revision; supplied harness in host and isolated mode · Expected / actual: reset with a seeded `note` that is not a string → 422 validation_failed; now 422 · Repro: reset fixture with `payments[0].note = null` → 422 validation_failed · Next: Architect.

## VERDICT: PASS for 76497f32a1e1cf9015d7b696827cfed4dfe81fcd

The change for the revised row C19 is in, and the whole list passes with nothing failed, skipped or errored.

### Row C19 as revised: met

- FX-08 passes. In a reset fixture, a seeded payment or request gives 422 `validation_failed` for:
  - a `note` that is a number, boolean, `null`, array or object, or longer than 200 characters;
  - a `visibility` that is not `public` or `private` (seeded payment);
  - an `amount` that is a string, boolean, `null`, fraction or negative.
- State is untouched after every rejected reset.
- An omitted `note` and `visibility` take the defaults (`""`, `public`), and a 200-character seeded note is kept.
- FX-07 still passes: the 19 wrong-typed cases of round 1 stay 400 `malformed_request`.

### What I ran

1. **Repository:** HEAD is the reported revision; tree clean before and after.
2. **Supplied checks**, from the kickoff checkout:
   - `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/ver-5` → stage 1 pass: 147 collected, 147 passed, 0 failed, 0 errors, 0 skipped, 0 deselected.
   - Same with `--out ../band-work/checks/ver-6 --mode isolated` → stage 1 pass, 147 passed.
   - The harness's stage-2 probe still fails against this folder, as it should.
3. **Delivery:** `docker build --no-cache` from a clean `git archive` export succeeds. Healthy after 0.43 s with `-e PORT=9123`, and on 8080 without `PORT`. The container stays up with `--network none`. The suite ran against two containers on a docker `--internal` network, each with `--cpus 2 --memory 2g`: no OOM kill, no restart, 152 MiB used, no traceback in the logs. After `docker restart`: healthy in 0.44 s, reset and login work. The RUN.md command was run as written in round 1; RUN.md and the Dockerfile are unchanged since.
4. **Own checks:** 137 = 130 scripted + 7 whole-run assertions, 137 pass. 7,804 requests, no 5xx, every error body well-formed, every response `application/json; charset=utf-8`. Slowest ordinary request 0.35 s (signup, 50 concurrent); slowest test-control request 1.49 s (reset with 200 users and 500 payments). 1,500 mixed operations at 50 in flight: balances conserved, no negative balance, slowest request 0.05 s.
5. **Diff read** (9f7cba3 → 76497f3, `fixture.py` only in `app/`): one `_note` helper, used for the seeded payment's and request's `note`. One check added for the changed code: FX-08.

### Notes (do not block)

- **N7:** closed by this revision.
- **N1, size:** `GET /activity` builds the caller's whole visible list under the global lock on every call. Measured in round 1: 50 concurrent feed reads took at most 0.71 s with 20,000 stored payments and 3.46 s with 100,000 (limit 5 s). The specification sets no limit on stored records. That code is unchanged.
- **N2:** the HTTP server sets no read timeout; a client that sends fewer bytes than its `Content-Length` keeps one thread waiting indefinitely. No statement in the specification covers it.
- **N4:** scrypt cost is N=4096, r=8, p=1, lower than common guidance, chosen for reset time. The specification names the function, not a cost.
- **N5, maintainability:** small modules with one job each; RUN.md's module table matches the code. Minor points:
  - the idempotency record's `status` and the stored `splits` are written but never read outside export;
  - `fixture.build` reserves user indexes, then clears and rebuilds them;
  - `handlers_settlements` imports `parse_transfer` from `handlers_payments`;
  - timestamps have one-second resolution, so feed order rests on insertion order.

### Remaining risk not tested

- The judge's full check set is larger than the supplied sample.
- Behaviour above 50 requests in flight, and a wall clock that steps backwards.
- Import was exercised only with states this service produced, plus my mutations of them.
