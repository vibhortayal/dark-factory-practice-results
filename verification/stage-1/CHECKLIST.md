# Verifier check list — pocketful stage 1

Derived from `pocketful/spec/stage-1.md` clause by clause, before reading the Implementer's code or tests.
Scripts: `vlib.py` (framework), `checks_a.py`, `checks_b.py`, `main.py`, `run.sh` in this folder.
Run: `run.sh <full-revision> <out-dir>` (builds from a clean export of the revision, starts the image on an
internal no-outbound network with `--cpus 2 --memory 2g`, runs every API check from the host).

A check FAILs (blocks) only on behaviour that contradicts the quoted specification statement. Points the
specification leaves open (the Architect's **[reading]** rows) are recorded as NOTE lines and never block.
Cross-cutting statements (GL-*) are evaluated over every HTTP response of the whole run.

## Delivery and runtime checks (run.sh and by hand)

| Check | Specification statement | Map rows |
|---|---|---|
| DL-01 | Handoff rule: working tree clean and at the reported revision, before and after | – |
| DL-02 | §2 deliver an HTTP service, a `Dockerfile` and a `RUN.md`; task: no nested .git, symlinks or submodules | A1 |
| DL-03 | §2 the harness builds the submitted Dockerfile: build from a clean export with `--no-cache` | A1 |
| DL-04 | §3.1 listen on 0.0.0.0, default port 8080 (no PORT, port mapping) | A2 |
| DL-05 | §2 the image must run on its own with `-e PORT=<port>` and a port mapping | A2 |
| DL-06 | §2 no outbound access at run time; 2 vCPU, 2 GiB; §3.2 healthy within 60 s of container start | A3 A4 |
| DL-07 | §2 `RUN.md` has a command that builds and starts the service without manual setup (run as written) | A1 |
| DL-08 | Supplied checks: harness `--stage 1 --mode isolated` ends with `claimed stage: 1 on the shipped checks` | J2 |
| DL-09 | Task: no later stage implemented early — harness stage-2 line fails | J1 |
| DL-10 | Implementer's own tests run and pass | J3 |
| DL-11 | §6 passwords stored with a password-hashing function (code read); maintainability read (note only) | E9 J3 |
| EX-07 | §10 no dependency on the source process, files, volume, port or address: export, remove the source containers, import into a fresh container and verify everything preserved | H2 H4 |

## API checks (main.py)

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
| GL-01 | §5 requests must not produce 5xx responses, including under concurrent load | A11 |
| GL-02 | §2 per-request timeout 5 s (10 s for the /_test endpoints) | A4 |
| GL-03 | §5 every 4xx and 5xx response carries {"error": {"code", "message"}} | A7 |
| GL-04 | §3.4 responses are application/json; charset=utf-8 | A7 |
| GL-05 | §3.4 IDs are opaque strings of at most 64 characters | A10 |
| GL-06 | §3.4 timestamps in responses are RFC 3339 with an explicit offset | A8 |

## Checks added after the code read of revision 03b5470f8967245daf840465472e91b6328c7e4f

These were added once the first full run and the code read were done; they run after the GL checks.

| Check | Specification statement | Map rows |
|---|---|---|
| LM-01 | §5 `limit` integer 1 to 200, otherwise 422 validation_failed — a value far beyond the range (4301 digits) is still 422 | D7 |
| LM-02 | §8 `amount` above 1000000000 -> 422 validation_failed — a value far beyond the range (4301 digits) is still 422, on every path that takes an amount | C2 |
| LM-03 | §5 `Idempotency-Key` 1 to 255 characters, otherwise 422 validation_failed, with the §5 error body — also for a key far beyond the range (65520 and 70000 characters) | D4 |
| LM-04 | §5 requests must not produce 5xx responses; a field of the wrong JSON type is a client error: reset with wrong-typed ids in the fixture | C11 A11 |
| NT-01 | [note only: size no ordinary user sends] §3.4 unknown fields are ignored / §5 no 5xx: an unknown field nested 985, 990 and 2000 levels deep | A9 A11 |
| NT-02 | [note only: size no ordinary user sends] §5 `offset` integer 0 or more: an offset of 4301 digits | D7 |

Map change b1636b35fce9cc902ce694fbddeb7455614bae78 (rows D7, A11): NT-01 now expects 201 or 400 `malformed_request` for nested unknown fields, NT-02 expects 200 with an empty page for a 4301-digit offset on `/activity` and `/requests`. Both remain [reading] checks recorded as notes.

## Checks added in fix round 1 (code changed between 03b5470 and 38f2970c0c1395ee1338ef6326948332609a45de)

| Check | Specification statement | Map rows |
|---|---|---|
| LM-05 | §5 requests must not produce 5xx responses: an absolute-form request target with a malformed host (`GET http://[bad/health`) is a client error | A11 |
| NT-03 | [note only: size no ordinary user sends] §5 `limit`/`offset` as plain decimal digits: a value written with more than 18 digits through leading zeros | D7 |

Further one-off probes of the changed code (protocol-level errors over a raw socket, the 18-digit rule, huge integer literals, the rewritten canonical form, wrong-typed values in an import): `probes3.py`, 80 probes.

## Fix round 2 (code changed between 38f2970 and d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47)

No new list checks. One-off probes of the changed code: `probes4.py` (44 probes: request targets, request lines, body framing, keep-alive reuse, the 30 s receive timeout, zero-padded `limit`/`offset`) and `probes3.py` again (80 probes).
