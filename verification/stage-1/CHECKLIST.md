# Verifier check list — Pocketful stage 1

Derived from `pocketful/spec/stage-1.md` (sha256 f5e4c644076cf5b4…) clause by clause, before any check was run and
before the Implementer's tests were read. `Rows` are rows of ACCEPTANCE-MAP-stage-1.md. `Blocks` = a failure is a
blocking finding; `note` = the specification is silent or ambiguous there (Architect reading, map section L), a
failure is reported as a note.

Run: `verify.sh up <rev> <out>`, `verify.sh checks <rev> <out>`, `verify.sh down <rev> <out>`; supplied checks separately.

## Delivery, deployment and reading (verify.sh, harness, source read)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| DL-00 | handoff | - | repository HEAD is the reported revision and the working tree is clean (verify.sh up) | yes |
| DL-01 | §2 'Deliver an HTTP service, a Dockerfile and a RUN.md with a command that builds and starts the service without manual setup' | A1 | files present in a clean export of the revision; docker build --no-cache; RUN.md command followed as written | yes |
| DL-02 | §2 'The image must run on its own with -e PORT=<port> and a port mapping'; §3.1 | A2,B1 | docker run -e PORT=9123 -p ...:9123 -> /health 200 | yes |
| DL-03 | §3.1 'default 8080' | B1 | docker run without PORT, -p ...:8080 -> /health 200 | yes |
| DL-04 | §2 'Runtime networking has no outbound access ... must work within that single container' | A3 | container stays up with --network none; the whole HTTP suite runs against containers on a docker --internal network; supplied checks with --mode isolated | yes |
| DL-05 | §2 'Start to first healthy response 60 s'; §3.2 | A4 | time from docker run to first 200 /health, each container | yes |
| DL-06 | §2 limits 2 vCPU / 2 GiB | A5 | all HTTP checks run against --cpus 2 --memory 2g containers; OOMKilled false, no restart | yes |
| DL-07 | §2 'Disk ephemeral; state need not survive a container restart' | A7 | docker restart -> healthy within 60 s, reset and login work | yes |
| DL-08 | §2 harness; handoff commands | all | supplied checks: harness run --stage 1 (host mode) and --mode isolated, new --out each; zero failed / skipped / errored for stage 1 | yes |
| RD-01 | §6 'Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2' | E10 | read the source: hashing function, salt per password, constant-time compare (plus AU-05 export canary) | yes |
| RD-02 | preamble 'Build from the supplied requirements'; task 'stage 1 only' | A8,A9 | read the source tree: no later-stage code, no UI, no nested repository, no vendored third-party product code | yes |
| RD-03 | mandate step 5 (note only) | A9 | one maintainability read of the code; recorded as a note | note |

## Runtime contract (§3)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| RT-01 | §3.2 | B2 | GET /health -> 200 {"status":"ok"} without auth | yes |
| RT-02 | §3.3 | B3 | POST /_test/reset -> 204, empty body, no auth | yes |
| RT-03 | §3.3 'Replace all service state' | B3 | reset replaces users, tokens, payments, requests, keys | yes |
| RT-04 | §3.3 'Repeated resets', §4 one currency, minor_units 0/2/3 | B4,C5 | resets with EUR/JPY/BHD; currency echoed | yes |
| RT-05 | §3.4 Content-Type | B5 | responses are application/json; charset=utf-8 on success and error | yes |
| RT-06 | §3.4 timestamps RFC 3339 with explicit offset | B6 | created_at / committed_at everywhere | yes |
| RT-07 | §3.4 'Unknown fields in a request body are ignored' | B7 | extra fields on every body | yes |
| RT-08 | §3.4 'Unknown query parameters are ignored' | B8 | extra query parameters | yes |
| RT-09 | §3.4 IDs opaque strings <= 64 chars; §4 seeded ids | B9 | generated ids never collide with seeded ids | yes |

