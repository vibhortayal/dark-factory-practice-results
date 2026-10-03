# Verifier check list — stage 1 (Pocketful)

Derived from `pocketful/spec/stage-1.md` clause by clause, before any revision existed and
before reading the supplied tests. Acceptance-map rows in brackets. Scripts live beside this
file; `run.sh <revision>` builds, starts and runs everything; `pytest` files are named per section.

Legend: **strict** = spec states it, a miss is a finding. **soft** = the spec leaves it open
(map decision D-n); a deviation is recorded in `notes.jsonl`, not failed.

Universal (every HTTP call made by any check, recorded in `violations.jsonl`, asserted in `test_zz_universal.py`):
- U1 no status >= 500 (§5 "Requests must not produce 5xx") [A6]
- U2 each request <= 5 s; reset/export/import <= 10 s (§2, §10) [A5, C8, I7]
- U3 every 4xx/5xx body is `{"error":{"code":str,"message":str}}` (§5) [D1]
- U4 every response with a body is `application/json; charset=utf-8`; 204 has no body (§3.4) [A7]
- U5 every `created_at`/`committed_at` is RFC 3339 with explicit offset (§3.4) [A8]
- U6 every `*_id` value is null or a string of 1..64 chars (§3.4) [A10]
- U7 every `amount`/`balance` in a response is a JSON integer (§1, §4) [B4]

## A. Delivery and runtime (run.sh + test_a_runtime.py)
- A1.1 `stage-1/` has Dockerfile, RUN.md, source; no nested `.git`; tree clean at revision (§2)
- A1.2 clean clone at the revision, `docker build --no-cache` of `stage-1/` succeeds (§2)
- A1.3 the command in RUN.md, followed literally from the clean clone, builds and starts a healthy service (§2)
- A2.1 `docker run -e PORT=<p> -p <p>:<p>` → /health 200 via the mapping (so listens on 0.0.0.0:$PORT) (§2, §3.1)
- A2.2 run without PORT, `-p <h>:8080` → /health 200 (default 8080) (§3.1)
- A3.1 whole own suite runs against a container on a `--internal` network (no outbound), `--cpus 2 --memory 2g` (§2)
- A3.2 supplied harness, `--mode isolated` (§2)
- A4.1 time from `docker run` to first 200 `/health` <= 60 s; body exactly `{"status":"ok"}` (§3.2)
- A4.2 after `docker restart`: healthy again <= 60 s and reset works (§2 disk ephemeral)
- A5.1 container stays up, never OOM-killed / restarted during the suite; memory stays under 2 GiB (§2)
- A9.1 unknown body fields ignored on signup, login, payments, requests, pay, splits, settlements, reset (§3.4)
- A9.2 unknown query params ignored on /me, /requests, /activity, /health and on POST paths (§3.4)
- A11.1 out-of-scope routes are absent (deposits, top-ups, withdrawals, cards, bank, users/search, admin balance, verify, password reset, refresh, roles) (§1, §4, §6)
- A11.2 supplied stage-2 suite does not fully pass on `stage-1/` (task: none implementing a later stage early)
- A12 review: no third-party product code/schemas (§ preamble)

## B. Invariants (test_b_invariants.py)
- B1.1 sum of balances == seeded total after every burst below (§1.1)
- B2.1 50 concurrent payments of 300 from a 10000 wallet: exactly 33 × 201, 17 × 409 `insufficient_funds`, final 100; concurrent `/me` polls never < 0 (§1.2)
- B2.2 two pending requests of 800 against a 1000 wallet paid concurrently: one 201, one 409 insufficient (§1.2)
- B3.1 50 concurrent pays of one request, distinct keys: one 201, 49 × 409 `request_not_pending`; money moved once (§1.3)
- B3.2 same, one key: one 201, 49 × 200 same body; money moved once (§1.3, §7)
- B4.1 balances near 2^53 stay exact (2^53-1 reachable exactly); minor_units 0 and 3 (§4 arithmetic range)
- B5.1 failed payment (insufficient, self, unknown, invalid) leaves balances and both feeds unchanged (§8)
- B6.1 cycle A→B→C→A, 50 in flight × 4 rounds: all 201, exact balances, no hang (§1, §5)
- B6.2 A↔B opposite directions, 25+25 in flight: all 201, exact balances
- B7.1 mixed load, 50 in flight (payments, requests, pays, splits, settlements, reads): no 5xx, conservation, no negative

