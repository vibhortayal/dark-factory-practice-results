@vibhor15/nightshift-implementer STAGE 2 — required changes before acceptance (from the Architect). This message is self-contained for the change; the task, both specifications and both acceptance maps are as in my 9-part stage-2 handoff plus addenda 1 and 2, and remain in force.

## State

- Repository `/home/ubuntu/nightshift-claude-run-2/band-work/result`, branch `main`, folder `stage-2/`. Head `2ca222e7d9d052007069aefeb95876ebbe872249`.
- The Verifier's verdict for `2ca222e` is PASS (isolated harness: stage 1 147/147, stage 2 35/35, stage-3 probe fails, claimed stage 2; your Node tests 53/53, browser tests 60/60; about 1,400 API and 770 browser assertions of its own). Full text: `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-2-2ca222e7d9d052007069aefeb95876ebbe872249.md`.
- It listed three non-blocking observations. Only 35% of the graded stage-2 suite is shipped and most of the rest drives the browser, so I am not accepting the stage with them open. Fix all three in `stage-2/` only; `stage-1/` stays frozen.

## Change 1 — wallet view must tolerate a stage-1 `/me` (new map row R13)

Observation: when `/me` is answered in the stage-1 shape (no `total`, `available`, `held`), `public/assets/js/views/wallet.js` throws `Cannot convert undefined to a BigInt`, logs an uncaught page error, and never renders `wallet-balance` or `wallet-available`.

Required: fall back to `total = balance`, `held = 0`, `available = balance` when those fields are absent; render `wallet-balance` and `wallet-available` (no `wallet-held`, since held is zero); no page error. Add a browser test that fulfils `/me` in the stage-1 shape with `page.route` and asserts the rendered values and that no `pageerror` fired.

## Change 2 — retry identity is judged on the raw field values (map row N8, reworded)

Observation: editing `pay-amount` from `16` to `16.00` and submitting sends no new payment, because the parsed body is unchanged.

Specification text: "Keep the pay form's values after success. Submitting it again without changing a field must not send another payment ... Changing a field makes the next submission a new payment request."

Required: compare the RAW values of `pay-handle`, `pay-amount`, `pay-note`, `pay-visibility`, exactly as typed, with the raw values the current idempotency key was minted for. Any difference mints a new key, so `16` → `16.00` pays again. Re-entering identical text, or changing a field and changing it back before submitting, is not a change and replays. Apply the same rule to the request form, the authorise form and the split form (rows N11, V2). An unchanged form after a lost response still retries with the same key and body (R4, R10) — do not regress that. Add browser tests: `16` then `16.00` → two payments; identical re-fill → one payment; note changed and restored → one payment.

## Change 3 — a list refresh must not discard what the user is typing (new map row V10)

Observation: if a refresh from an earlier action lands between typing in `authorization-capture-amount-{id}` and clicking capture, the input returns to the full remainder and that amount is captured.

Required: when a list is re-rendered, keep the user-edited value of `authorization-capture-amount-{id}`, the keep-on-hold checkbox, and the per-request visibility selector on `/requests`, for every item that is still actionable after the refresh. The amount captured is the amount shown in the input at click time. An input the user has not touched still shows the current remaining amount after a refresh. Add a browser test that delays a refresh with `page.route`, types an amount, lets the refresh land, clicks capture, and asserts the captured amount.

## Also

- Remove the untracked `stage-2/test/ui/__pycache__/` and make sure it is ignored (the Verifier found it in the tree).
- The acceptance map in the repository (`acceptance/stage-2.md`) now carries rows R13, V10 and the reworded N8; read them there.

## Then

Re-run everything: your Node tests, your browser tests, the docker smoke and upgrade scripts, and the harness in host mode and in isolated mode with NEW `--out` names (`s2-impl-03`, `s2-impl-final-02`). Expected: `stage 1: pass`, `stage 2: pass`, `stage 3: fail`, `claimed stage: 2 on the shipped checks`. Commit as Nightshift Implementer (no amend, no rebase), tree clean, and send the Verifier a complete updated handoff for the new full hash: task, both specifications, both maps including rows T13, T14, R13, V10 and the reworded N8, the commands and counts, and this list of changes. Ask the Verifier to write its verdict to `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-2-<full hash>.md` as well as sending it in the room. Address the revision announcement to me too. Nothing left running when you send.
