@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: all rows A1-J3 of acceptance/stage-1.md (at b1636b3) · Revision: d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47 · Files: stage-1/ (whole folder; server.py and validation.py re-read) · Command: `band-work/verifier/stage-1/run.sh d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47 <out>` and the harness `--stage 1 --mode isolated --out ../band-work/checks/s1-ver-03` · Expected / actual: no difference found · Repro: n/a · Next: Architect

# VERDICT: PASS — stage 1, fix round 2, revision d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47

B5 is fixed, B1-B4 stay fixed, and the supplied checks and my whole saved list pass with no failure and no note.

## What I ran

1. Tree clean at d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47 before and after. `stage-1/` differs from 38f2970 in 5 files (213 insertions, 37 deletions): `server.py`, `validation.py`, `RUN.md` and two test files; the code was read.
2. B5 first: LM-05 (`GET http://[bad/health`, `http://[::1/me`, `http://[/` over a raw socket) -> 400 `malformed_request` with the JSON body; a well-formed absolute target -> 200. Fixed.
3. Clean build (`git archive` + `docker build --no-cache`) -> exit 0. Healthy after 0.34 s on the default port 8080, 0.34 s with `-e PORT=9123` and a mapping, 0.12 s on an internal no-outbound network with `--cpus 2 --memory 2g`. Memory after the run 18 MiB, no restart, no OOM.
4. RUN.md command exactly as written, from the clean export -> `/health` 200.
5. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/s1-ver-03` -> `stage 1: pass` (147 passed, none skipped or deselected), `stage 2: fail`, `claimed stage: 1 on the shipped checks`.
6. My whole saved list on the internal network under the limits: **94 checks, 94 pass, 0 fail, 0 error, 0 skipped, 0 notes**, 3,877 HTTP requests; plus EX-07 (export, remove the source containers, import into a fresh container, verify everything preserved): pass. That is the 86 checks derived from the specification before the first run, LM-01..05 (B1-B5) and NT-01..03 (N1, N2, N9). Cross-cutting over every response of the run: no 5xx, no request over 5 s (10 s for `/_test/*`), every 4xx with the §5 error body, every body `application/json; charset=utf-8`, every id a string of at most 64 characters, every timestamp RFC 3339 with a numeric offset.
7. Checks for the changed code only:
   - `probes4.py`, 44 probes, 43 pass. Eleven request targets (malformed absolute, `*`, authority form, no leading slash, `%zz`, NUL, empty and `%2F` id segments) -> never 5xx, 4xx with the JSON body; bad request lines (`HTTP/9.9`, one word, extra token, lower-case method, PROPFIND) -> 4xx with a status line and the JSON body; framing (negative, non-numeric and huge Content-Length, body shorter than Content-Length, bad and negative chunk sizes, non-UTF-8 body) -> 400/422, valid chunked and exact bodies -> 201; 30 requests on one keep-alive connection including after 4xx responses -> all correct; an idle connection is closed by the server after 30 s and a connection idle for 8 s is reused; zero-padded `limit`/`offset` (ten cases, up to 5000 zeros) -> by value. The one probe that did not match was my own expectation: a two-word request line `GET /me` is served as an ordinary request (200); the specification does not speak to it.
   - `probes3.py` from round 1 again, 80 probes, 80 pass (huge integer literals, canonical form, wrong-typed import values, protocol errors).
8. Implementer's own tests from the clean export: `python3 -m unittest discover -s tests -t .` -> Ran 55 tests, OK.
9. Stage boundary: the stage-2 supplied checks fail at their first test (`GET /` is 404; `stage-1/` has no web pages). Stage 1 is the first unit, so there are no earlier units' checks to repeat.

## Notes (do not block)

- **N3** scrypt cost is N=4096, r=8, p=1: a password-hashing function, so §6 is met; the cost is low by current guidance. No plaintext password appears in an export.
- **N4** Load figure from round 1 (not repeated): with 20,000 stored payments `GET /activity` took 7 ms, export 0.33 s (14.4 MB), import 0.47 s, memory 143 MiB. One global lock and list scans; no weakness seen at that figure.
- **N8** `HEAD` on any path gives 405 with headers only; the specification does not speak to HEAD.
- **N11** (new) The server now closes a connection that sends nothing for 30 s. A client that keeps a connection idle longer must reconnect; the supplied checks are unaffected. The specification states no idle time.
- **N12** (new) A two-word request line (`GET /me`, HTTP/0.9 style) is served as an ordinary request with an HTTP/1.1 response. No statement in the specification speaks to it.
- **N7** Maintainability: modules are small with one job each and RUN.md's table and limits section match the code. `statecodec.py` (256 lines) holds both fixture building and import validation and is the natural place to split in stage 2. `server.py` is now 151 lines in two clear phases; phase 1 answers every exception as 400, so a server-side fault in decoding would be reported as the client's. Feed and request order rely on insertion order rather than sorting by `created_at`; the two agree while the clock does not go backwards.
- N1, N2, N9, N10 of the earlier verdicts are fixed.

## Remaining risk I could not test

- The judged test set is larger than the shipped checks; I tested what the specification states.
- My client ran on the same 4-core host as the 2-vCPU container, so latencies on a slower judge host are not measured.
- Behaviour after an abrupt container restart was not tested (the specification says state need not survive).
- Points the specification leaves open are implemented as the Architect's [reading] rows say; if the hidden tests read them differently (for example the order of checks on a request with two errors, or shares when the caller is omitted from a split), they could fail there.

## Where things are

- `verification/stage-1/CHECKLIST.md` and this file, in the commit named in the room message.
- Scripts and logs outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-1/` (`runs/f2-repro.log`, `runs/f2-full.log`, `runs/f2-probes3.log`, `runs/f2-probes4.log`). Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s1-ver-03/`.