## C. Reset and fixture (test_c_reset.py)
- C1.1 reset → 204 empty body, no auth needed (§3.3)
- C1.2 after reset: old tokens 401, old accounts cannot log in, signed-up users gone, old payments/requests gone, old idempotency keys are first use, old operator not operator (§3.3)
- C1.3 five resets in a row, each fully effective (§3.3)
- C2.1 fixture without `payments`/`requests`/`settlement_operator_ids`; with empty arrays (§4, §11 default [])
- C2.2 JPY/0 and BHD/3 fixtures: `/me` and payment `currency`, `minor_units` (§4)
- C2.3 unknown fields in the fixture are ignored (§3.4)
- C2.4 fixture ids of 64 chars kept as given (§3.4)
- C2.5 fixture amounts written `2500.0` / `1e4` accepted as integral (§4) — soft if rejected with 4xx
- C3.1 every seeded user logs in at once (§4)
- C4.1 balances equal the fixture; seeded payments not replayed (§4)
- C5.1 negative balance → 422 `validation_failed`, nothing changed (old token, balance, feed) (§4)
- C6.1 unparseable body → 400 `malformed_request`; non-object body → 400 (soft 422); state unchanged (§5)
- C6.2 `minor_units` 1 / 5 / "2"; missing `users`, `currency`, `minor_units`; duplicate user id / handle / email; handle `ADA` / 21 chars / empty; payment or request naming an unknown user; unknown operator id; request status `open`; payment visibility `friends`; payment amount -5; balance 10.5; balance "100" → 4xx (422, or 400 for a wrong type), never 5xx/204, state unchanged (§4, §5)
- C7.1 seeded payments: public visible to all, private only to its two parties; ids, handles, amount, note, visibility as seeded; `request_id` null, `settlement_id` null (§4, §11)
- C7.2 seeded requests: visible to their two parties only, status as seeded; pending one can be paid / declined / cancelled; seeded paid/declined/cancelled → pay 409 `request_not_pending`; seeded declined → decline 200; seeded cancelled → cancel 200 (§4, §8)
- C8.1 reset with 60 users <= 10 s, logins work (§2)

## D. Errors (test_d_errors.py)
- D1.1 unknown route → 404 `not_found` envelope; wrong method → 4xx envelope (§5)
- D2.1 unparseable body → 400 `malformed_request` on signup, login, payments, requests, pay, splits, settlements, import (§5)
- D2.2 non-object body (`[]`, `"x"`, `1`, `null`) → 400 (soft 422) on the same paths
- D2.3 wrong JSON type: `to_handle` 5, `payer_handle` 5, `participant_handles` "ada", `participant_handles` [1], signup `email` 5 / `password` 12345678 / `display_name` 5 → 400 `malformed_request` (§5)
- D3.1 missing required: `to_handle`, `amount` (payments); `payer_handle`, `amount` (requests); `amount`, `participant_handles` (splits); `email`, `password`, `display_name` (signup); `email`, `password` (login) → 422 (§5)
- D4/D5 amount matrix on payments, requests, splits, settlement entry: valid `1`, `1000`, `1000.0`, `1e3`, `1000000000`, `1E9`; 422 for `0`, `-1`, `1.5`, `"100"`, `true`, `false`, `null`, `1000000001`, `1e10`, `[]`, `{}`, `0.5`, `1e30`; `1e400` → 4xx (§4, §5, §8)
- D4.2 note: 200 chars ok, 201 → 422, 200 emoji ok (soft), 201 emoji → 422; `null`, `5`, `true`, `[]`, `{}` → 422; on payments, requests, splits, settlement entry (§5, §8)
- D4.3 visibility `PUBLIC`, `friends`, `""`, `null`, `1`, `true`, `[]` → 422 on payments, pay, settlement entry; omission → `public` (§5, §8)
- D6/D7 on /requests and /activity: `limit` 1, 200 ok; 0, 201, -1, abc, 1e9, 1e1, 4.0, +4, %2B4, empty → 422; `offset` 0, 5, 100000 ok; -1, 1.0, abc, +1, 1e0, empty → 422; defaults 50 / 0 (§5, §8)
- D7.2 `direction=sideways`, `status=open`, `status=PENDING` → 422 on /requests; ignored on /activity (§8, §3.4)
- D8.1 key absent → 400 `missing_idempotency_key`; empty → 400; 255 chars → 201; 256 → 422; on all five write paths (§5, §7)
- D9.1 no header / `Bearer bogus` / `Basic x` / `Bearer` / raw token without scheme → 401 `unauthenticated` on /me, /payments, /requests (GET, POST), pay, decline, cancel, /splits, /activity, /settlements; 401 wins over missing key and bad body (§5, §6)
- D10.1 request content types `application/json` and `application/json; charset=utf-8` both accepted; other content types, HEAD, OPTIONS never 5xx (§3.4, §5)
- D11.1 pay/decline/cancel on unknown id, 65-char id, odd id → 404 `not_found` (§8)
- D11.2 decline and cancel work with no body and with an Idempotency-Key present (§8)

