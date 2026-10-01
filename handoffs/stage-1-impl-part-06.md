@vibhor15/nightshift-implementer
Rows: all stage-1 rows · Revision: head of main (base for stage-1) · Files: stage-1/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-1 HANDOFF PART 6/7 — ACCEPTANCE MAP acceptance/stage-1.md (verbatim)

| K11 | Once body parsed as a JSON object and caller authenticated, a claimed key is resolved before field validation or current-resource checks: a successful request re-sent with the same key and a now-invalid body → 409 `idempotency_key_reuse` (not 422/404). | T |

## P — API (§8)

| Row | Requirement | Check |
|---|---|---|
| P1 | `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}`. | T/H |
| P2 | `POST /payments {to_handle, amount, note?, visibility?}` → 201 payment `{payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id: null, settlement_id: null, created_at}`; balances move by `amount`. | T/H |
| P3 | `note` defaults to `""`, `visibility` defaults to `"public"`. | T |
| P4 | Balance below `amount` → 409 `insufficient_funds`; paying the exact full balance succeeds. | T |
| P5 | `amount` < 1, > 1000000000, or non-integer → 422 (0, -1, 1.5, 1000000001 rejected; 1 and 1000000000 accepted). | T |
| P6 | `to_handle` is caller's own handle → 422 `self_payment`. | T |
| P7 | `note` longer than 200 characters → 422 (200 accepted, 201 rejected; length counted in characters, not bytes). | T |
| P8 | `visibility` not `public`/`private` → 422. | T |
| P9 | No user with that handle → 404 `not_found`. | T |
| P10 | `note` stored and returned verbatim: no trim, no escaping, no normalisation; Unicode and emoji round-trip byte for byte (leading/trailing spaces, `<b>`, combining characters, non-NFC forms). | T |
| P11 | `POST /requests {payer_handle, amount, note?}` → 201 request `{request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status: "pending", payment_id: null, created_at}`; caller is requester; payer balance not checked. | T/H |
| P12 | Request errors: amount rule → 422; own handle → 422 `self_request`; note > 200 → 422; unknown handle → 404. | T |
| P13 | `POST /requests/{id}/pay {visibility?}` (payer only) → 201 with the created payment exactly as `POST /payments` returns it, `request_id` set; request becomes `paid` with `payment_id`; payment's note is the request's note. | T/H |
| P14 | Pay errors: not `pending` → 409 `request_not_pending`; payer short → 409 `insufficient_funds` (nothing changes); caller not payer → 403 `forbidden`; unknown request → 404. | T |
| P15 | Replaying a successful pay (same key, same body) → 200 with the original payment body even though the request is `paid`; no extra money moves; never 409 `request_not_pending`. | T |
| P16 | `POST /requests/{id}/decline` (payer only, no idempotency key) → 200 request with `status: "declined"`; repeat → 200 current state; `paid` or `cancelled` → 409 `request_not_pending`; not payer → 403; unknown → 404. | T |
| P17 | `POST /requests/{id}/cancel` (requester only, no idempotency key) → 200 request with `status: "cancelled"`; repeat → 200; `paid` or `declined` → 409 `request_not_pending`; not requester → 403; unknown → 404. | T |
| P18 | `GET /requests` → `{requests, has_more}`; only requests where caller is requester or payer; newest first by `created_at`. | T/H |
| P19 | `direction`: `incoming` (caller is payer), `outgoing` (caller is requester), absent = both; unknown value → 422. | T |
| P20 | `status`: one of `pending`, `paid`, `declined`, `cancelled`, absent = all; unknown value → 422. | T |
| P21 | `limit` default 50 (1..200), `offset` default 0 (≥ 0); `has_more` true iff items exist beyond the last returned. | T: page boundaries |
| P22 | `POST /splits {amount, participant_handles, note?}` → 201 `{split_id, amount, currency, note, shares, requests, created_at}`. `shares` covers every participant incl. caller in given order and sums to `amount`; `requests` covers every participant except the caller in the same order, each `pending`, caller as requester, amount = that share, note = split note. | T/H |
| P23 | Caller may be included or omitted in `participant_handles`; if omitted the caller gets no share (shares are over the listed handles only). | T |
| P24 | Split errors: amount rule → 422; `participant_handles` empty or with a duplicate → 422; note > 200 → 422; any unknown handle → 404; nothing is created on error. | T |
| P25 | A split whose only participant is the caller is valid: one share, `"requests": []`. No split checks any balance. | T |
| P26 | `GET /activity` → `{payments, has_more}`; newest first by `created_at`; `limit`/`offset` exactly as `GET /requests`. | T/H |
| P27 | Feed rule: a payment appears iff `visibility` is `public` OR caller is sender or receiver. Private payments visible to both parties, hidden from third parties (including operators). | T |
| P28 | Requests and splits never appear in `/activity`; requests are never visible to third parties (third party sees none in `GET /requests`; pay/decline/cancel by an outsider is 403). | T |
| P29 | Visibility is one value on the payment, identical for every viewer; a request carries no visibility. | T |

## S — Money and rounding (§9)

