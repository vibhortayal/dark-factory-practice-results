@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: T1, Q4 (blocking, from the Verifier's BLOCK); new row Q11; rows M4, O9, N12, V3, V4, V5 (corrections folded into this fix) · Revision: 427730e1c2d1d84edfc66233b81ceab77885c07b is BLOCKED (stage 2 fix round 1 of at most 5) · Files: stage-2/public/js/screens/requests.js line 27; stage-2/RUN.md; stage-2/src (snapshot import, authorisation listing, expiry sweep/clock); stage-2/public/css and feed/wallet components; acceptance/stage-2.md · Command: the Verifier's reproduction below · Expected / actual: `[data-testid="request-pay-visibility"]` with a request whose id is `visibility` matches one BUTTON / matches a SELECT and a BUTTON · Repro: below · Next: Implementer.

STAGE 2 FIX REQUEST, round 1 (single message, final). This message also adds one row to the stage-2 acceptance map, which is why it goes to both seats.

## Blocking finding (Verifier, verdict BLOCK on 427730e1c2d1d84edfc66233b81ceab77885c07b)

Finding 1 (rows T1, Q4). Stage-2 specification, Requests table: "`request-pay-{request_id}` | Button. Present only on a `pending` incoming request". The requests screen adds a visibility `<select>` with `data-testid="request-pay-visibility"` (public/js/screens/requests.js line 27), which has the specified form with `request_id` = `visibility`.
Repro: reset with a fixture holding the pending request `{"id":"visibility","requester_id":"u_bob","payer_id":"u_ada","amount":100,"note":"n","status":"pending"}`; sign in as ada; open `/requests`; evaluate `Array.from(document.querySelectorAll('[data-testid="request-pay-visibility"]')).map(e => e.tagName)`. Actual `["SELECT","BUTTON"]`, expected `["BUTTON"]`. Any check that selects pay buttons by the prefix `request-pay-` also picks up the select.

## Architect's ruling: fix the class of fault, not the one id. New map row Q11 (now in acceptance/stage-2.md), in full

"Q11. Any element or test id the UI adds beyond S2 must not fall inside a specified test-id family for any possible resource id (ids are opaque strings, seeded ids are arbitrary): nothing added may match `activity-item-*`, `activity-parties-*`, `activity-amount-*`, `activity-note-*`, `request-item-*`, `request-amount-*`, `request-pay-*`, `request-decline-*`, `request-cancel-*`, `split-share-*`, `authorization-item-*`, `authorization-amount-*`, `authorization-captured-*`, `authorization-expires-*`, `authorization-capture-amount-*`, `authorization-capture-*`, `authorization-void-*`, or equal a fixed specified id. Each specified id names exactly the element S2 describes, whatever the resource id is."
Check: seeded resources whose ids are the suffix words the UI uses (`visibility`, `amount`, `keep-open`, `error`).

Note the specification's own families overlap: `authorization-capture-{id}` and `authorization-capture-amount-{id}` (an authorisation whose id is `amount-X` collides with the amount input of X). That overlap is the specification's and cannot be removed; do not add to it. Review every id you added (`*-success`, `*-uncertain`, `load-error`, `request-pay-visibility`, `authorization-keep-open-{id}`) and every fixed id (`request-error`, `authorization-error`, `empty-requests`, …) against row Q11: a fixed specified id such as `request-error` cannot be renamed, but an added one must sit outside all the families above. Add a test that enumerates the test ids the UI can emit and fails on any that enters a specified family.

## Also required in this fix (the Verifier's notes that are stated rules or cheap; not separately blocking, but they must not come back)

1. Row M4: import must reject (422, destination unchanged) a state whose payment carries a non-boolean `seeded` flag; treat every leaf of the state as typed.
2. Row O9: `GET /authorizations` is "newest first by `created_at`": sort by the stored `created_at` (ties by creation order), so seeded entries that supply their own `created_at` out of order are listed correctly. The same must hold for any other list ordered by `created_at` (`GET /requests`, `GET /activity`) when seeded or imported records carry their own times.
3. Row N12: read the clock once per request and use that one instant for the expiry sweep, for the handler's decisions and for the timestamps it writes, so a capture can never be stamped at or after the `expires_at` of the hold it captured.
4. stage-2/RUN.md: remove the stale "Timestamps: whole seconds" line.
5. Rows V3 to V5, from the Verifier's screenshot review: (a) at 375 px a feed row with a very large amount (10,000,000.00 EUR) leaves the note a column about nine characters wide: let the amount wrap below or the row stack on narrow screens; (b) the "On hold" marker is a small bar that reads as a stray mark: replace it with a marker that reads as intended or remove it; (c) there must be a visible, considered loading state on each screen while its first data is being read (the Verifier could not capture one): make it observable when the read is slow.

## Report

Implementer: commit under your seat identity, then report the new full revision to the Architect and the Verifier with the evidence header, the reproduction's new output, your tests, and harness host and isolated runs with new --out directories, run from /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs:
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --out ../band-work/checks/s2-impl-04
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/s2-impl-05
(use the next free numbers if these exist). stage-1/ must stay unchanged.
Verifier: when that revision is reported, verify it in full against both specifications and both maps including Q11 (everything else you hold is unchanged), and report PASS, BLOCK or INCONCLUSIVE for that full revision.