## E. Authentication (test_e_auth.py)
- E1.1 signup → 201 `{user_id, display_name, token}`; `/me` balance 0, fixture currency; receives a payment and a request at once (§4, §6)
- E2.1 derived handle: `A.B+c@x.io`→`a_b_c`; `mary-ann@…`→`mary_ann`; 25-char local part → first 20; `UPPER9_x@…`→`upper9_x`; `jürgen@…`→`j_rgen`; body `handle` ignored (§4)
- E3.1 same email again → 409 `email_taken`; seeded email → 409 `email_taken` (§6)
- E4.1 `a.b@x.io` then `a_b@y.io` → 409 `handle_taken`, login with it → 401; collision with a seeded handle → 409 `handle_taken` (§6)
- E5.1 password 7 chars → 422, 8 → 201; emails `nodomain`, `@x.io`, `a@`, `` → 422 (§6)
- E5.2 (map clarification 2, fix round 1) signup email containing whitespace or a control character → 422; empty `display_name` accepted
- E6.1 login → 200 same shape; wrong password / unknown email → 401 `unauthenticated` (§6)
- E7.1 two logins + signup token all valid at once; tokens distinct (soft) (§6)
- E7.2 50 concurrent logins each <= 5 s, all 200; 20 concurrent signups of one email: one 201, rest 409 (§2, §6)
- E9.1 export text holds no plaintext password of a seeded or signed-up user (§6); review of hashing function
- E10.1 handles stay the same across operations and import (§4)