## Fixture (§4)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| FX-01 | §4 'Seeded users must be able to log in with the given password immediately' | C13,C6 | seeded login, /me handle | yes |
| FX-02 | §4 'balance is the wallet balance after every seeded payment ... you do not replay' | C14 | seeded payments not replayed | yes |
| FX-03 | §4 'A balance below zero in a fixture is a reset error: 422 validation_failed ... change nothing' | C15 | negative balance fixture | yes |
| FX-04 | §5 'Unparseable body' 400; 'Requests must not produce 5xx' | C19 | malformed fixtures: error body, no 5xx, nothing changes | yes |
| FX-05 | §4 feed contract + fixture payments | C16 | seeded payments appear in the feed with the full payment shape | yes |
| FX-06 | §4 requests + fixture requests; §8 pay/decline/cancel | C17 | seeded requests listed for their two parties and actionable | yes |
| FX-07 | §5 '400 malformed_request: Unparseable body, or a field of the wrong JSON type'; 'Reserve 400 malformed_request for a body that does not parse or a field of the wrong type' | C19,D2 | reset fixture with a field of the wrong JSON type -> 400 malformed_request, state untouched | yes |
| FX-08 | §5 'invalid amount values (including strings and booleans), non-string note values (including null), and any visibility other than public or private are 422 validation_failed. Omission alone selects the optional-field defaults' | C19,D4 | seeded payment / request with a bad note, visibility or amount -> 422, state untouched; omission takes the defaults | yes |

## Model (§4)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| MD-01 | §4 'JSON 1000, 1000.0 and 1e3 all represent the same valid minor-unit amount' | C4 | integral number spellings accepted on every amount | yes |
| MD-01n | §4 'Every amount in the API is an integer count' | C4 | amounts are emitted as JSON integers (no fraction/exponent) | note |
| MD-02 | §4 derived handle: local part, lowercase, non [a-z0-9_] -> '_', truncate to 20 | C7 | signup handle derivation | yes |
| MD-03 | §4 'New users start with a balance of 0. They can receive money and be asked for money immediately' | C8 | signup then pay / request the new user | yes |
| MD-04 | §4 'A request may exceed the payer's balance ... 409 insufficient_funds and changes nothing ... then becomes payable' | C10 | oversized request lifecycle | yes |
| MD-05 | §4 'Visibility belongs to the payment, not the request ... seen identically by both parties' | C11 | request has no visibility; private payment visible to receiver | yes |
| MD-06 | §4 Arithmetic range: amount <= 1000000000; balances exact within ±2^53 | C12 | exact arithmetic near 2^53 | yes |

## Errors (§5)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| ER-01 | §5 400 malformed_request 'Unparseable body' | D2 | unparseable or non-object body on every POST | yes |
| ER-02 | §5 400 'a field of the wrong JSON type' | D2,E11,L4 | wrong-typed non-exempt fields -> 400 | yes |
| ER-02n | §5 wrong JSON type (array element) | L4 | non-string element in participant_handles -> 400 | note |
| ER-03 | §5 422 'A required field or query parameter is missing' | D3,E11 | missing required fields -> 422 | yes |
| ER-03n | §6 signup body | L8 | signup without display_name -> 422 | note |
| ER-04 | §5 'invalid amount values (including strings and booleans) ... are 422'; §8 tables 'below 1, above 1000000000, or not an integer' | D4,G4,G10,G19,K4 | invalid amount on every endpoint that takes one | yes |
| ER-05 | §5 'non-string note values (including null), and any visibility other than public or private are 422'; 'Omission alone selects the optional-field defaults' | D4,G6,G7 | note / visibility rules on every endpoint that takes them | yes |
| ER-06 | §5 'An integer-valued query parameter is written as plain decimal digits: 1e9, 4.0 and +4 are 422' | D5 | query integer format on /requests and /activity | yes |
| ER-07 | §5 shared ranges: limit integer 1 to 200, offset 0 or more | D6 | limit/offset boundaries on both list endpoints | yes |
| ER-08 | §5 shared ranges: Idempotency-Key 1 to 255 characters else 422; §5 absent or empty 400 missing_idempotency_key | D7,F1 | key length boundaries on the five write paths | yes |
| ER-09 | §5 401 'Missing, malformed or unknown bearer token'; §6 'Every other endpoint requires a bearer token' | D8,E8,K1 | 401 on every authenticated endpoint | yes |
| ER-10 | §5 'Every 4xx and 5xx response carries this body'; 404 not_found 'No such resource' | D1,L10 | unknown route / wrong method carry the error body | yes |
| ER-10n | §5 404 not_found | L10 | unknown route or unsupported method is exactly 404 not_found | note |
| ER-11 | §5 'Requests must not produce 5xx responses' | D9 | odd but ordinary inputs never give 5xx | yes |

