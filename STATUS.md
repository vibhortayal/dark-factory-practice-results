# Status

Run start: 2026-10-02T04:11Z. Track: pocketful. Acceptance maps: `acceptance/stage-N.md`.
Check outputs: `../checks/` (outside this repository). Times are UTC, taken from commit and
check-report timestamps.

| Unit | State | Accepted revision | Fix rounds (BLOCK verdicts) | Elapsed |
|---|---|---|---|---|
| stage-1 | DONE | 43ecb3c9d24e89b47ea00c98828bf3999bb0a5cc | 3 | 04:11Z to 05:57Z (1 h 46 min) |
| stage-2 | DONE | 4a9c357bc8cc5c71df5634b15dd9527f145be2d5 | 2 | 05:57Z to 09:43Z (3 h 46 min) |
| stage-3 | BUILDING | n/a | 0 | started 09:43Z |
| stage-4 | PLANNED | n/a | 0 | n/a |

## Log

- 04:11Z task received; stage-1 spec read; acceptance map written (832ebf1, 04:13Z); both seats confirmed in room; stage-1 handoff sent to both seats.
- 04:20Z Implementer committed 5493ad07335b7e273f76792f0280e184970f553d (147 supplied checks passed isolated, own 41 OK); complete handoff sent to Verifier.
- ~04:58Z Verifier BLOCK #1 on 5493ad0: supplied checks 147/147 isolated (../checks/s1-ver-01), own list 584/595; eight Severity 2 findings (501 HTML on HEAD/OPTIONS/other methods; 500 on >4300-digit limit; 500 on array/object user reference in fixture; 500 on replay of deeply nested body; 500 on malformed absolute-form target; non-integral amounts such as 0.99999999999999999999 accepted; >4300-digit integer amount gives 400 instead of 422; import accepts invalid state). Routed to Implementer with notes N1-N3.
- 05:02Z Implementer committed 6c6d0a623fbe052d3edb56373e706450238865ea (fix round 1; 147/147 isolated in ../checks/s1-impl-final-02, own 50 OK); complete handoff sent to Verifier.
- ~05:17Z Verifier BLOCK #2 on 6c6d0a6: findings 1-8 and notes N1-N4, N6, N7 confirmed fixed; supplied checks 147/147 isolated (../checks/s1-ver-02), own list 807/827; four new Severity 2 findings in the changed code (R1 number with a 19+ digit exponent gives 500; R2 replay with a non-integer number in an ignored field fails after export/import; R3 own export refused by import after a body nested 898-900 levels; R4 signup accepts control characters in email). Routed to Implementer with a map clarification on zero-padded query integers.
- 05:20Z Implementer committed df4b305f070db63ec64f768222aeeffeba9081ba (fix round 2; 147/147 isolated in ../checks/s1-impl-final-03, own 58 OK); complete handoff sent to Verifier.
- ~05:34Z Verifier BLOCK #3 on df4b305: R1-R4, N11, N12 confirmed fixed; supplied checks 147/147 isolated (../checks/s1-ver-03), own list 882/884; one Severity 2 finding S1 (import accepts a state whose idempotency `response` holds a non-integer number; export and replay then return 500). Routed to Implementer.
- 05:38Z Implementer committed 43ecb3c9d24e89b47ea00c98828bf3999bb0a5cc (fix round 3; 147/147 isolated in ../checks/s1-impl-final-04, own 61 OK); complete handoff sent to Verifier.
- ~05:56Z Verifier PASS on 43ecb3c9d24e89b47ea00c98828bf3999bb0a5cc (head of main at that time, tree clean): supplied checks isolated 147 collected / 147 passed / 0 failed / 0 skipped (../checks/s1-ver-04), stage-2 probe on stage-1/ fails 0 of 35 as required; own list 900/900 under --cpus 2 --memory 2g on an internal network, 19,389 requests, no status >= 500, slowest request 0.423 s, slowest reset/export/import 0.414 s, first healthy response 0.43 s. No Blocker, Severity 1, 2 or 3 finding open. **Stage 1 accepted at 43ecb3c.**
- 05:57Z stage-2 spec read; acceptance map acceptance/stage-2.md written; stage-2 handoff sent to both seats.
- 06:33Z Implementer committed 3ba327652d0fa62e939ae0d773bd845c96b58a6d (stage 2; supplied checks isolated 147 + 35 passed in ../checks/s2-impl-final-02, stage-3 probe fails; own API 24 OK, stage-1 own suite 61 OK, own browser suite 28 OK); complete handoff sent to Verifier.
- ~07:35Z Verifier BLOCK #1 (stage 2) on 3ba3276: supplied checks isolated 147/147 and 35/35 (../checks/s2-ver-01), stage-3 probe fails; own list 1,338 check executions all passed after the finding was isolated; visual rows V1-V4 accepted from screenshots. One Severity 2 finding: with the page's API calls answered by the stage-1 service (the pre-upgrade situation of rows M2/M4), `/` throws a script error (`BigInt(undefined)` on the missing `available`) and shows no balance, no refresh button and no feed; `/authorizations` throws too. Routed to Implementer with notes T2-T5 to fix.
- 07:57Z Implementer committed 54ab7a9c086d6280402df0d09faca3b10949a5c5 (stage 2 fix round 1; supplied checks isolated 147 + 35 in ../checks/s2-impl-final-03; own API 25, stage-1 list 61, browser 34 OK); complete handoff sent to Verifier.
- ~08:29Z Verifier BLOCK #2 (stage 2) on 54ab7a9: finding 1 and notes T2-T5 confirmed fixed; supplied checks isolated 147/147 and 35/35 (../checks/s2-ver-02), stage-3 probe fails; own list 1,411 of 1,412; container logs empty (the 4 unexplained lines did not recur). One Severity 2 finding: the delayed first `/me` read of the page load overwrites a later `wallet-refresh` (balance goes back from 75.00 to 100.00 EUR). Routed to Implementer.
- 08:52Z Implementer committed 4a9c357bc8cc5c71df5634b15dd9527f145be2d5 (stage 2 fix round 2, UI read ordering only; supplied checks isolated 147 + 35 in ../checks/s2-impl-final-04; own API 25, stage-1 list 61, browser 38 OK); complete handoff sent to Verifier.
- ~09:42Z Verifier PASS on 4a9c357bc8cc5c71df5634b15dd9527f145be2d5 (head of main at that time, tree clean; stage-1/ unchanged since 43ecb3c): supplied checks isolated suite 1 147/147, suite 2 35/35, 0 skipped (../checks/s2-ver-03), stage-3 probe on stage-2/ fails as required; own list 1,441 check executions all passed under --cpus 2 --memory 2g on an internal network with Chromium at 375 and 1280 px, 29,764 API requests, no status >= 500, slowest request 0.47 s, slowest reset/export/import 0.43 s, container logs empty. No Blocker, Severity 1, 2 or 3 finding open. **Stage 2 accepted at 4a9c357.**
- 09:43Z stage-3 spec read; acceptance map acceptance/stage-3.md written; stage-3 handoff sent to both seats.