## F. Idempotency (test_f_idem.py), on each of the five paths
- F1.1 first use → 201 (§7)
- F2.1 replay → 200, same JSON value; no further state change (balances, feed, request list) (§7)
- F2.2 replay with other key order and whitespace → 200 (§7); replay with `1e3` for `1000` → soft
- F2.3 replay through another token of the same user → 200 (§7 scoped to the user)
- F2.4 replay after the resource changed: request cancelled; request paid; payer drained; split's requests paid → 200 original body (§7)
- F3.1 same key, different body → 409 `idempotency_key_reuse`; pay `{}` vs `{"visibility":"public"}` → 409 (§7, §8)
- F4.1 two users, same key → both 201, independent (§7)
- F5.1 same key and body on /payments, /requests, /splits → each 201; same key on two request ids' pay → both 201 (§7)
- F6.1 key of a 422 / 404 / 409-insufficient / 403 failure reused → first use, 201; with another body too (§7)
- F7.1 50 concurrent identical requests, unused key: one 201, 49 × 200, bodies equal, effect once (§7)
- F7.2 50 concurrent, one key, two bodies: one 201; the rest 200 (winner's body) or 409 reuse; effect once (§7)
- F8.1 claimed key + invalid body (bad amount, missing field, unknown handle, self) → 409 `idempotency_key_reuse` (§7)
- F8.2 pay replay on a paid request → 200, not 409 `request_not_pending` (§8)
- F9.1 body differing only by an unknown field → 409 (§7 same JSON value)
- F10.1 keys compare exactly: `abc` and `ABC` are two keys (§7)

## G. API (test_g_api.py)
- G1.1 `/me` keys and values (§8)
- G2.1 payment 201: all fields, defaults, balances moved, in both feeds (§8)
- G3.1 exactly the balance → 201 then 1 more → 409 `insufficient_funds`; self → 422 `self_payment`; unknown handle → 404; `ADA`/` bob` → 404 (soft 422) (§8)
- G4.1 notes verbatim through POST response and /activity: spaces, tab/newline, emoji, combining char, HTML, quotes/backslash, RTL, ZWJ (§8)
- G5.1 request 201 fields; payer balance not checked (1e9 to a 0 wallet); to a just-signed-up user (§4, §8)
- G6.1 self → 422 `self_request`; unknown → 404 (§8)
- G7.1 pay → 201 payment with `request_id`; default public / chosen private; money payer→requester; request `paid` with `payment_id` for both parties; payment in feed; note equals request note (soft) (§8)
- G8.1 pay: unknown 404; requester 403; third party 403 (soft 404); declined/cancelled/paid(new key) → 409 `request_not_pending`; short → 409 `insufficient_funds`, still pending, no change; funded later → same key 201; bad visibility → 422 and still pending (§4, §8)
- G9.1 decline: 200 declined; twice 200; paid 409; cancelled 409; requester 403; third party 403 (soft 404); unknown 404 (§8)
- G10.1 cancel: 200 cancelled; twice 200; paid 409; declined 409; payer 403; third party 403 (soft 404); unknown 404 (§8)
- G11.1 race pay × 20 / decline × 15 / cancel × 15 on one request, 5 rounds: one terminal status, money moved iff paid, losers consistent (§4)
- G12.1 /requests: only own; direction × status filters; newest first (items spaced > 1 s); `limit`/`offset`/`has_more`; default 50 of 55 (§8)
- G13.1 split 201 fields; caller included / omitted / in the middle; shares in order, sum; requests for all but caller, in order, pending, caller requester, share amounts; note (soft) (§8)
- G14.1 split errors: empty 422; duplicate 422; caller twice 422; unknown 404; 1000 unknown handles 4xx; note 201; missing fields; only-caller → 201 `requests: []`; zero-balance users fine (§8)
- G15.1 /activity: payments only (no requests, no splits); public or party; newest first; pagination, `has_more`, default 50 of 55 (§4, §8)
- G16.1 private payment: same `visibility` value for sender and receiver; absent for third party and for an operator (§4, §11)
- G17.1 third party sees no request under any filter and cannot pay/decline/cancel it; it stays pending (§4)

## H. Rounding (test_h_split.py)
- H1.1 table: 1000/3, 1/3, 10/3, 999/3, 5/5; plus 1000000000/3, 7/6, 100/1, 2/5 (§9)
- H2.1 reversed order moves the extra unit; zero shares create pending 0-amount requests; paying one → 201 (map D-11) (§9)
- H3.1 three splits in a row are independent; pay all requests; balances exact and sum to the total (§9)

## I. Export / import (test_i_export.py; needs second container BASE2)
- I1.1 export 200 without auth: `track`, `format_version` 1, `state` object (§10)
- I1.2 export, then writes, then import of that export → state as at export time (§10 snapshot)
- I1.3 exports taken during a 50-in-flight payment burst, each imported into container 2: balances sum to the total (§10 atomic)
- I2.1 import of an unchanged export → 204; full snapshot (every user's /me, /activity, /requests) equal (§10)
- I2.2 import twice → no duplicates (§10)
- I2.3 destination with another fixture: after import its tokens → 401, its accounts cannot log in, its payments are gone (§10)
- I3.1 export from container 1, import into fresh container 2: snapshot equal with the same tokens (§10)
- I4.1 after import in container 2: password login; signup-created account and token; operator may settle, others 403; new writes work, new ids do not collide with imported ids; conservation (§10, §11)
- I5.1 after import: replay of completed payments / requests / pay / splits / settlements → 200 original body; other body → 409; key of a failed request → 201 first use (§10)
- I6.1 invalid JSON → 400; non-object → 400 or 422 (map clarification 1, fix round 1: both accepted); missing `track` / `format_version` / `state`; track `tablekeeper`; version 2; state `null` / `[]` / `"x"`; each top-level state value replaced by a wrong type → 422; destination unchanged each time (§10)
- I7.1 reset after import clears imported accounts and tokens (§10)
- I8.1 export → import → export gives the same state JSON (soft)

## J. Settlements (test_j_settle.py)
- J1.1 no token 401; non-operator 403 `forbidden`; fixture without operators → everyone 403; signed-up user 403 (§11)
- J2.1 operator moves money between two other wallets; 32 entries 201; 33 → 422; 0 → 422; `transfers` missing / `{}` / `"x"` / `null` → 422; entry `5` / `"x"` / `null` / `[]` → 422 (§11)
- J3.1 entry amount / note / visibility rules and defaults; unknown from or to handle 404; self 422 `self_payment`; unknown fields ignored at top level and in entries (§11)
- J3.2 order: [unknown, self] → 404; [self, unknown] → 422 `self_payment`; [bad amount, unknown] → 422 `validation_failed`; [unaffordable, unknown] → 404; [unaffordable, self] → 422 (§11)
- J4.1 net affordability: A(0)→B and B(0)→A same amount → 201; chain through a 0 wallet → 201; exactly to zero → 201; one unit short → 409 `insufficient_funds` (§11)
- J5.1 after 404 / 422 / 409: balances and feeds unchanged, key reusable → 201 (§11)
- J6.1 201: `settlement_id`, `committed_at`, `payments` in input order; each a payment with the `settlement_id`, `request_id` null, `created_at` == `committed_at`; distinct `payment_id`s; balances moved by the net; in parties' feeds; non-members (direct, pay, seeded) have `settlement_id` null (§11)
- J7.1 private member visible to its parties, not to a third party, not to the operator; operator sees no foreign requests and cannot pay/decline/cancel them (§11)
- J8.1 replay 200 original; other body 409; 50 concurrent identical → one 201 (§7, §11)
- J8.2 50 concurrent different settlements: only 201 / 409 `insufficient_funds`; final balances == initial + net of the 201s; none negative (§1, §11)
- J8.3 identical entries twice in one batch → two payments (§11)

## Hardening (first revision only, <= 15 minutes by the clock, chosen after the list has run)
- Run on revision 5493ad0, 2026-10-02T04:48:20Z to 04:56:32Z (scripts in `hardening/hard1.py`, `hard2.py`, `hard3.py`, output in `out/r1/hardening.log`):
  4400-digit `limit`/`offset`/`amount`; float amounts beyond double precision; NaN literals; odd request targets; fixture fields of
  wrong types; nesting depth; NUL and lone surrogates; raw protocol cases (bad request line, long URL, many headers, Content-Length,
  chunked framing, Expect); percent-encoded path replay; 50-in-flight races of reset/import against traffic; 500-user reset; tampered import states.

## K. Fix round 1 (test_k_round1.py) — added for revision 6c6d0a6: one check per finding of the first verdict and checks for the changed code only
- K1 (finding 1, 5, N2, N3, N4) other methods, HEAD, bad request lines, long URL/headers, bad targets, Content-Length and chunk framing → JSON 4xx; valid chunked body still works; 1 MiB body cap is a 4xx
- K2 (finding 2, N1) `limit` of 31..20000 digits → 422; `offset` of the same lengths → 200 empty page; leading zeros
- K3 (finding 3, N6) reset with wrong-typed references and other wrong shapes → 400/422, state unchanged
- K4 (finding 4) nested bodies 10..100000 levels: same answer on first use and replay; accepted bodies survive export/import
- K6 (findings 6, 7) exact number parsing: non-integral and out-of-range amounts → 422 on all four amount paths; integral spellings accepted; odd numbers in ignored fields; fixture numbers; fractional ignored field replays before and after import
- K8 (finding 8) 43 invalid-state mutations → 422, destination unchanged; unchanged export still imports
- K7/K9 (N7, N9) encoded-path replay; signup email rule
- K2b (map clarification 3, fix round 2) zero-padded `limit`/`offset` are evaluated by numeric value: `0002`, `0050`, `<5000 zeros>2` valid; `00201`, `000` as limit → 422
- E5.2 extended (fix round 2, Architect direction 5): email with a Cc/Cf/Zs/Zl/Zp character (DEL, U+0085, U+00A0, U+200B, U+2028, U+2029) → 422

## L. Fix round 2 (test_l_round2.py) — added for revision df4b305: checks for the changed code only
- L1 equal numbers in an ignored field replay (soft: spelling), different values conflict, before and after import; amount spellings
- L2 raw-text bodies: marker-like body is ordinary; odd bodies (escapes, duplicate keys, 150 KB, 900 levels, extreme numbers) replay after import in both containers; pay with empty body
- L3 import validation of the changed idempotency record; non-integer numbers inside an imported record or in free-form parts of the state never give 5xx
- L4 email predicate on fixture; ordinary and international emails accepted on reset, signup, import, login

## M. Fix round 3 (test_m_round3.py) — added for revision 43ecb3c: checks for the changed import code only
- M1 (finding S1) a non-integer or over-long number in a stored idempotency response → 422, destination and export unchanged, key still replays
- M2 reachable states still round-trip: fixture ids with `/`, spaces, `?`, `#`, `%`, newline, non-ASCII, 64 chars; zero-amount pay; signup handle from a non-ASCII local part; seeded non-pending requests; 41 keys up to 255 chars with 200-emoji private notes — import into the same and a fresh container, snapshots equal, every key replays 200
- M3 mutation sweep over every member of each state section (9 replacement values): import answers 204 or 422 only; after 204 the export is 200 and re-imports, replays and reads stay below 500; after the sweep the destination equals the original
Note: from this round the list runs in two halves (`run.sh <rev> <name> pytest1`, `pytest2`), each ending with the universal assertions.
