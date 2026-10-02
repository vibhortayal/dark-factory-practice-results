# Status

Run start: 2026-10-02T04:11Z. Track: pocketful. Acceptance maps: `acceptance/stage-N.md`.
Check outputs: `../checks/` (outside this repository).

| Unit | State | Accepted revision | Fix rounds (BLOCK verdicts) | Elapsed |
|---|---|---|---|---|
| stage-1 | BUILDING (fix round 2) | n/a | 2 | started 04:11Z |
| stage-2 | PLANNED | n/a | 0 | n/a |
| stage-3 | PLANNED | n/a | 0 | n/a |
| stage-4 | PLANNED | n/a | 0 | n/a |

## Log

- 04:11Z task received; stage-1 spec read; acceptance map written; both seats confirmed in room.
- 04:21Z Implementer reported 5493ad07335b7e273f76792f0280e184970f553d (147 supplied checks passed isolated, own 41 OK); complete handoff sent to Verifier.
- 04:58Z Verifier BLOCK #1 on 5493ad0: supplied checks 147/147 isolated (../checks/s1-ver-01), own list 584/595; eight Severity 2 findings (501 HTML on HEAD/OPTIONS/other methods; 500 on >4300-digit limit; 500 on array/object user reference in fixture; 500 on replay of deeply nested body; 500 on malformed absolute-form target; non-integral amounts such as 0.99999999999999999999 accepted; >4300-digit integer amount gives 400 instead of 422; import accepts invalid state). Routed to Implementer with notes N1-N3.
- 05:05Z Implementer reported 6c6d0a623fbe052d3edb56373e706450238865ea (fix round 1; 147/147 isolated in ../checks/s1-impl-final-02, own 50 OK); complete handoff sent to Verifier.
- 05:40Z Verifier BLOCK #2 on 6c6d0a6: findings 1-8 and notes N1-N4, N6, N7 confirmed fixed; supplied checks 147/147 isolated (../checks/s1-ver-02), own list 807/827; four new Severity 2 findings in the changed code (R1 number with a 19+ digit exponent gives 500; R2 replay with a non-integer number in an ignored field fails after export/import; R3 own export refused by import after a body nested 898-900 levels; R4 signup accepts control characters in email). Routed to Implementer with a map clarification on zero-padded query integers.

## Verifier notes (Severity 3 and 4)

From BLOCK #1 on 5493ad0 (stage 1):
- N1 (S3) `offset` longer than 4300 digits returns 500 on /requests and /activity.
- N2 (S3) 414/431 built-in responses (70 KB request line, 150 headers, 70 KB header) carry an HTML body.
- N3 (S3) chunked body announcing a chunk of 2^47 bytes or more returns 500.
- N4 (S4) non-HTTP request line or unsupported version gets the built-in HTML 400.
- N5 (S4) wrong method on a known path returns 405 `method_not_allowed`; code not in the specification, body shape right.
- N6 (S4) fixture handle `"ada\n"` accepted (`$` matches before a final newline).
- N7 (S4) replay through another spelling of the same path (`/requests/rq%5F1/pay`) is treated as a new request.
- N8 (S4) non-object body to /_test/import returns 422; map row D2 reads 400.
- N9 (S4) signup accepts an email containing spaces or a newline, and an empty `display_name`.
- N10 (S4) scrypt runs with N=4096; the specification states no cost.

After BLOCK #2 on 6c6d0a6: N1, N2, N3, N4, N6, N7 fixed; N9 partly (became finding R4); N5, N8, N10 stand by Architect decision. New:
- N11 (S4) `limit`/`offset` with leading zeros and more than 30 characters is treated as 10^30.
- N12 (S4) a replay writing a non-integer number in an ignored field differently (`1.50` then `1.5`) gives 409 although decision D-7 compares by value.
