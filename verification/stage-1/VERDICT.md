# Verdict — Pocketful stage 1 — PASS

Rows: all of acceptance/stage-1.md (A1-J6) · Revision: 172a3180c731a310e00e403ea1c4990a4a78b5d4 ·
Files: stage-1/ (Dockerfile, RUN.md, app/, tests/) inspected; verification/stage-1/ written ·
Command: `python3 deliver.py --dir stage-1 --out <dir>` (runs `checks.py`), harness `--stage 1` normal and `--mode isolated`,
Implementer's `python3 -m unittest discover -s tests -t .`, RUN.md command verbatim ·
Expected / actual: no difference found · Repro: n/a · Next: Implementer reports the revision to the Architect.

**PASS** for revision 172a3180c731a310e00e403ea1c4990a4a78b5d4.

## What was run

Working tree was clean at the reported revision before and after (`git status --short` empty, HEAD = 172a318…).
The check list (`CHECKS.md`) was derived from the specification before reading the Implementer's code or tests.

| Run | Command | Result |
|---|---|---|
| Delivery checks | `python3 deliver.py --dir …/result/stage-1 --out …/verifier/stage-1/out-r1` | 10 of 10 passed (`run-1/deliver.log`) |
| Own HTTP check list | `checks.py --base http://<ip>:8080 --base2 http://<ip>:9200 --kill-cmd 'docker kill nsv-stage1-a'`, against containers started with `--cpus 2 --memory 2g` on a docker `--internal` network (no outbound) | 58 of 58 passed, 2883 HTTP requests, 0 responses ≥ 500, 0 transport errors (`run-1/checks.log`, `run-1/checks.json`) |
| Supplied checks | `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/verifier-s1-r1` | `stage 1: pass`, 147 passed (stage 2 line is `fail`: no stage-2 folder exists yet) |
| Supplied checks, isolated | same with `--mode isolated --out ../band-work/checks/verifier-s1-r1-isolated` | `stage 1: pass`, 147 passed |
| Implementer's tests | `python3 -W error -m unittest discover -s tests -t .` in a `git archive` copy of the revision | Ran 60 tests, OK |
| RUN.md verbatim | `docker build -t pocketful-stage-1 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-1` in the copy | built, `curl localhost:8080/health` → `{"status":"ok"}` |

Delivery checks: clean `docker build --no-cache`; no PORT → healthy on 8080 through a port mapping in 0.42 s;
`-e PORT=9123` with mapping → healthy in 0.40 s; `--network none` → still running after 8 s; start to healthy under
2 vCPU / 2 GiB 0.20 s (limit 60 s); neither container OOM-killed or restarted.

Measured at the stated limits: 50 requests in flight, slowest mixed request 0.036 s, slowest of 50 concurrent logins
0.393 s (limit 5 s); reset of a 60-user fixture 0.590 s (limit 10 s); export and import under 10 s.

Next-unit check: the route table (`app/router.py`) holds exactly the stage-1 endpoints. The paths the stage-2
specification adds (`/authorizations`, `/authorizations/{id}/capture`, `/authorizations/{id}/void`) return 404
`not_found`, and no such code exists in `stage-1/app`. Stage 1 is the first unit, so there are no earlier units' checks.

E7 by code read: `app/passwords.py` uses salted scrypt (n=4096, r=8, p=1) with constant-time compare; the export
contains only `pw_hash` (checked: neither fixture nor signup password appears in the export text).

## Findings

None blocking.

## Notes (do not block)

1. A settlement entry with a non-string handle (`"from_handle": 5`) gives 422 `validation_failed`, not 400
   `malformed_request`. §5 (wrong JSON type → 400) and §11 (malformed batch shape → 422) both fit; the specification does
   not settle it.
2. `POST /_test/import` with a body that is JSON but not an object (`[]`, `"x"`, `7`) gives 422 `validation_failed`; the
   other POST endpoints give 400 `malformed_request` for a non-object body. §10 names 400 only for invalid JSON, so both fit.
3. Paying a zero-amount request created by a split returns 201 with an `amount: 0` payment. The specification is silent;
   this matches the Architect's recorded choice.
4. Choices the specification does not speak to, observed and consistent: emails are matched case-insensitively; a wrong
   method on a known path gives 405 `method_not_allowed` in the standard error body; a non-operator calling
   `POST /settlements` gets 403 before the body and the idempotency key are looked at; signup without `display_name` is 422.
5. Maintainability (one read): small modules with one job each, RUN.md maps them, no nested repository, no
   dependencies beyond the standard library. Three small things: (a) the idempotency claim uses the raw request path,
   so `/payments/` (trailing slash, which the router accepts) is a different claim from `/payments`; (b) scrypt cost
   n=4096 is low for production, though the specification only names the function; (c) `__pycache__` folders left in the
   working folder by local test runs are ignored by git but would be copied into an image built from that folder by
   `COPY app` — harmless.
6. Load beyond the stated limits was not applied. State, tokens and idempotency records live in memory and are never
   pruned; largest state exercised was 60 users / 60 seeded payments plus about 400 writes per fixture.

## Remaining risk I could not test

- The harness states it ships only a portion of the judging tests; the hidden remainder may read the open choices in
  notes 1, 2 and 4 differently.
- Timing was measured on this host (4 cores, container limited to 2 vCPU / 2 GiB), not on the judge's machine.
- Behaviour over a long run (memory growth of the in-memory state) was not measured.