## Verifier notes (Severity 3 and 4)

Stage 1, open at acceptance (all Severity 4, kept by Architect decision; no Severity 3 open):
- N5 (S4) wrong method on a known path returns 405 `method_not_allowed`; the code is not in the specification, the body shape is right.
- N8 (S4) non-object JSON body to /_test/import returns 422; map clarification C-1 accepts 400 or 422.
- N10 (S4) scrypt runs with N=4096; the specification names scrypt and states no cost.

Stage 1, raised and fixed during the fix rounds: N1 (S3) long `offset` gave 500; N2 (S3) 414/431
built-in HTML bodies; N3 (S3) huge chunk size gave 500; N4 (S4) built-in HTML 400 for non-HTTP
lines; N6 (S4) fixture handle `"ada\n"` accepted; N7 (S4) replay through another spelling of the
path; N9 (S4) email with whitespace/control characters accepted; N11 (S4) zero-padded query
integers over 30 characters; N12 (S4) respelled non-integer number in an ignored field gave 409.

Stage 1, remaining risk stated by the Verifier (not findings): the supplied checks are a sample;
single process behind one lock measured only up to 500 users / about 300 payments; import proves
each candidate state by a second export and validation (largest timed: 60 users, 300 payments);
a login overlapping a reset was not examined; wallets above 2^53 not exercised.

Stage 2, from BLOCK #1 on 3ba3276 (all Severity 4; no Severity 3):
- T1 (S4) a seeded authorisation without `status` is accepted and treated as `open`. Kept (Architect: lenient reading, no statement requires the member).
- T2 (S4) capture without any body returns 400; `{}` works and request pay accepts a missing body. To fix in fix round 1.
- T3 (S4) while the first read of `/` is pending the loading state replaces the wallet, so `wallet-refresh` is absent. To fix in fix round 1.
- T4 (S4) `Accept` matched as a substring (`text/htmlx` gets HTML). To fix in fix round 1.
- T5 (S4) `/favicon.ico` answers 404. To fix in fix round 1.
- T6 (S4) at 375 px a 17-digit amount breaks inside the number; text exact, no sideways scroll. Kept.
- T7 (S4) forms lower-case and trim a typed handle and drop empty split entries. Kept.
- Unexplained observation by the Verifier: 4 log lines matching `traceback|internal error` in one stage-2 container of the first run, text not captured, no request received a 5xx, not reproduced in a full re-run. Implementer asked to look for the cause.

Stage 2, after BLOCK #2 on 54ab7a9: T2, T3, T4, T5 fixed. Open, all Severity 4, kept by Architect decision: T1, T6, T7 (T7 now also: `0015.50` and ` 15.00 ` accepted as 15.50 and 15.00). No Severity 3 open.

Stage 2, open at acceptance (all Severity 4; no Severity 3 open): T1, T6, T7 kept by Architect decision; T8 (new at PASS) on `/`, while the first read of `/me` has not returned, the wallet frame and `wallet-refresh` are shown but the pay, request and authorise forms are not. T8 is listed as work for stage 3.
Stage 2, remaining risk stated by the Verifier (not findings): supplied stage-2 checks are a sample (35 of about 100); how the graded upgrade checks put a signed-in browser in front of the stage-1 service is not visible (the method of map row M2 was used); single process and lock measured to 0.47 s per request at 50 in flight with up to 500 users and a few hundred records; the page's 15 s hung-read path was exercised only on the first stage-2 revision; the 4 unexplained log lines of the first stage-2 run never recurred in two full rounds with saved logs; V1-V4 accepted from screenshots of the first revision (markup and style sheet unchanged since).
