# Verifier check list — pocketful stage 2

Derived from `pocketful/spec/stage-2.md` clause by clause (which keeps `stage-1.md` in force), before any stage-2
revision existed and without reading the Implementer's work. Scripts in this folder: `vlib.py` (framework),
`checks_a.py` + `checks_b.py` (the stage-1 list, rerun against the stage-2 image; seven idempotent paths; `/me` compared
on its stage-1 members), `checks_c.py` (stage-2 API), `ui.py` (browser checks with Playwright/Chromium at 375 px and
1280 px), `main.py`, `run.sh`.

Run: `run.sh <full-revision> <out-dir> [api|ui|all]`. It builds `stage-2/` from a clean export with `--no-cache`, builds
`stage-1/` as the previous service, starts both on an internal no-outbound network with `--cpus 2 --memory 2g`.

A check FAILs (blocks) only on behaviour that contradicts the quoted specification statement. Points the specification
leaves open (the Architect's **[reading]** rows) and heuristics that need a human look are NOTE lines and never block
by themselves. GL-* are evaluated over every API response of the run; UI-22 over every browser request.

## Delivery, runtime and review checks (run.sh and by hand)

| Check | Specification statement | Map rows |
|---|---|---|
| DL-01 | Handoff rule: working tree clean and at the reported revision, before and after | – |
| DL-02 | stage-1 §2 Dockerfile and RUN.md in `stage-2/`; task: complete, buildable folder, no nested .git, symlinks or submodules | K2 |
| DL-03 | stage-1 §2 build of `stage-2/` from a clean export with `--no-cache` | K2 |
| DL-04 | stage-1 §3.1 default port 8080 | K1 |
| DL-05 | stage-1 §2 `-e PORT=<port>` with a port mapping | K1 |
| DL-06 | stage-1 §2 no outbound network at run time, 2 vCPU, 2 GiB, healthy within 60 s | K1 K3 |
| DL-07 | stage-1 §2 the RUN.md command builds and starts the service without manual setup (run as written) | K2 |
| DL-08 | Supplied checks: harness `--stage 2 --mode isolated` ends with `claimed stage: 2 on the shipped checks` | K5 |
| DL-09 | Task: no later stage implemented early — the harness stage-3 line fails; read of the stage-3 headings only at verification time | K4 |
| DL-10 | Implementer's own tests run and pass | J3 |
| DL-11 | Code read once for maintainability (note only); stage-1 §6 password hashing unchanged | J3 E9 |
| DL-12 | Task: `stage-1/` is not modified — `git diff d02b8f6..<rev> -- stage-1` is empty; the stage-1 harness run still passes | K2 |
| DL-13 | Product and visual direction: screenshots of every screen at 375 px and 1280 px (empty, filled, error, uncertain, loading, read-failure states) reviewed by eye for a coherent visual system, a clear headline number, scannable lists, distinct states | S1 S2 S3 S4 |

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

## Added after the code read of revision 1e2214f72f4feacaa076fc48157c516b1ca944a8

| Check | Specification statement | Map rows |
|---|---|---|
| AZ-18 | POST /authorizations: `expires_at` is `created_at` plus `authorization_ttl_seconds` — on every one of 4000 creations (the difference was 599 s once in 16,000 on 1e2214f: two clock reads straddling a second) | N5 |

One-off probes of this revision: `probes5.py` (API: wrong-typed authorization values in fixtures and imports, values far beyond stated limits on the two new paths, static asset paths, expiry at the deadline, lifetime over many creations, latency with 4000 open holds), `ui_probes.py` (browser: double submits on the other forms, markup in names and notes, signed-out visits, a sanity check of the out-of-order refresh check), `repro_b1.py` (lifetime mismatch).

## Map change 5968fd7e31a44019290a3c439f8591eaef6e598a (new row K6, a reading about time)

| Check | Specification statement | Map rows |
|---|---|---|
| AZ-19 | Expiry against the returned expires_at: a hold is open strictly before it and expired at or after it (capture succeeds before, is 409 authorization_expired after; void after is 409 authorization_not_open). [reading K6, notes only] six fractional digits, created_at is the request instant, timestamps never go back, a capture's payment is not timestamped before its authorization | K6 N4 N11 |

At verification the exact-lifetime run is `repro_b1.py 20000`, and the stepped-clock reproduction is repeated inside the image against the new code.