## Authentication (§6)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| AU-01 | §6 signup 201 {user_id, display_name, token}; login 200 | E1,E2,E9 | signup, login, multiple concurrent tokens | yes |
| AU-02 | §6 table: email_taken 409; password < 8 -> 422; email not local@domain -> 422 | E3,E4,E5 | signup rejections | yes |
| AU-03 | §6 'Wrong password or unknown email on login -> 401 unauthenticated' | E6 | login failures | yes |
| AU-04 | §6 '409 handle_taken, and no account is created'; §4 derived handle | E7 | derived-handle collision | yes |
| AU-05 | §6 'Passwords must be stored using a password-hashing function ... Plaintext password storage is not permitted' | E10 | export holds no plaintext password | yes |

## API (§8)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| AP-01 | §8 GET /me | G1 | GET /me shape for a seeded user | yes |
| AP-02 | §8 POST /payments 201 body; 'The debit and the credit are one atomic step' | G2,K8 | payment response shape and balances | yes |
| AP-03 | §8 payments table 'The caller's balance is below amount -> 409 insufficient_funds'; 'a failed payment leaves no trace in either' | G3 | insufficient funds boundary | yes |
| AP-04 | §8 payments table: self_payment 422; unknown handle 404 | G5,G8,L3 | self payment and unknown handle | yes |
| AP-04n | §8 'No user has that handle -> 404' | L3 | exact handle lookup: '', uppercase, padded -> 404 | note |
| AP-05 | §8 'note is stored and returned verbatim: no trimming, no escaping, no normalisation ... byte for byte'; note <= 200 characters | G6,L7 | note round trip on payments, requests, pay, feed, replay | yes |
| AP-06 | §8 POST /requests 201 body; 'The payer's balance is not checked here' | G9 | request response shape | yes |
| AP-07 | §8 requests table: self_request 422, unknown handle 404 | G10 | request rejections | yes |
| AP-08 | §8 POST /requests/{id}/pay: 201 with the created payment, request becomes paid and carries payment_id | G11 | pay a request | yes |
| AP-09 | §8 pay table: request_not_pending 409, insufficient_funds 409, forbidden 403, not_found 404 | G12,L2,K2 | pay rejections | yes |
| AP-10 | §8 decline: 'Only the payer. No idempotency key. 200 ... declining twice is not an error ... paid or cancelled is 409 ... Not the payer is 403' | G13,C9 | decline transitions | yes |
| AP-11 | §8 cancel: 'Only the requester. No idempotency key. 200 ... already-cancelled is 200 ... paid or declined is 409 ... Not the requester is 403' | G14,C9 | cancel transitions | yes |
| AP-12 | §8 GET /requests: caller's requests only, direction, status, unknown values 422 | G16,K2 | request listing filters | yes |
| AP-13 | §8 'Newest first by created_at'; 'has_more is true when items exist beyond the last one returned' | G16,G17 | ordering and pagination of GET /requests | yes |
| AP-14 | §8 GET /activity 'newest first by created_at'; limit/offset 'exactly as in GET /requests' | G17,G21 | ordering and pagination of GET /activity | yes |
| AP-14b | §8 default limit 50, range 1 to 200; has_more | G17,D6 | default page size and the 200 ceiling with 205 items | yes |
| AP-15 | §4 feed contract 'if and only if its visibility is public, or the caller is its sender or its receiver'; §8 GET /activity | G21,K2 | feed visibility for sender, receiver, third party, operator, new signup | yes |
| AP-16 | §8 POST /splits 201 body; 'A request is created for every participant except the caller' | G18 | split response, caller included | yes |
| AP-16n | §8 split requests | G18 | split requests carry the split's note | note |
| AP-17 | §8 'The caller may be included in participant_handles or omitted'; solo split valid; 'Nothing about a split checks anyone's balance' | G20 | caller omitted, caller only, balances ignored | yes |
| AP-18 | §8 splits table: empty or duplicate handles 422; unknown handle 404 | G19 | split rejections create nothing | yes |

## Money and rounding (§9)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| MR-01 | §9 table and rule: 'sum exactly to amount and differ by at most one ... larger shares go to the first participants' | H1 | specification table and a sweep of amounts and sizes | yes |
| MR-02 | §9 'a different participant_handles order gives the extra unit to a different person' | H2 | permuted participants | yes |
| MR-03 | §9 'A share of 0 is legal and still produces a request for that participant' | H3 | zero share request exists and can be settled | yes |
| MR-04 | §9 'Each split's shares are independent of previous splits. After any number of splits have been paid in full, wallet balances must still sum exactly to the seeded total' | H4,C1 | many splits paid in full | yes |

