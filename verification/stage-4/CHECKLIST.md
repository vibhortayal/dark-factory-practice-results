# Verifier check list — pocketful stage 4

Derived from `pocketful/spec/stage-4.md` clause by clause (it keeps stages 1-3 in force), before any stage-4 revision
existed and without reading the Implementer's work. Scripts here: `vlib.py`, `checks_a.py` + `checks_b.py` (stage-1
list; idempotency over ten paths, refunds and correction batches included), `checks_c.py` (stage-2 API), `checks_d.py`
(stage-3 API; revision comparisons ignore the new `correction_batch_id`), `checks_e.py` (stage-4 API), `ui.py`
(stage-2 browser list, unchanged), `main.py`, `run.sh` (clean `--no-cache` build of `stage-4/`, and `stage-3/`,
`stage-2/`, `stage-1/` as previous services, on an internal no-outbound network with `--cpus 2 --memory 2g`).

A check FAILs only on behaviour contradicting the quoted specification statement; Architect [reading] rows are NOTE lines.

## Delivery and review checks (run.sh and by hand)

| Check | Specification statement | Map rows |
|---|---|---|
| DL-01 | Tree clean at the reported revision, before and after | – |
| DL-02/03 | stage-1 §2 Dockerfile, RUN.md, clean build; no .git, symlinks, submodules, `__pycache__` | AA2 |
| DL-04/05/06 | Default port, `-e PORT`, no outbound at run time, 2 vCPU / 2 GiB, healthy within 60 s | AA1 |
| DL-07 | RUN.md command run as written | AA2 |
| DL-08 | Supplied checks: harness `--stage 4 --mode isolated` -> `claimed stage: 4 on the shipped checks`; and `--all --mode isolated` once | AA5 |
| DL-10 | Implementer's own tests run and pass | J3 |
| DL-11 | Code read once (note only); error-precedence lists in RUN.md compared with rows AB9, AC4, AD5 | J3 |
| DL-12 | `stage-1/`, `stage-2/`, `stage-3/` unchanged since d02b8f6, 93f0fbd, cfff6f7 | AA2 |
| DL-13 | Screens unchanged from stage 2; screenshots looked at again | AA1 |

## API and browser checks (main.py)

