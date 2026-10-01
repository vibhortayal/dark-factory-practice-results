@vibhor15/nightshift-implementer STAGE 3 HANDOFF — part 13 of 13 (FINAL): stage-1 acceptance map (verbatim from acceptance/stage-1.md; still applies to stage-3/), piece 2 of 2. With this part the handoff is complete: parts 1–13 together are the whole task, all three specifications and all three acceptance maps. Start now.

## G. API (§8)

| # | Requirement | Check |
|---|---|---|
| G1 | `GET /me` → `user_id, display_name, handle, balance, currency, minor_units` exactly | S |
| G2 | `POST /payments` 201 body: `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id:null, settlement_id:null, created_at` | S + O (`settlement_id` present and null) |
| G3 | `note` default `""`, `visibility` default `"public"` on omission only | S |
| G4 | Balance below amount → 409 `insufficient_funds`, no trace in either wallet or the feed; paying exactly the balance succeeds | S |
| G5 | amount <1, >1000000000, non-integer → 422; exactly 1 and exactly 1000000000 in range | S |
| G6 | Own handle → 422 `self_payment` | S |
| G7 | `note` > 200 characters → 422; exactly 200 accepted; length counted in Unicode code points (200 emoji OK, 201 emoji rejected) | S |
| G8 | Unknown handle → 404 `not_found` (CHOICE: a handle string that cannot match the pattern, e.g. `""`, `"ADA"`, `"@ada"`, is also 404 — "no user has that handle") | S |
| G9 | `note` stored and returned verbatim, byte for byte: no trim, escape or Unicode normalisation (leading/trailing spaces, `<script>`, combining marks, emoji, `\u0000`-free control chars) | S + O |
| G10 | `POST /requests` 201 body: `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status:"pending", payment_id:null, created_at`; caller is requester | S |
| G11 | Request rejections: amount range 422; own handle 422 `self_request`; note > 200 → 422; unknown handle 404; payer balance NOT checked | S |
| G12 | `POST /requests/{id}/pay`: payer only; body `visibility` optional default public; 201 with payment (`request_id` set); request becomes `paid` with `payment_id` | S |
| G13 | Pay rejections: unknown id 404; caller not payer 403 (requester and third party alike — CHOICE: 403 for any authenticated non-payer of an existing request, per the endpoint table); not pending 409 `request_not_pending`; short balance 409 `insufficient_funds` (request stays pending); bad visibility 422 | S + O |
| G14 | A request moves money at most once: concurrent pays with DIFFERENT keys → exactly one 201, others 409 `request_not_pending`; pay racing decline/cancel → exactly one wins | O |
| G15 | `POST /requests/{id}/decline`: payer only, no key needed, 200 with request `declined`; repeat → 200; `paid`/`cancelled` → 409 `request_not_pending`; not payer 403; unknown 404 | S + O |
| G16 | `POST /requests/{id}/cancel`: requester only, no key, 200 `cancelled`; repeat → 200; `paid`/`declined` → 409; not requester 403; unknown 404 | S + O |
| G17 | Decline/cancel accept a missing or empty body and ignore any `Idempotency-Key` | S + O |
| G18 | `GET /requests`: only caller's, newest first; `direction` incoming/outgoing/absent; `status` one of four/absent; unknown value → 422; `limit`/`offset` per D8; `has_more` true iff items exist beyond the page; body `{requests, has_more}` | S + O (offset beyond end → empty, `has_more:false`) |
| G19 | `POST /splits` 201 body: `split_id, amount, currency, note, shares[{handle,amount}], requests[...], created_at`; shares cover every participant incl. caller in given order and sum to amount; one pending request per participant except the caller, same order, caller as requester, request `note` = split note (CHOICE: note copied; reason: the request is the share of that split) | S + O |
| G20 | Caller may be included or omitted; when omitted the caller has no share and all participants get requests | O |
| G21 | Split rejections: amount range 422; `participant_handles` empty or with a duplicate → 422; missing → 422; not an array or non-string member → 400; note > 200 → 422; unknown handle → 404. Duplicate check precedes the unknown-handle check (CHOICE). No upper bound on participants is stated: 1000 handles must be validated, not crash | S + O |
| G22 | Caller-only split is valid: one share, `requests: []`. Splits never check balances. Zero share still creates a request (amount 0 request is legal only via a split) | S |
| G23 | Paying a zero-amount split request: CHOICE — succeeds with a zero-amount payment, request becomes `paid`. Reason: the request is legal and pending, and nothing in the pay table rejects it | O |
| G24 | A failed split creates no requests at all (atomic) | O |
| G25 | `GET /activity`: `{payments, has_more}`, newest first by `created_at`, C10 visibility, paging per D8, ignores `direction`/`status` | S |

