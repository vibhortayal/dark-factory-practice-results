@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: A11 (blocking); D7 (note) · Revision: 38f2970c0c1395ee1338ef6326948332609a45de · Files: stage-1/pocketful/server.py (read only) · Command: `curl -s -i --request-target 'http://[bad/health' http://127.0.0.1:$PORT/` · Expected / actual: a 4xx with the §5 error body / `500 internal_error` · Repro: the curl command above, no token needed · Next: Implementer

# VERDICT: BLOCK — stage 1, fix round 1, revision 38f2970c0c1395ee1338ef6326948332609a45de

B1, B2, B3 and B4 of the first verdict are fixed, and so are notes N1 and N2. The supplied checks and my
whole saved list pass. One new blocking finding, in code this fix changed.

## Blocking finding

**B5 — a request whose target is an absolute URL with a malformed host answers 500.** Map row A11.
Specification §5: "Requests must not produce 5xx responses, including under concurrent load."
Map row A11 (at b1636b3): "No request yields a 5xx ... Responses produced by the HTTP layer itself ... also carry the §5 JSON error body."
Repro (no token, any running container of this revision):
`curl -s -i --request-target 'http://[bad/health' http://127.0.0.1:$PORT/`
Actual: `HTTP/1.1 500 Internal Server Error` `{"error": {"code": "internal_error", "message": "internal error"}}`; container log `internal error: ValueError('Invalid IPv6 URL')`.
Expected: a 4xx with the §5 error body (400 `malformed_request`).
Same for `http://[::1/me` and `http://[/`. A well-formed absolute target (`http://ok.example/health`) answers 200.
This is a regression of the fix: revision 03b5470 answered the same request `400 malformed_request`. Cause: `server.py` `_handle` calls `urlsplit(self.path)`, which raises ValueError for an unbalanced `[` in the host part; the fix replaced `except (ValueError, UnicodeError)` by `except RecursionError`, so the error now reaches the catch-all 500. In my scripts as LM-05.

## Earlier findings, each repeated first

| Finding | Reproduction | Result on 38f2970 |
|---|---|---|
| B1 reset with wrong-typed ids | LM-04, six fixtures | 422 `validation_failed`, state unchanged — fixed |
| B2 `limit` of 4301 digits | LM-01, `/requests` and `/activity` | 422 `validation_failed` — fixed |
| B3 `amount` of 4301 digits | LM-02, payments, requests, splits, settlements | 422 `validation_failed` — fixed |
| B4 `Idempotency-Key` of 65520 / 70000 characters | LM-03 | 422 `validation_failed` with the JSON body — fixed |
| N1 unknown field nested 990 / 2000 levels | NT-01 | 201 — fixed |
| N2 `offset` of 4301 digits | NT-02, both list endpoints | 200 with an empty page — fixed |

## What I ran

1. Tree clean at 38f2970c0c1395ee1338ef6326948332609a45de before and after; `stage-1/` differs from 03b5470 in 8 files (196 insertions, 36 deletions), all read.
2. Clean build (`git archive` + `docker build --no-cache`) -> exit 0. Healthy after 0.34 s on the default port, 0.34 s with `-e PORT=9123`, 0.12 s on the internal no-outbound network with `--cpus 2 --memory 2g`. Memory after the run 18.6 MiB, no restart, no OOM.
3. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/s1-ver-02` -> `stage 1: pass` (147 passed, none skipped), `stage 2: fail`, `claimed stage: 1 on the shipped checks`.
4. My whole saved list (the 86 original checks, LM-01..04, NT-01..02) on the internal network under the limits: **92 pass, 0 fail, 0 error, 0 notes**, 3,871 HTTP requests; EX-07 (import into a fresh container with the source removed): pass. Cross-cutting over every response: no 5xx, nothing over 5 s (10 s for `/_test/*`), every 4xx with the error body, every body `application/json; charset=utf-8`.
5. Checks for the changed code only (`probes3.py`, 80 probes): 78 pass, 2 fail.
   - Protocol-level refusals over a raw socket (PROPFIND, 70 kB request line, 150 headers, `Content-Length: abc`, bad chunk size, valid chunked body): correct. Fail: the absolute target with a malformed host (B5). Fail: `GET /me HTTP/9.9` (note N10).
   - The 18-digit rule in `query_int`: limit of 18, 19 and 4301 digits -> 422; offset of 18, 19 and 4301 digits -> 200 empty page.
   - Huge integer literals: amount of 4000, 4001 and 5000 digits, negative, `1e999999`, a 5000-digit fraction -> 422; a 5000-digit number in an unknown field -> 201 and its replay 200; a 5000-digit fixture balance -> 422, state intact.
   - The rewritten canonical form: same value in another key order with `1.0` for `1` -> 200 same body; eight changed variants (list order, `true` for `1`, `null` for `""`, `"3"` for `3`, renamed or removed member, strings that look like structure) -> 409 each.
   - Import validation: thirteen wrong-typed values in an otherwise unchanged export -> 422 each, destination unchanged; the unchanged export -> 204 and replay 200.
6. Added to the list: LM-05 (B5) **fails**; NT-03 gives note N9. Totals on this revision: 94 checks, 93 pass, 1 fail, 0 error, 0 skipped.
7. Implementer's own tests from the clean export: `python3 -m unittest discover -s tests -t .` -> Ran 47 tests, OK.
8. Stage boundary unchanged: stage-2 supplied checks fail (no web pages in `stage-1/`).

## Notes (do not block)

- **N9** (new) A `limit` or `offset` written with more than 18 digits through leading zeros is treated as 10^18 whatever its value: `limit=0000000000000000050` (19 digits, value 50) gives 422, and `offset=0000000000000000000` (19 digits, value 0) gives an empty page instead of the first one. Size no ordinary user sends: 19 or more digits. Stripping leading zeros before the length test would cover it.
- **N10** (new) A request line with an unsupported HTTP version (`GET /me HTTP/9.9`), like the one-word request line the Implementer reported, is answered with the JSON error body but no status line or headers, because `http.server` treats it as HTTP/0.9. No statement in the specification speaks to it.
- **N3** scrypt cost N=4096, r=8, p=1: a password-hashing function, so §6 is met; low cost by current guidance. Unchanged.
- **N7** Maintainability, unchanged in substance: `statecodec.py` is now about 255 lines with two jobs (fixture building, import validation). `server.py` gained the protocol-error mapping and is still under 110 lines. RUN.md documents the new size limits.
- **N8** `HEAD` gives 405 with headers only. Unchanged; RUN.md now says so.
- Import no longer copies the parsed document before loading it; that is safe because the document is built per request and not kept elsewhere.

## Remaining risk I could not test

- The judged test set is larger than the shipped checks.
- My client ran on the same 4-core host as the 2-vCPU container; latencies on a slower judge host are not measured.
- Behaviour after an abrupt container restart was not tested (the specification says state need not survive).
- I did not search for further ValueError sources beyond reading every statement inside `_handle`'s try block; `urlsplit` is the only one I found that the new handler does not cover.

## Where things are

- `verification/stage-1/CHECKLIST.md` (updated: map change b1636b3, LM-05, NT-03) and this file, in the commit named in the room message.
- Scripts and logs outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-1/` (`runs/f1-repro.log`, `runs/f1-full.log`, `runs/f1-probes3.log`, `runs/f1-lm05.log`, `probes3.py`). Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s1-ver-02/`.
