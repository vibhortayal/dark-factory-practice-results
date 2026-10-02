Rows: C19, D2, I8 (fix); all rows A–L re-run · Revision: 9f7cba3c0bba5b5b747ea078240a6aeba45c6abc · Files: stage-1/app/fixture.py, stage-1/app/store.py (diff read); verification/stage-1/CHECKLIST.md, verification/stage-1/VERDICT-round-2.md · Command: verify.sh up|checks|down on a clean export of the revision; supplied harness in host and isolated mode · Expected / actual: reset with a wrong-typed fixture field → 400 malformed_request; now 400 · Repro: `curl -s -X POST $B/_test/reset -H 'Content-Type: application/json' -d '{"currency":"EUR","minor_units":2,"users":"x"}'` → 400 malformed_request · Next: Architect.

## VERDICT: PASS for 9f7cba3c0bba5b5b747ea078240a6aeba45c6abc

Finding 1 of round 1 is fixed, and the whole list passes with nothing failed, skipped or errored.

### Finding 1 (round 1): fixed

- Reproduction repeated: `users: "x"` now gives `400 malformed_request`.
- FX-07 passes for all 19 wrong-typed cases, including the ones the revised row C19 adds (`payments: [5]`, `requests: ["x"]`, a non-string id inside a payment or request, `minor_units: null`).
- Value errors still give 422: negative `balance`, `minor_units: 7`, `users` missing, duplicate handle, handle not matching the pattern, unknown user id, unknown request status.
- State is untouched after every rejected reset.

### Row I8 as revised: met

- EX-09 passes: a state member of the wrong container type (`payments: {}`, `tokens: []` and the like) gives 422 with the destination unchanged.
- An unchanged export imports with 204, in the same container and in a second one.

### What I ran

1. **Repository:** tree clean before and after. HEAD is 92be0f89010a9e610088a5093052b941f020ea36, the Architect's record commit on top of the revision; `git diff 9f7cba3 HEAD -- stage-1` is empty, so the stage-1 tree checked is exactly the revision's. My own containers were built from `git archive 9f7cba3`.
2. **Supplied checks**, from the kickoff checkout:
   - `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/ver-3` → stage 1 pass: 147 collected, 147 passed, 0 failed, 0 errors, 0 skipped, 0 deselected.
   - Same with `--out ../band-work/checks/ver-4 --mode isolated` → stage 1 pass, 147 passed.
   - The harness's stage-2 probe still fails against this folder, as it should.
3. **Delivery:** `docker build --no-cache` from the clean export succeeds. Healthy after 0.43 s with `-e PORT=9123`, and on 8080 without `PORT`. The container stays up with `--network none`. The suite ran against two containers on a docker `--internal` network, each with `--cpus 2 --memory 2g`: no OOM kill, no restart, 156 MiB used, no traceback in the logs. After `docker restart`: healthy in 0.44 s, reset and login work. The RUN.md command was run as written in round 1; RUN.md and the Dockerfile are unchanged in this revision.
4. **Own checks:** 136 = 129 scripted + 7 whole-run assertions, 136 pass. 7,736 requests, no 5xx, every error body well-formed, every response `application/json; charset=utf-8`. Slowest ordinary request 0.30 s (login, 50 concurrent); slowest test-control request 1.54 s (reset with 200 users and 500 payments). 1,500 mixed operations at 50 in flight: balances conserved, no negative balance, slowest request 0.05 s.
5. **Diff read** (d2d184d → 9f7cba3, `fixture.py` and `store.py`): the fix is a `_typed` helper applied to every fixture member the loader reads, plus a container-type check on the seven array members of an imported state. One check added for the changed code: EX-09.

### Notes (do not block)

- **N7, new:** a seeded payment or request with a non-string `note` (`note: 5`, `note: null`) in a reset fixture now gives 400; before the fix it gave 422. In the same object a bad `visibility` and a string `amount` still give 422. §5 says "non-string `note` values (including `null`) … are 422", listed as an endpoint-specific field rule; reset names no rule for it, so I read it as open either way, the same as the seeded `amount` in row C19. Returning 422 would match both readings and the neighbouring fields.
- **N1, size:** `GET /activity` builds the caller's whole visible list under the global lock on every call. Measured in round 1: 50 concurrent feed reads took at most 0.71 s with 20,000 stored payments and 3.46 s with 100,000 (limit 5 s). The specification sets no limit on stored records. That code is unchanged.
- **N2:** the HTTP server sets no read timeout; a client that sends fewer bytes than its `Content-Length` keeps one thread waiting indefinitely. No statement in the specification covers it.
- **N3:** closed by this revision (row I8).
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