| Check | Specification statement | Map rows |
|---|---|---|
| RT-01 | §3.2 GET /health -> 200 {"status":"ok"}, no authentication | A5 |
| RT-02 | §3.3 reset -> 204 No Content, replaces all state, repeatable, no authentication | A6 |
| RT-03 | §4 fixture: negative balance -> 422 validation_failed from reset, nothing changes | C11 |
| RT-04 | §5 reset with an unparseable body -> 400 malformed_request, state unchanged | C11 |
| RT-05 | §4 fixture: seeded users log in at once; balance is final (payments not replayed); seeded payments and requests readable with their ids | C10 C12 |
| RT-06 | §4 one currency from the fixture; minor_units 0, 2 or 3 (EUR 2, JPY 0, BHD 3) | C1 |
| RT-07 | §2 limits: reset finishes within 10 s (50-user fixture; 300 users recorded as a note) | A4 |
| RT-08 | [reading] fixture without payments/requests/settlement_operator_ids keys; structurally invalid fixture -> 422, nothing changed | C10 C11 |
| CV-01 | §3.4 unknown fields in a request body are ignored, never an error | A9 |
| CV-02 | §3.4 unknown query parameters are ignored | A9 |
| CV-03 | §5 every 4xx carries {error:{code,message}}; unknown route and unsupported method included | A7 |
| AU-01 | §6 signup -> 201 {user_id, display_name, token}; login -> 200 same shape; §4 new user: balance 0, derived handle | E1 E2 C5 |
| AU-02 | §4 signup handle: local part, lowercased, chars outside [a-z0-9_] -> '_', truncated to 20 | C4 |
| AU-03 | §6 email already registered -> 409 email_taken (seeded and signed-up emails) | E3 |
| AU-04 | §6 derived handle already taken -> 409 handle_taken and no account is created | E7 |
| AU-05 | §6 password shorter than 8 characters -> 422 (7 rejected, 8 accepted) | E4 |
| AU-06 | §6 email not of the form local@domain -> 422 validation_failed | E5 |
| AU-07 | §6 wrong password or unknown email on login -> 401 unauthenticated | E6 |
| AU-08 | §5/§6 signup and login: missing field -> 422, wrong JSON type -> 400, unparseable -> 400 | D1 D3 E7 |
| AU-09 | §6/§5 every other endpoint requires a bearer token: missing, malformed or unknown -> 401 | D5 |
| AU-10 | §6 tokens do not expire; an account may have multiple valid tokens | E8 |
| AU-11 | §6 passwords are hashed: plaintext passwords do not appear in an export | E9 |
| AU-12 | §2 limits: 50 concurrent logins and 50 concurrent signups each finish within 5 s | A4 |
| AU-13 | §4/§6 concurrent signups with one email: exactly one account, no 5xx | E10 |
| PY-01 | §8 POST /payments -> 201 payment object; defaults note "" and visibility public; §11 settlement_id null on a non-member | G1 G2 I7 |
| PY-02 | §4 amounts: JSON 1000, 1000.0 and 1e3 are the same valid amount | C2 |
| PY-03 | §8 /payments: amount below 1, above 1000000000 or not an integer -> 422; §5 strings and booleans are 422; a failed payment leaves no trace | C2 D2 G3 G4 |
| PY-04 | §8 /payments: balance below amount -> 409 insufficient_funds; balance == amount succeeds | G3 B2 |
| PY-05 | §8 /payments: own handle -> 422 self_payment; no user has that handle -> 404 not_found | G3 C3 |
| PY-06 | §8 /payments: note longer than 200 characters -> 422 (200 accepted); §5 non-string note incl. null -> 422 | G3 D2 |
| PY-07 | §8 /payments: visibility neither public nor private -> 422 | G3 D2 |
| PY-08 | §8 note is stored and returned verbatim; Unicode and emoji survive byte for byte | G5 |
| PY-09 | §5 /payments: unparseable body -> 400 malformed_request | D1 |
| RQ-01 | §8 POST /requests -> 201 request object, caller is requester, pending; payer's balance not checked; §4 a request carries no visibility | G6 C7 C8 |
| RQ-02 | §8 /requests rejections: amount rules 422; own handle 422 self_request; note > 200 -> 422; unknown handle 404; §5 type rules | G7 C2 D1 D2 |
| RQ-03 | §8 pay -> 201 payment exactly as POST /payments returns one, request_id set; request becomes paid and carries payment_id; visibility is the payer's choice, default public | G8 C8 |
| RQ-04 | §8 pay table: not pending 409 request_not_pending; payer short 409 insufficient_funds; not the payer 403 forbidden; unknown request 404 | G9 |
| RQ-05 | §4 a request may exceed the payer's balance; paying while short is 409 insufficient_funds and changes nothing; once money arrives the same request is payable | C7 |
| RQ-06 | §4/§8 request life cycle: pending then exactly one of paid, declined, cancelled; decline/cancel rules and repeats | C6 G10 G11 |
| RQ-07 | §8 GET /requests: only the caller's requests; direction, status filters; unknown values 422 | G12 |
| RQ-08 | §8 GET /requests: limit (default 50, 1..200), offset (>= 0), has_more, 422 outside; §5 integer query parameters are plain decimal digits | G12 D7 |
| RQ-09 | §8 GET /requests: newest first by created_at; default limit is 50 | G12 D7 |
| ID-01 | §7/§5 header absent or empty -> 400 missing_idempotency_key, on each of the five paths | D4 I2 |
| ID-02 | §5 Idempotency-Key 1 to 255 characters: 1 and 255 accepted, 256 -> 422 validation_failed | D4 |
| ID-03 | §7 first use 201; replay (same key, same JSON value; key order and whitespace do not matter) -> 200 with a body identical to the original, no further state change | F1 F2 |
| ID-04 | §7 same key, different body -> 409 idempotency_key_reuse; a claimed key is resolved before field validation, so an invalid body with a used key is also 409 | F3 F9 |
| ID-05 | §7 a key whose original request failed with 4xx is treated as a first use | F6 |
| ID-06 | §7 the key is scoped to the authenticated user: two users may use the same key string | F4 |
| ID-07 | §7 the same key with the same body on a different path is a different request and succeeds | F5 |
| ID-08 | §7 concurrent identical requests with an unused key: exactly one 201, the others 200 with the same body; the operation takes effect once (50 in flight, each path) | F7 B3 I9 |
| ID-09 | §7 a successful replay returns the original response even after the resource changes or is cancelled; §8 replay of a pay on a paid request is 200, never request_not_pending | F8 F9 |
| SP-01 | §8 POST /splits -> 201 {split_id, amount, currency, note, shares, requests, created_at}; a pending request for every participant except the caller, caller as requester, in the given order | G13 |
| SP-02 | §9 equal-split table; larger shares go to the first participants; reordering moves the extra unit | G15 |
| SP-03 | §8 a split whose only participant is the caller is valid; the caller may be omitted; a share of 0 still produces a request; nothing about a split checks anyone's balance | G13 |
| SP-04 | §8 split rejections: amount rules 422; empty or duplicate participant_handles 422; note > 200 -> 422; any unknown handle 404; nothing is created | G14 C2 D1 D2 |
| SP-05 | §9 after any number of splits have been paid in full, balances still sum to the seeded total; shares are whole units, sum to amount, differ by at most one, larger first | G15 B1 B4 |
| FD-01 | §4 feed contract: a payment appears iff it is public or the caller is its sender or receiver; one visibility value seen by all; a private payment is visible to its receiver | C9 G16 |
| FD-02 | §4 requests never appear in the activity feed and a split is not a feed item; §8 a feed item equals the receipt returned when the payment was created | C9 G16 |
| FD-03 | §8 GET /activity newest first by created_at | G16 |
| FD-04 | §8 GET /activity: limit and offset behave exactly as in GET /requests | G16 D7 |
| AR-01 | §4 arithmetic range: exact integer balances up to 2^53 | B4 |
| ST-01 | §11 POST /settlements requires an operator: no token 401, non-operator 403 forbidden; settlement_operator_ids defaults to [] | I1 I2 |
| ST-02 | §11 201 with settlement_id, committed_at and payments in input order; members are ordinary payments with settlement_id, null request_id, the same created_at equal to committed_at; nonmembers expose null settlement_id | I3 I7 |
| ST-03 | §11 transfers contains 1..32 objects (32 accepted; 0 and 33 -> 422); malformed batch shape -> 422 | I3 |
| ST-04 | §11 each entry uses the ordinary payment amount, note and visibility rules; unknown handle 404; self-transfer 422 self_payment | I3 C2 |
| ST-05 | §11 entry errors take precedence in input order, before insufficient funds | I4 |
| ST-06 | §11 affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative; otherwise 409 insufficient_funds; all movements commit together or none | I5 I6 B2 |
| ST-07 | §11 constituents follow ordinary activity-feed visibility; the operator permission grants no access to another user's requests or private activity items | I1 I8 C9 |
| EX-01 | §10 GET /_test/export -> 200 {track: "pocketful", format_version: 1, state: object}; unauthenticated; read-only | H1 |
| EX-02 | §10 import of an unchanged export -> 204, replaces the state (not a merge), removes previous destination data and credentials; preserves accounts, tokens, balances, payments, requests, permissions, idempotent bodies and responses; ids and timestamps not regenerated | H2 H4 I10 |
| EX-03 | §10 repeating an import restores the exported state without duplicating anything; an export of the restored state is itself importable; reset clears imported state | H2 H5 |
| EX-04 | §10 import errors: invalid JSON -> 400; missing fields, wrong track/version or an invalid state -> 422 validation_failed, without changing the destination | H3 |
| EX-05 | §10 import into a different, fresh container: no dependency on the source process, files, volume, port or network address | H2 H4 |
| EX-06 | §10 export is an atomic snapshot: one taken during a burst of payments restores to a state whose balances sum to the seeded total and match its own payments | H1 B1 |
| CC-01 | §1 no wallet balance may be negative, including transiently: 49 concurrent payments from a balance that covers 10 -> exactly 10 succeed, the rest 409 insufficient_funds | B1 B2 |
| CC-02 | §1 a payment request may move money at most once: 50 concurrent pays of one request with different keys -> exactly one 201, the others 409 request_not_pending | B3 |
| CC-03 | §1 the sum of wallet balances always equals the seeded total and no balance goes negative under 48 concurrent writers; §2 each request within 5 s | B1 B2 A4 A11 |
| CC-04 | §4 a request ends in exactly one of paid, declined, cancelled: pay, decline and cancel racing on 16 requests | C6 B3 |
| CC-05 | §11/§1 concurrent settlements and payments keep the sum and never go negative; each settlement commits wholly or not at all | I9 B1 B2 |
| CC-06 | §2 up to 50 requests in flight: a mixed burst of reads and writes, every request within 5 s | A4 A11 |
| LM-01 | §5 `limit` integer 1 to 200, otherwise 422 validation_failed — a value far beyond the range (4301 digits) is still 422 | D7 |
| LM-02 | §8 `amount` above 1000000000 -> 422 validation_failed — a value far beyond the range (4301 digits) is still 422, on every path that takes an amount | C2 |
| LM-03 | §5 `Idempotency-Key` 1 to 255 characters, otherwise 422 validation_failed, with the §5 error body — also for a key far beyond the range (65520 and 70000 characters) | D4 |
| LM-04 | §5 requests must not produce 5xx responses; a field of the wrong JSON type is a client error: reset with wrong-typed ids in the fixture | C11 A11 |
| NT-01 | [note only: size no ordinary user sends] §3.4 unknown fields are ignored / §5 no 5xx: an unknown field nested 985, 990 and 2000 levels deep | A9 A11 |
| NT-02 | [note only: size no ordinary user sends] §5 `offset` integer 0 or more: an offset of 4301 digits | D7 |
| LM-05 | §5 requests must not produce 5xx responses: an absolute-form request target with a malformed host (`GET http://[bad/health`) is a client error | A11 |
| NT-03 | [note only: size no ordinary user sends] §5 `limit`/`offset` as plain decimal digits: a value written with more than 18 digits through leading zeros | D7 |
| AZ-01 | API GET /me: balance equals total; available and held beside it; with no open holds balance, total and available agree and held is zero | M1 |
| AZ-02 | POST /authorizations -> 201 authorization object, status open; a hold reserves money without moving it; expires_at is created_at plus authorization_ttl_seconds; not a feed item | N5 N6 M1 |
| AZ-03 | POST /authorizations table: available below amount 409 insufficient_funds; amount rules 422; own handle 422 self_payment; note over 200 or bad visibility 422; unknown handle 404 | N5 |
| AZ-04 | Invariant 2: held funds cannot fund new payments, authorizations or settlement net debits; every stage-1 insufficient_funds is evaluated against available | M3 |
| AZ-05 | Capture (default, final): 201 with the payment in the POST /payments shape, authorization_id set, request_id null; the authorization becomes captured and the remainder is released in the same step; a second capture is 409 authorization_not_open | N7 N8 N6 |
| AZ-06 | Capture replays: {} and {"amount": N} are different bodies (409 idempotency_key_reuse); a replay returns the original payment even after the authorization closed; new fields do not change body equality | N1 N7 |
| AZ-07 | Extended capture mode: final:false keeps the remainder held and the status open; captured_amount is cumulative, payment_id the latest, payment_ids every capture in order, remaining_amount the amount still held | N9 |
| AZ-08 | Capture table: not open 409 authorization_not_open; amount above the remainder 422 capture_exceeds_authorization; amount below 1 or not an integer 422; not the receiver 403; unknown 404 | N10 |
| AZ-09 | Void: only the payer, no idempotency key; 200 with status voided and the hold released; voiding twice is 200; captured or expired is 409 authorization_not_open; other callers 403; a partially captured authorization releases only the remainder and keeps its capture records | N11 |
| AZ-10 | Expiry by the clock: at or after expires_at the authorization is expired and holds nothing, on reads and writes, with no request at the deadline; capture is then 409 authorization_expired | N4 N10 |
| AZ-11 | Model: seeded authorizations; available is derived, never seeded; only open unexpired holds hold anything; seeded holds keep their own expires_at | N2 N4 |
| AZ-12 | Model: a sum of seeded unexpired open holds larger than the user's balance is 422 from reset, changing nothing; authorization_ttl_seconds, if supplied, must be a positive integer | N2 N3 |
| AZ-13 | GET /authorizations: only the caller's; direction and status filters; unknown values 422; limit, offset and has_more exactly as GET /requests; newest first by created_at | N12 |
| AZ-14 | Invariants under concurrency: available never negative; cumulative captures never exceed the authorized amount; a closed hold is not captured again; results equal some serial order | M5 M3 M2 |
| AZ-15 | Screens: the browser and the API share /requests and /authorizations — HTML for Accept: text/html, JSON without it; the other screens are reachable by URL | L1 L2 |
| AZ-16 | Export/import keeps authorizations: holds, statuses, expires_at, capture records, lifetime and the idempotent responses of the two new paths; import into a second container | N13 |
| AZ-17 | Existing clients after an upgrade (API side): a stage-2 service accepts an export produced by the same team's stage-1 service and preserves accounts, tokens, balances, requests and retry responses | R1 |
| AZ-18 | POST /authorizations: `expires_at` is `created_at` plus `authorization_ttl_seconds` — on every one of 4000 creations (the difference was 599 s once in 16,000 on 1e2214f: two clock reads straddling a second) | N5 |
| AZ-19 | Expiry against the returned expires_at: a hold is open strictly before it and expired at or after it (capture succeeds before, is 409 authorization_expired after; void after is 409 authorization_not_open). [reading K6, notes only] six fractional digits, created_at is the request instant, timestamps never go back, a capture's payment is not timestamped before its authorization | K6 N4 N11 |
| HS-01 | Payment timestamps: seeded created_at kept as given; omission uses reset time, before later API payments; a seeded created_at in the future is 422 from reset with no state change; the seeded balance is the balance after all seeded payments | U1 U2 U3 |
| HS-02 | GET /me: without temporal parameters the stage-2 fields are unchanged; as_of is an RFC 3339 instant with an offset, echoed exactly; anything else is 422 | V1 V2 |
| HS-03 | GET /me?as_of=T: the balance after every payment at or before T and before every later one; a payment at exactly T counts; T after the latest is the current balance; T before the earliest is the opening balance | V3 V4 |
| HS-04 | GET /statement: entries are the caller's payments in [from, to), oldest first, with delta and balance_after; opening + deltas = closing; defaults from = opening, to = now | W1 W2 W3 W4 W5 |
| HS-05 | Statement: only the caller's payments (own private included, others' public excluded); money movements only — holds, releases and expiry are not entries; a capture appears once with its links; settlement members with settlement_id; ties ordered by payment id | W2 W5 |
| HS-06 | Corrections: 201 {payment_id, revision, amount, effective_at, recorded_at, reason}; revisions endpoint in order with revision 1 (reason ""); recorded_at strictly increases; the difference moves between the same two wallets; original payment, activity and original replay unchanged | X1 X5 X7 X10 X11 |
| HS-07 | Corrections input: all fields required; expected_revision a positive integer; amount 0..1000000000; reason 1..200 characters; effective_at an RFC 3339 instant not later than now; invalid input 422 | X3 |
| HS-08 | Corrections: only the original sender (403 for receiver, third party, operator); unknown payment 404; stale expected revision 409 stale_revision; settlement members and captures 422 linked_payment_immutable; replays 200 even after newer revisions; different body 409; a refused correction leaves the key unused | X2 X4 X6 X12 |
| HS-09 | Corrections: an unaffordable current debit is 409 insufficient_funds (judged on available); otherwise a negative total or available at any past boundary is 409 historical_overdraft; movements at the same instant combine; either failure preserves everything | X7 X8 X9 |
| HS-10 | known_at: each payment contributes its latest revision recorded at or before known_at (nothing if none yet); revisions apply at their effective times; as_of inclusive, windows half-open; echoed exactly | V5 W6 |
| HS-11 | Historical holds: for GET /me?as_of=T&known_at=K all four money fields describe one view; a hold starts at creation, a non-final capture reduces it, final capture/void/expiry release it at the event time; authorizations expose closed_at | V6 V7 |
| HS-12 | Stable statement pagination: every first statement returns a snapshot token; paging the token returns that exact result after later payments, corrections, captures and voids; only limit and offset may accompany it (422); unknown, another user's or pre-reset tokens are 404 | Y1 Y2 Y3 Y4 Y5 |
| HS-13 | Upgrades: a stage-3 service accepts exports of this team's stage-1 and stage-2 services; imported payments get revision 1 at created_at; statements and historical balances work on imported history; authorizations and captures are accounted for | T3 T6 |
| HS-14 | Concurrency and limits: with corrections, statements and historical reads in the mix, balances sum to the seeded total, nothing over 5 s, no 5xx; statements and historical /me on a wallet with 2000 payments | Z1 |
| HS-15 | stage-2 Model: seeded status open, captured, voided or expired — only open holds anything; stage-3: all four money fields of GET /me?as_of describe one view. A seeded expired hold whose expires_at is still in the future holds nothing in any view and cannot cause a historical_overdraft | N2 V6 V7 X8 |
| HS-16 | stage-2 Model: only open holds anything — every seeded closed status (captured, voided, expired) with expires_at in the past and in the future holds nothing in GET /me, GET /me?as_of (now, before and after expires_at, with known_at) and takes no part in historical_overdraft; [reading V7, note] closed_at is never in the future | N2 V6 V7 X8 |
| RF-01 | Refunds: a new payment in the opposite direction with refund_of naming the target, request_id and authorization_id null, the original note and visibility; 201, replay 200; other payments have refund_of null; an ordinary money movement in activity, statements, /me as_of and revisions | AB5 AB8 |
| RF-02 | Refunds: only the original receiver (403 for sender, third party, operator); unknown payment 404; idempotency key required; amount follows the ordinary payment amount rules (422) | AB1 AB2 AA3 |
| RF-03 | Refund targets: a direct payment, a request payment, a capture or a settlement member — never a refund (422 invalid_refund_target); refunds never reopen a request or an authorization or restore a released hold | AB3 AB7 |
| RF-04 | Cumulative refunds may not exceed the payment's current corrected amount (422 refund_exceeds_payment; equal accepted); a payment corrected to 0 cannot be refunded; a correction upward raises the cap; a correction cannot reduce a payment below its refunded total | AB4 AC2 |
| RF-05 | A refund moves existing money from the receiver's available funds atomically, or fails 409 insufficient_funds and changes nothing (key unused); held funds cannot fund it | AB6 |
| RF-06 | Concurrency: concurrent refunds of one payment never exceed its amount; concurrent refunds and payments never make available negative | AB10 |
| RF-07 | [reading AB9, notes] order of checks on a refund: amount validation, 404, 403, invalid_refund_target, refund_exceeds_payment, insufficient_funds | AB9 |
| SC-01 | Single corrections: captures, refund payments and settlement members are 422 linked_payment_immutable; refunds are part of the history every check walks; correction_batch_id null on single revisions (reading) | AC1 AC3 AC4 AC5 |
| BC-01 | POST /correction-batches: no token 401; authenticated non-operator 403 forbidden; key required; body {corrections: [1..32 objects with distinct payment_ids]} else 422; unknown fields ignored | AD1 AD2 |
| BC-02 | Batch items: ordinary correction validation (422); unknown payment 404; stale revision 409; captures and refunds 422 linked_payment_immutable; below the refunded amount 422 refund_exceeds_payment; the operator corrects payments of any parties | AD3 |
| BC-03 | Settlements in batches: correcting any member requires every member (422 incomplete_settlement); members carry identical effective instants (offset spellings may differ) else 422; non-members keep single corrections | AD4 AD9 |
| BC-04 | Batch precedence: item errors in input order, then settlement completeness, then current available funds, then history; affordability uses the combined effect of all proposed revisions | AD5 |
| BC-05 | Batch success: 201 {correction_batch_id, recorded_at, revisions} in input order; one shared recorded_at later than every member's previous one; correction_batch_id on each revision; money per payment; replay 200; originals, receipts and old snapshots unchanged; a rejected batch changes nothing and leaves the key unused | AD6 AD7 AD8 |
| BC-06 | Concurrency: corrections sharing any expected payment revision cannot both succeed — batch vs batch and batch vs single correction; invariants hold | AD10 |
| UP-01 | A stage-4 service accepts exports of this team's stage-3 service, keeping settlement membership, corrections and statement snapshots (a stage-3 snapshot token pages the same frozen result); stage-4 refunds and batches survive export -> import into a fresh container | AA4 |
| GL-01 | §5 requests must not produce 5xx responses, including under concurrent load | A11 |
| GL-02 | §2 per-request timeout 5 s (10 s for the /_test endpoints) | A4 |
| GL-03 | §5 every 4xx and 5xx response carries {"error": {"code", "message"}} | A7 |
| GL-04 | §3.4 responses are application/json; charset=utf-8 | A7 |
| GL-05 | §3.4 IDs are opaque strings of at most 64 characters | A10 |
| GL-06 | §3.4 timestamps in responses are RFC 3339 with an explicit offset | A8 |
| UI-01 | Screens reachable by URL: / /requests /split /signup /login and the new route /authorizations; current-user visible on every screen when signed in; navigation consistent across the routes | L1 L3 |
| UI-02 | Signup and login: test ids; auth-error present only when there is an error; current-user contains the display name; current-handle is exactly the handle; logout | L3 L4 |
| UI-03 | Formatted amount: exactly minor_units decimals, one space, the currency code; no decimal point for minor_units 0; wallet-balance carries data-amount | O1 P1 |
| UI-04 | Pay form: decimal amounts become minor units (15.00 and 15 -> 1500, 15.5 -> 1550); values kept after success; the feed and balance show the new state without a reload; pay-error absent | P2 P3 P5 P6 O2 |
| UI-05 | Amount input: nonnumeric input or more than minor_units decimals shows the form's error element without sending a request; nothing is rounded | O2 |
| UI-06 | A refused payment shows pay-error (insufficient funds, unknown handle, own handle), keeps the inputs; another client spending the balance first: pay-error, balance and feed refreshed, inputs preserved | P2 P8 |
| UI-07 | Request form on /: creates a request; request-error when refused | P4 |
| UI-08 | Activity feed: empty-activity shown instead of the list when nothing is visible; one item per visible payment by the feed contract; note element present even when empty | P5 |
| UI-09 | wallet-refresh refreshes balance and feed without clearing the pay form; latest refresh wins when responses arrive out of order | P7 |
| UI-10 | Lost payment response: pay-uncertain (nonempty), not pay-error; the unchanged form retries with the same key and body; a successful retry removes both elements, refreshes, and money moves exactly once | P9 |
| UI-11 | /requests: incoming-list and outgoing-list; request-item with data-status; request-amount; pay and decline only on a pending incoming request, cancel only on a pending outgoing one; empty-requests | Q1 Q2 |
| UI-12 | /split: split-preview shows the shares the server would compute (stage-1 §9) before anything is posted; preview and submitted split have identical shares; split-error when refused | Q3 |
| UI-13 | Wallet: wallet-balance is the formatted total; wallet-available the formatted available, the headline number; wallet-held the formatted held, absent when held is zero; correct immediately after a reset with holds | P1 S2 |
| UI-14 | Authorise form: authorize-handle/-amount/-note/-visibility/-submit with the pay form's input rules; authorize-error when refused, including insufficient available funds; the wallet reflects the new hold | P10 O2 |
| UI-15 | /authorizations: authorization-list newest first; item data-status; amount; captured only when captured; expires text is the RFC 3339 expires_at; capture input and button only on incoming open; void only on outgoing open; empty-authorizations | Q4 |
| UI-16 | Capture and void from the screen; authorization-error when a capture or void is refused; the list and the wallet show the new state after a successful action | Q5 P6 |
| UI-17 | Existing clients after an upgrade: a browser signed in before the export/import stays signed in with no reload; a payment whose response was lost before the export is retried with the same key and recovers the original payment; pending requests remain payable through the request screen | R2 R3 R4 L5 |
| UI-18 | Product direction: the required flows remain usable at a 375 CSS-pixel viewport and at desktop widths without horizontal page scrolling (long notes, a 20-character handle, the largest amounts) | S5 |
| UI-19 | Product direction: inputs need visible labels; text and controls need sufficient contrast | S6 |
| UI-20 | Product direction: keyboard focus must be apparent; forms are usable with the keyboard | S6 |
| UI-21 | Product direction: considered loading and error states (screens while their reads are slow or fail) | S4 |
| UI-22 | stage-1 §2: runtime assets are included in the image — the browser fetched nothing from another origin during the whole run; no uncaught script errors | K3 |