## H. Money invariants (§1, §9)

| # | Requirement | Check |
|---|---|---|
| H1 | Sum of all balances always equals the seeded total (signups add 0) | S + O after every concurrency test |
| H2 | No balance negative, even transiently: N concurrent payments from one wallet that together exceed it → exactly floor(balance/amount) succeed, the rest 409 | S + O: 50-way burst, also cross-payments A↔B (deadlock check) |
| H3 | Equal-split rule: base = amount div n, first (amount mod n) participants get +1; table rows 1000/3, 1/3, 10/3, 999/3, 5/5 | S + O: property test over amounts and n |
| H4 | Different handle order moves the extra unit; shares independent of earlier splits | S |
| H5 | After splits are paid in full, balances still sum to the seeded total | O |

## I. Export / import (§10)

| # | Requirement | Check |
|---|---|---|
| I1 | `GET /_test/export` (no auth) → 200 `{track:"pocketful", format_version:1, state:{...}}` | S |
| I2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically replaces all state; repeated import → same state, nothing duplicated | S + O |
| I3 | Import invalid JSON → 400; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid state (wrong types, dangling references, negative balance) → 422, destination unchanged | O |
| I4 | Preserved across export→reset→import and export→fresh container→import: accounts + password login, existing bearer tokens, currency/minor_units, balances, payments (ids, timestamps, notes, visibility, links), requests (status, payment_id), splits, settlement membership, operator ids, every completed idempotent request body with its original response | O: replay each of the five paths after import → 200 identical body; changed body → 409 |
| I5 | Nothing regenerated or replayed: ids and timestamps identical, balances not double-applied | O: deep-equal export A vs export after import |
| I6 | Failed-request keys remain reusable after import | O |
| I7 | Import removes all previous destination data and credentials (old tokens 401, old users can't log in) | O |
| I8 | Reset clears imported state | O |
| I9 | Export is an atomic read-only snapshot: a later write does not alter an export already taken; export under concurrent writes is internally consistent (balances sum to total) | O |
| I10 | No dependency on source process, files, volume, port or address: export from container A imports into a new container B | O |
| I11 | Export/import/reset each under 10 s for a few hundred users | O |
| I12 | `state` carries its own internal schema version so later stages can accept this stage's exports (design requirement for the stage-2 upgrade path; no stage-2 behaviour) | O: review |

## J. Settlements (§11)

| # | Requirement | Check |
|---|---|---|
| J1 | Fixture `settlement_operator_ids` (default `[]`) names operators | S |
| J2 | `POST /settlements`: no token 401; authenticated non-operator 403 `forbidden`; key required (400 when missing) | O |
| J3 | `transfers` is an array of 1..32 objects; missing, not an array, empty, 33+, or a non-object member → 422 `validation_failed` (batch shape) | O: 0, 1, 32, 33 |
| J4 | Each entry: `from_handle`, `to_handle`, `amount` (ordinary amount rules), optional `note` (default `""`, ≤ 200), optional `visibility` (default public); missing handle → 422; unknown handle (either side) → 404; `from_handle == to_handle` → 422 `self_payment`; unknown entry fields ignored | O |
| J5 | Entry errors are reported in input order (first bad entry wins) and always before `insufficient_funds` | O: bad entry 2 + unaffordable batch → entry-2 error; two bad entries → first one's code |
| J6 | Affordability is NET: every wallet's balance after all incoming and outgoing transfers ≥ 0; a wallet may pass through more than it holds (A→B 100, B→C 100 with B at 0 is fine); otherwise 409 `insufficient_funds` | S + O |
| J7 | All-or-nothing: on any failure no payment exists, no balance changed, key not claimed (reusable) | O |
| J8 | 201 body `{settlement_id, committed_at, payments[...]}` in input order; every member is an ordinary payment object with `settlement_id` set, `request_id: null`, `created_at` == `committed_at` (same value for all members); `from_*` is the transfer's sender, not the operator | S + O |
| J9 | Every payment anywhere in the API exposes `settlement_id` (null for non-members) | O |
| J10 | Members follow the ordinary feed rule (private member hidden from third parties and from the operator when not a party); the operator gains no access to other users' requests or private activity | O |
| J11 | Replay → 200 with the original complete response; different body same key → 409; concurrent identical → one 201 | O |
| J12 | The operator may settle across any wallets, including ones the operator is not a party to; an operator may also be a party | S + O |
| J13 | Reset/import preserve operator permissions, payments, requests, settlement membership and retry responses | O (with I4) |
| J14 | Concurrent settlements and payments over the same wallets keep H1 and H2 | O |