| Row | Requirement | Check |
|---|---|---|
| S1 | Shares are whole minor units, sum exactly to `amount`, differ by at most one; larger shares go to the first participants in given order. Table: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333,333,333; 5/5 → 1,1,1,1,1. | T: all five rows |
| S2 | Different `participant_handles` order gives the extra unit to a different person. | T |
| S3 | A share of 0 is legal and still creates a request for that participant (amount 0, pending). Paying a 0 request must not break conservation or produce 5xx. | T |
| S4 | Each split's shares are independent of previous splits; after any number of splits are paid in full, balances still sum to the seeded total. | T |

## X — Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| X1 | `GET /_test/export` (no auth) → 200 JSON object with `track: "pocketful"`, `format_version: 1`, `state` (JSON object). | T |
| X2 | `POST /_test/import` (no auth) with an unchanged export → 204; atomically replaces all state. | T |
| X3 | Import works in a **fresh second container** of the same image (no dependency on the source process, files, volume, port or address). | T: export from container A, import into container B |
| X4 | Import is replacement, not merge: previous destination data and credentials are gone; repeating the import duplicates nothing. | T |
| X5 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track or version, or invalid state → 422 `validation_failed`, destination unchanged. | T |
| X6 | Export is an atomic read-only snapshot; later writes on the source do not change an already-taken export; export itself changes nothing. | T + C: export during load is internally consistent (balances sum to seeded total) |
| X7 | Preserved across export→import: accounts and hashed-password login, existing bearer tokens, currency/minor_units, balances, payments, requests, operator permissions, handles. Ids and timestamps identical (not regenerated); balances not re-applied. | T: compare `/me`, `/activity`, `/requests` before and after |
| X8 | All completed idempotent request bodies and original responses preserved: replay after import → 200 with the original body; same key with different body → 409. Failed request keys remain reusable. | T |
| X9 | Reset after import clears everything, including imported state. | T |
| X10 | Export/import complete within 10 s. | T |
| X11 | Settlement membership, settlement retry responses and operator permissions survive export→import. | T |

## N — Atomic net settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| N1 | `POST /settlements` requires an operator and an idempotency key: no token → 401; authenticated non-operator → 403 `forbidden`. | T |
| N2 | Body `{"transfers":[{from_handle,to_handle,amount,note?,visibility?}, ...]}`; 1..32 objects (0 and 33 rejected; 1 and 32 accepted). Malformed batch shape (missing/non-array `transfers`, non-object entry, count out of range) → 422 `validation_failed`. | T |
| N3 | Each entry follows ordinary payment rules: amount 1..1000000000 integral; note string ≤ 200, default `""`; visibility `public`/`private`, default `public`. Unknown handle → 404; `from_handle == to_handle` → 422 `self_payment`. Unknown fields ignored. | T |
| N4 | Entry errors take precedence in input order (first failing entry decides the error), and before insufficient funds. | T: batch with entry-2 invalid and entry-3 unknown handle → entry-2's error; unaffordable + invalid entry → entry error |
| N5 | Affordability is on the **net**: affordable iff every wallet's balance after all transfers is ≥ 0; a wallet may send more than its starting balance if incoming transfers in the same batch cover it (e.g. bob has 0: ada→bob 100, bob→cy 50 succeeds). Otherwise 409 `insufficient_funds`. | T |
| N6 | All-or-nothing: on any failure nothing commits — no payment, no balance change, no idempotency key claimed. | T + C |
| N7 | Success → 201 `{settlement_id, committed_at, payments}` with `payments` in input order; each member is an ordinary payment with `settlement_id` set, `request_id` null, and `created_at` equal to `committed_at` (identical across members). | T |
| N8 | Every payment object in every response (payments, pay, activity, replays) carries `settlement_id`; null for non-members. | T |
| N9 | Members follow ordinary feed visibility: private members visible only to their sender/receiver; the operator sees them in `/activity` only if public or a party. The settlement response itself always contains every member. | T |
| N10 | Operator permission grants nothing else: operator cannot see or act on others' requests or private activity. The operator may move money between wallets that are not their own, and may be a party. | T |
| N11 | Replay → 200 with the original complete response; concurrent identical → one 201; different body same key → 409. | T + C |
| N12 | Invariants I1/I2 hold under concurrent settlements mixed with payments. | C |
| N13 | Operators come from the last reset/import; reset without `settlement_operator_ids` → no operators. | T |

## Decisions recorded by the Architect (spec is silent or needs a reading)

| # | Choice | Reason |
|---|---|---|
| Q1 | Check order on idempotent writes: authentication (401) → `Idempotency-Key` presence (400) and length (422) → body parses as a JSON object (400) → claimed-key resolution (200 replay / 409 reuse) → permission (403, e.g. non-operator) and field validation → resource checks → funds. | §7 last paragraph fixes key resolution after parse+auth and before validation; auth-first matches "No token gives 401". |
| Q2 | Validation order inside an endpoint: wrong JSON type (400) / field rules (422) before handle lookup (404) before self-payment/self-request (422) before funds (409). For settlements, per entry in input order. | §11 "Entry errors take precedence in input order, before insufficient funds"; shape before existence is the conventional reading. |