## Idempotency (§7)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| ID-01-payments | §7 table: 'First use of the key -> 201'; 'Replay: same key, same body -> 200, body identical to the original response as a JSON value'; 'It makes no further state changes' | F2,F3 | first use 201, replays 200 with the identical body, no state change [payments] | yes |
| ID-01-requests | §7 table: 'First use of the key -> 201'; 'Replay: same key, same body -> 200, body identical to the original response as a JSON value'; 'It makes no further state changes' | F2,F3 | first use 201, replays 200 with the identical body, no state change [requests] | yes |
| ID-01-pay | §7 table: 'First use of the key -> 201'; 'Replay: same key, same body -> 200, body identical to the original response as a JSON value'; 'It makes no further state changes' | F2,F3 | first use 201, replays 200 with the identical body, no state change [pay] | yes |
| ID-01-splits | §7 table: 'First use of the key -> 201'; 'Replay: same key, same body -> 200, body identical to the original response as a JSON value'; 'It makes no further state changes' | F2,F3 | first use 201, replays 200 with the identical body, no state change [splits] | yes |
| ID-01-settlements | §7 table: 'First use of the key -> 201'; 'Replay: same key, same body -> 200, body identical to the original response as a JSON value'; 'It makes no further state changes' | F2,F3 | first use 201, replays 200 with the identical body, no state change [settlements] | yes |
| ID-02-payments | §7 '"Same body" means the same JSON value after parsing — key order and whitespace do not matter' | F4 | replay with reordered keys, whitespace, escapes [payments] | yes |
| ID-02-requests | §7 '"Same body" means the same JSON value after parsing — key order and whitespace do not matter' | F4 | replay with reordered keys, whitespace, escapes [requests] | yes |
| ID-02-pay | §7 '"Same body" means the same JSON value after parsing — key order and whitespace do not matter' | F4 | replay with reordered keys, whitespace, escapes [pay] | yes |
| ID-02-splits | §7 '"Same body" means the same JSON value after parsing — key order and whitespace do not matter' | F4 | replay with reordered keys, whitespace, escapes [splits] | yes |
| ID-02-settlements | §7 '"Same body" means the same JSON value after parsing — key order and whitespace do not matter' | F4 | replay with reordered keys, whitespace, escapes [settlements] | yes |
| ID-03-payments | §7 table: 'Same key, different body -> 409 idempotency_key_reuse' | F5 | same key with a different body -> 409 [payments] | yes |
| ID-03-requests | §7 table: 'Same key, different body -> 409 idempotency_key_reuse' | F5 | same key with a different body -> 409 [requests] | yes |
| ID-03-pay | §7 table: 'Same key, different body -> 409 idempotency_key_reuse' | F5 | same key with a different body -> 409 [pay] | yes |
| ID-03-splits | §7 table: 'Same key, different body -> 409 idempotency_key_reuse' | F5 | same key with a different body -> 409 [splits] | yes |
| ID-03-settlements | §7 table: 'Same key, different body -> 409 idempotency_key_reuse' | F5 | same key with a different body -> 409 [settlements] | yes |
| ID-04-payments | §7 'After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks ... still returns 409 idempotency_key_reuse' | F11 | claimed key with an invalid body -> 409, not 422 [payments] | yes |
| ID-04-requests | §7 'After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks ... still returns 409 idempotency_key_reuse' | F11 | claimed key with an invalid body -> 409, not 422 [requests] | yes |
| ID-04-pay | §7 'After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks ... still returns 409 idempotency_key_reuse' | F11 | claimed key with an invalid body -> 409, not 422 [pay] | yes |
| ID-04-splits | §7 'After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks ... still returns 409 idempotency_key_reuse' | F11 | claimed key with an invalid body -> 409, not 422 [splits] | yes |
| ID-04-settlements | §7 'After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks ... still returns 409 idempotency_key_reuse' | F11 | claimed key with an invalid body -> 409, not 422 [settlements] | yes |
| ID-05-payments | §7 table: 'Key reused after the original request failed with 4xx -> Treated as a first use' | F8,K7 | key is a first use after a 4xx [payments] | yes |
| ID-05-requests | §7 table: 'Key reused after the original request failed with 4xx -> Treated as a first use' | F8,K7 | key is a first use after a 4xx [requests] | yes |
| ID-05-pay | §7 table: 'Key reused after the original request failed with 4xx -> Treated as a first use' | F8,K7 | key is a first use after a 4xx [pay] | yes |
| ID-05-splits | §7 table: 'Key reused after the original request failed with 4xx -> Treated as a first use' | F8,K7 | key is a first use after a 4xx [splits] | yes |
| ID-05-settlements | §7 table: 'Key reused after the original request failed with 4xx -> Treated as a first use' | F8,K7 | key is a first use after a 4xx [settlements] | yes |
| ID-05b | §7 'Key reused after the original request failed with 4xx -> Treated as a first use' | F8 | failed by 409 insufficient_funds / 404 / 403, then the same key and body succeed | yes |
| ID-06 | §7 'The key is scoped to the authenticated user. Two different users may use the same key string with no interaction between them' | F6 | same key, two users, on each path | yes |
| ID-07 | §7 'The same key with the same body on a different path is a different request, not a replay, and must succeed normally' | F7 | one key and one body across paths | yes |
| ID-08 | §7 'A successful replay returns the original response, even after the resource changes or is cancelled' | F10 | replay after the resource changed | yes |
| ID-09 | §8 'Replaying a successful payment returns 200 with its original payment body, including when the request is already paid. It moves no additional money and must not return 409 request_not_pending'; '{} and {"visibility": "public"} are different JSON values' | F12,F5 | pay replay and the {} vs explicit-default rule | yes |
| ID-10n | §7 'the same JSON value after parsing' | L5 | 1000, 1000.0 and 1e3 are the same body for a replay | note |
| ID-11n | §7 / §5 ordering | L1,L6 | order of checks: 401 before key; 403 before key on settlements; key before body; empty pay body | note |

