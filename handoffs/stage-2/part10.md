@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: stage-2 map M1..Z2 and stage-1 map A1..K10 · Revision: f470dbb7a1fcf1868bb3a6ddf16440ca278d54a8 (maps and status; stage-1/ accepted at 77409dda43334b784ca1125d2d990ba51478abf6; stage-2/ does not exist yet) · Files: acceptance/stage-2.md, acceptance/stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-2/ to be built / not yet built · Repro: n/a · Next: Implementer builds stage-2/ and reports a committed revision; Verifier prepares its checks now and waits for that revision.

STAGE 2 HANDOFF, part 10 of 10. FINAL PART. ACCEPTANCE MAP, stage 1, as it stands (part 2 of 2: sections G to L; its Commands section is superseded by the stage-2 commands in part 1), then what each seat does now.

## G. Splits and rounding (§8, §9)

| Row | Requirement | Check |
|---|---|---|
| G1 | `POST /splits` `{amount,participant_handles,note?}` -> 201 `{split_id, amount, currency, note, shares:[{handle,amount}], requests:[…], created_at}`. | H, P |
| G2 | Shares: whole units, sum exactly to `amount`, differ by at most one, the larger shares go to the first participants in the given order: 1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3 -> 4,3,3; 999/3 -> 333,333,333; 5/5 -> 1×5. Independent of earlier splits. | H, P |
| G3 | `shares` lists every participant including the caller in the given order. `requests` lists one pending request per participant except the caller, same order, caller as requester, amount = that share, note = the split note. A 0 share still creates a request (amount 0 is legal for a split-created request, and paying it moves 0 and marks it paid). | H, P |
| G4 | The caller may be listed or omitted. If omitted, the amount is divided among the listed participants only **[D]** (shares "cover every participant" and "always sum to amount"; the caller is not a participant unless listed). A split whose only participant is the caller is valid: one share, `requests: []`. | H, P |
| G5 | `participant_handles` empty or with a duplicate -> 422; any unknown handle -> 404; amount and note rules C3, C4. **[D]** Precedence: type errors 400 -> amount/note/empty/duplicate 422 -> unknown handle 404. A 1000-handle list is validated, not crashed, and answers within 5 s. | H, P |
| G6 | A split checks nobody's balance and moves no money. A split is not a feed item. Created requests are atomic with the split: a rejected split creates none. | H, P |
| G7 | After any number of splits are paid in full, balances still sum to the seeded total. | P |

## H. Activity feed (§4, §8)

| Row | Requirement | Check |
|---|---|---|
| H1 | `GET /activity` returns payments only: a payment appears iff it is `public`, or the caller is its sender or receiver. No other rule. | H, P with three users |
| H2 | A `private` payment is visible to both of its parties with the same single `visibility` value, hidden from everyone else, including a settlement operator who is not a party. | H, P |
| H3 | Newest first by `created_at`; `{payments:[…], has_more}`; `limit`/`offset` per C9; request-only parameters (`direction`, `status`) are ignored here. | H, P |
| H4 | Payments made by paying a request and settlement members follow the same rule and carry `request_id` / `settlement_id`. | P |

## I. Idempotency (§7)