## Settlements (§11)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| ST-01 | §11 'POST /settlements requires an operator and an idempotency key. No token gives 401; authenticated non-operator gives 403 forbidden'; 'settlement_operator_ids ... default []' | K1,C18 | who may settle | yes |
| ST-02 | §11 'Return 201 with settlement_id, committed_at and payments in input order. Every member is an ordinary payment with settlement_id linking the batch ... null request_id and the same server-assigned created_at, equal to committed_at' | K8,K2 | settlement response and effect | yes |
| ST-03 | §11 'Constituents follow ordinary activity-feed visibility'; 'This permission does not grant access to another user's requests or private activity items' | K9,K2 | members in the feed | yes |
| ST-04 | §11 'transfers contains 1..32 objects'; 'malformed batch shape is 422 validation_failed' | K3 | batch size and shape | yes |
| ST-05 | §11 'Each uses ordinary payment amount, note and visibility rules (defaults: empty note, public). Unknown handle is 404; self-transfer is 422 self_payment ... Unknown fields are ignored' | K4 | entry rules | yes |
| ST-06 | §11 'Entry errors take precedence in input order, before insufficient funds' | K5 | first bad entry decides; entry error beats insufficient funds | yes |
| ST-07 | §11 'A settlement is affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative. Insufficient collective funds gives 409 insufficient_funds. Either all movements commit together or none do' | K6,K7 | net affordability and all-or-nothing | yes |
| ST-08 | §11 'Replays return 200 with the original complete response'; §7 on the fifth path | K10 | settlement replay and reuse | yes |