| Row | Requirement | Check |
|---|---|---|
| I1 | Five paths need a key: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`. Decline and cancel do not. | H, P |
| I2 | A key is scoped to the authenticated user and to the method and path: two users with one key string do not interact; the same key and body on a different path (including a different `{id}`) is a first use and succeeds. | H, P |
| I3 | First use -> 201. Replay (same user, path, key, body) -> 200 with a body equal as a JSON value to the original, and no state change, even after the resource has since changed (request paid, declined, cancelled; balances moved). | H, P |
| I4 | Same key with a different body -> 409 `idempotency_key_reuse`. Body sameness is JSON-value equality after parsing: key order and whitespace do not matter; an extra unknown field makes it a different body. **[D]** Numbers compare by numeric value (`1000` = `1000.0` = `1e3`). | H, P |
| I5 | A key whose original request failed with 4xx is not claimed: reusing it, with the same or a different body, is a first use. | H, P |
| I6 | An already-claimed key is resolved after authentication and JSON-object parsing and before field validation and resource checks: changing a successful request to an invalid body under the same key is 409 `idempotency_key_reuse`, not 422/404/403. | P |
| I7 | Concurrent identical requests with an unused key: exactly one 201, all others 200 with the same body, one effect. | P: 50-way burst per path |
| I8 | Concurrent same-key requests with different bodies: exactly one takes effect; the others get 409 `idempotency_key_reuse` (or, if theirs failed validation on its own merits before the claim, their own 4xx); never two effects. | P |

## J. Export and import (§10)

| Row | Requirement | Check |
|---|---|---|
| J1 | `GET /_test/export` -> 200 `{track:"pocketful", format_version:1, state:{…}}`, no auth; an atomic read-only snapshot unaffected by later writes. | H, P |
| J2 | `POST /_test/import` with an unchanged export -> 204 and atomically replaces all state. It works in a different container of the same image (no dependency on the source process, files, volume, port or address). | P: export from container A, import into fresh container B |
| J3 | Import is replacement, not merge: previous destination users, tokens, records and operator grants are gone; importing twice gives the same state with nothing duplicated. | P |
| J4 | Preserved across export/import: accounts and password login, existing bearer tokens, currency and minor units, balances, payments (ids, timestamps, notes, visibility, links), requests and their status, splits' requests, settlement membership, operator grants, every completed idempotent request's body and original response. Nothing is regenerated or replayed against a balance. | H, P: replay each of the five paths after import -> 200 same body; old token works; feed equal item for item |
| J5 | Keys of failed requests stay reusable after import; new IDs issued after import do not collide with imported ones. | P |
| J6 | Invalid JSON -> 400 `malformed_request`. Missing `track`/`format_version`/`state`, wrong track or version, or an invalid `state` (wrong shape, tampered so it is inconsistent or unreadable) -> 422 `validation_failed`, destination unchanged. Never 5xx. | P |
| J7 | Reset clears everything, including imported state. Export and import each finish within 10 s on a populated state. Export holds password hashes, never plaintext passwords. | P, I |

## K. Settlements (§11)

| Row | Requirement | Check |
|---|---|---|
| K1 | Fixture `settlement_operator_ids` (array of user ids, default `[]`) grants the operator permission. No token -> 401; authenticated non-operator -> 403 `forbidden`. Users created by signup are never operators. | H, P |
| K2 | `POST /settlements` `{transfers:[{from_handle,to_handle,amount,note?,visibility?}]}` with 1..32 entries; the operator may move money between any wallets, not only their own. | H, P |
| K3 | Malformed batch shape (`transfers` missing, not an array, empty, more than 32, an entry that is not an object) -> 422 `validation_failed`. | P: 0, 1, 32, 33 entries |
| K4 | Each entry follows the payment rules: amount C3, note C4, visibility C5 with defaults; unknown handle (either side) 404; `from_handle` = `to_handle` -> 422 `self_payment`. Entry errors are reported in input order (the first bad entry decides) and always before `insufficient_funds`. **[D]** Inside one entry: field validation -> unknown handle -> self-transfer. A missing handle field is 422; a handle of the wrong JSON type is 400 (C2). | P |
| K5 | Affordability is judged on the net result: the settlement is affordable iff every wallet's balance after all its incoming and outgoing transfers is >= 0, so a wallet may pass money on that it only receives inside the batch, and the order of entries does not matter. Not affordable -> 409 `insufficient_funds`. | H, P: chain a->b->c where b starts at 0 |
| K6 | All or nothing: on any failure no balance changes, no payment is created, and the idempotency key is not claimed. | P |
| K7 | 201 `{settlement_id, committed_at, payments:[…]}` with `payments` in input order; each member is an ordinary payment (E1 shape) with `settlement_id` set, `request_id` null, and `created_at` equal to `committed_at` for every member. Non-members expose `settlement_id: null`. | H, P |
| K8 | Members follow the ordinary feed rule: a private member is visible only to its sender and receiver; the operator sees it only if a party or if public. The 201/replay response still contains every member's receipt. Being an operator gives no access to other users' requests or private payments. | P |
| K9 | Replay -> 200 with the original complete response; same key with a different body -> 409; I-rows apply (fifth idempotent path). Concurrent settlements and payments over the same wallets keep invariants B9..B10. | P |
| K10 | Reset and import preserve operator grants, original payments, requests, settlement membership and retry responses (as the fixture / export state them). | P |

## L. Stage boundary

| Row | Requirement | Check |
|---|---|---|
| L1 | `stage-1/` implements the stage-1 specification only: no browser UI, no endpoints, fields or behaviour from a later stage. The harness overshoot line for stage 2 must be `fail` and the final lines `claimed stage: 1`. | H, I |
| L2 | The code is written to the specification, not to the supplied checks: no behaviour keyed to fixture names, test ids or check-specific values. | I |
| L3 | Maintainable: clear module layout, one place for validation, one for the ledger/atomicity, automated tests the Implementer ran, RUN.md accurate. | I |


## What each seat does now

Implementer:
1. Copy stage-1/ (as at 77409dda43334b784ca1125d2d990ba51478abf6) to /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-2/ and extend the copy to the stage-2 specification (parts 1 and 2), keeping every stage-1 requirement (parts 3 to 5). Satisfy every row of the stage-2 map (parts 6 to 8) and of the stage-1 map (parts 9 and 10). Do not touch stage-1/. Update RUN.md for stage 2.
2. Keep the property the stage-1 design rests on: every state change is one synchronous step on the event loop, and the pipeline rejects an idempotent handler that returns a promise. Holds, captures, voids and clock expiry must fit that rule. Expiry must be derived from the clock at every read and write, not from a timer that might not have fired.
3. Rows marked [D] are the Architect's resolution of an open choice. Implement them as written; if you find evidence in the specification that one is wrong, say so in your report with the section, do not silently diverge.
4. The browser product is a quarter of how this work is judged. Treat rows V1 to V7 as requirements, not decoration: design the visual system first (tokens, type scale, spacing, colour roles, component styles), then the six screens. Look at your own screens in a real browser at 375 px and 1280 px before you report, and fix what looks wrong.
5. Write automated tests for what the supplied checks do not reach: holds under concurrency, capture modes, expiry by the clock, the seven idempotent paths, import of a stage-1 export, money formatting and decimal parsing, the split preview, and browser tests of your own for the lost-response retry, latest-refresh-wins and the upgrade without reload. Run them, and run the harness in host mode and in isolated mode.
6. Commit under your own seat identity on branch main. Do not rewrite history and do not push. Commit in meaningful steps rather than one large commit if that is natural.
7. Report in this room to both the Architect and the Verifier, starting with the evidence header: the full commit hash, files touched, each command with its result (harness --out directory and final lines), any row you could not satisfy, any [D] row you dispute, and what you did not test.

Verifier:
1. While the Implementer builds, prepare your checks from the two specifications and the two maps: API probes for rows M to O, browser probes (Playwright with Chromium is available in /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs/.venv) for rows Q to U, and a screenshot review for rows V1 to V6. Keep your material outside stage-2/. Do not edit anything under stage-1/ or stage-2/.
2. When the Implementer reports a committed revision, verify that exact full revision: build from a clean copy by following stage-2/RUN.md, run the harness in host mode and in isolated mode with new --out directories, re-run your stage-1 probes against the stage-2 image, run your stage-2 probes, take and inspect screenshots of every screen at 375 px and 1280 px in its main states, and inspect the source for rows marked I. Confirm stage-1/ is unchanged since 77409dda43334b784ca1125d2d990ba51478abf6.
3. Report a verdict to the Architect and the Implementer, starting with the evidence header: PASS, BLOCK or INCONCLUSIVE for that full revision, with every command and its result, and for each finding the row, expected and actual, and the smallest reproduction. Any unmet row is blocking unless you show the specification does not require it. Judge product quality (rows V) against the specification's own words; say concretely what falls short.

END OF STAGE 2 HANDOFF (part 10 of 10, final).