## Export and import (§10)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| EX-01 | §10 'Return 200 from export with a JSON object containing track: "pocketful", format_version: 1 and state (an implementation-defined JSON object)'; unauthenticated; read-only | I1 | export envelope | yes |
| EX-02 | §10 'Import takes that entire object and atomically replaces the service's state, returning 204 ... Import is replacement, not merge; repeating it restores the exported state without duplicating anything' | I2,I4,I6,I7 | same-container round trip | yes |
| EX-03 | §10 'Preserve accounts and hashed-password login, existing bearer tokens, currency, balances, payments, requests, permissions ... No dependency on the source process, files, volume, port or network address'; 'Import removes all previous destination data and credentials' | I3,I4,I6,I7,K11 | import into a different container | yes |
| EX-04 | §10 'all completed idempotent request bodies and original responses ... Failed request keys remain reusable. Existing receipts, tokens and retries must remain valid after import' | I5,K11 | replays after import on all five paths | yes |
| EX-05 | §10 'Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 validation_failed without changing the destination' | I8 | import rejections leave the destination unchanged | yes |
| EX-05n | §10 'wrong track/version' | I8 | format_version of another JSON type ("1", 1.5, true) is rejected | note |
| EX-06 | §10 'Reset clears all state, including imported state'; §3.4 ids | I9 | reset after import; new ids after import do not collide | yes |
| EX-07 | §10 'Export is an atomic, read-only snapshot; subsequent source writes do not change it' | I1 | exports taken during writes are internally consistent | yes |
| EX-08 | §10 'missing fields, wrong track/version or an invalid state give 422 validation_failed without changing the destination' | I8 | state with a top-level member removed or replaced by another JSON type -> 422, destination unchanged | yes |
| EX-09 | §10 'an invalid state give 422 validation_failed without changing the destination'; 'It must accept an unchanged export produced by this service' | I8 | state member of the wrong container type -> 422, destination unchanged; unchanged export -> 204 | yes |

## Concurrency and limits (§1, §2)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| CC-01 | §1(2) 'No wallet balance may be negative, including transiently'; §8 insufficient_funds | C2,C1 | 50 concurrent payments against a balance that affords 10 | yes |
| CC-02 | §1(3) 'A payment request may move money at most once' | C3 | 40 concurrent pays of one request with distinct keys | yes |
| CC-03-payments | §7 'For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once' | F9,K10 | 40 concurrent identical requests on an unused key [payments] | yes |
| CC-03-requests | §7 'For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once' | F9,K10 | 40 concurrent identical requests on an unused key [requests] | yes |
| CC-03-pay | §7 'For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once' | F9,K10 | 40 concurrent identical requests on an unused key [pay] | yes |
| CC-03-splits | §7 'For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once' | F9,K10 | 40 concurrent identical requests on an unused key [splits] | yes |
| CC-03-settlements | §7 'For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once' | F9,K10 | 40 concurrent identical requests on an unused key [settlements] | yes |
| CC-04 | §4 'pending, and then exactly one of paid, declined or cancelled'; §1(3) | G15,C9 | pay vs decline vs cancel race on the same request | yes |
| CC-05 | §1(1) 'The sum of wallet balances always equals the total seeded'; §2 'Concurrent requests up to 50 in flight', 'Per-request timeout 5 s'; §5 'no 5xx, including under concurrent load' | A6,C1,C2,D9,K10 | 50-way mixed burst: payments, pays, splits, settlements, reads | yes |
| CC-06 | §2 'Concurrent requests up to 50 in flight', 'Per-request timeout 5 s'; §6 password hashing | A6,L13 | 50 concurrent logins and signups each within 5 s while reads stay responsive | yes |
| CC-07 | §2 '10 s for POST /_test/reset'; §10 'Test control calls have a 10-second timeout' | I10,L13 | reset, export and import of a populated state within 10 s | note |

## Scope (task statement)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| NX-01 | task: 'Do not implement later stages'; §1 'Only the HTTP API is required' | A8 | stage 2-4 endpoints and fields are absent | yes |

## Whole-run assertions (every request sent by the suite)

| Id | Specification statement / section | Rows | Check | Blocks |
|---|---|---|---|---|
| GL-5xx | §5 'Requests must not produce 5xx responses, including under concurrent load' | D9 | no 5xx among all requests of the run | yes |
| GL-conn | §2 limits | A5,A6 | no dropped / refused / timed-out connection | yes |
| GL-ctype | §3.4 content type | B5 | every response with a body is application/json; charset=utf-8 | yes |
| GL-errbody | §5 'Every 4xx and 5xx response carries this body' | D1 | every 4xx/5xx of the run carries {error:{code,message}} | yes |
| GL-latency | §2 per-request timeout 5 s / 10 s | A6,I10 | no request of the run exceeded its limit | yes |
| GL-ids | §3.4 ids <= 64 chars | B9 | every *_id seen in any response | yes |
| GL-ts | §3.4 timestamps | B6 | every created_at / committed_at seen in any response | yes |

Total: 12 delivery/reading items, 130 scripted HTTP checks, 7 whole-run assertions.
