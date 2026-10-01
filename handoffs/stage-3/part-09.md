@vibhor15/nightshift-implementer STAGE 3 HANDOFF — part 9 of 13: stage-2 acceptance map (verbatim from acceptance/stage-2.md; still applies to stage-3/), piece 3 of 3. Do not start until part 13 (FINAL).

## V. Authorizations — UI

| # | Requirement | Check |
|---|---|---|
| V1 | `/` wallet: `wallet-available` formatted `available` with `data-amount`, presented as the headline number (largest, first); `wallet-balance` (total) and `wallet-held` visibly secondary; `wallet-held` formatted `held` with `data-amount`, ABSENT from the DOM when held is zero | O |
| V2 | Authorise form on BOTH `/` and `/authorizations` (CHOICE; reason: the spec does not say which screen carries it, and a check may look on either; one form per page so no testid is duplicated in a DOM): `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility` (option values `public`/`private`), `authorize-submit`; same input rules as the pay form; `authorize-error` when refused incl. insufficient available funds; success refreshes available/held | O |
| V3 | `/authorizations`: `authorization-list` children newest first; `authorization-item-{id}` with `data-status`; `authorization-amount-{id}` exactly the formatted authorised amount; `authorization-captured-{id}` formatted captured amount, present ONLY when status is `captured`; `authorization-expires-{id}` text is the RFC 3339 `expires_at` exactly as the API returns it | O |
| V4 | `authorization-capture-amount-{id}` (decimal input pre-filled with the remaining amount as a plain decimal, e.g. `20.00`) and `authorization-capture-{id}` ONLY on incoming `open`; `authorization-void-{id}` ONLY on outgoing `open`; none on closed or clock-expired ones | O |
| V5 | Capture and void work from the screen and refresh the list; `authorization-error` when refused (expired, exceeds, not open, bad decimal input) and the list refreshes so stale controls disappear | O |
| V10 | A refresh or re-render of a list never discards what the user is typing: a value edited in `authorization-capture-amount-{id}` (and the keep-on-hold checkbox, and the per-request visibility selector on `/requests`) survives a list refresh that arrives before the click, as long as that item is still actionable; the amount actually captured is the amount shown in the input at click time (stage-2 Verifier observation 3) | O: delay a refresh with `page.route`, type, let it land, click |
| V6 | `empty-authorizations` shown when the list is empty. CHOICE: `authorization-list` itself is ALWAYS in the DOM once the screen has loaded (same pattern as `incoming-list`), with no children when empty | O |
| V9 | CHOICE: `/authorizations` also shows the wallet summary (`wallet-available` headline, `wallet-balance`, `wallet-held` with the same rules as V1) and refreshes it after authorise/capture/void. Reason: "the same balance refresh rules apply to the available and held amounts"; the user needs to see what a hold did | O |
| V7 | UI reflects seeded and new holds; available shown as spending balance immediately after a reset with open holds; refresh rules (R1–R3) also apply to available and held | O |
| V8 | CHOICE: a "keep the rest on hold" checkbox next to the capture button sends `final:false`; unchecked by default. Reason: extended capture mode must be usable by a person; default behaviour unchanged | O |

## W. Product quality (judged by review)

| # | Requirement | Check |
|---|---|---|
| W1 | One consistent visual system: typography scale, spacing, colour tokens, control and feedback styles shared by all six screens; calm, trustworthy consumer-finance character; primary action obvious on each screen | O: screenshots of every screen |
| W2 | At a 375 CSS-px viewport and at desktop widths: all required flows usable, no horizontal page scrolling (`scrollWidth <= clientWidth`), long notes/handles wrap | O: automated overflow check at 375 and 1280 on every route with long-content fixtures |
| W3 | Every input has a visible label; keyboard focus is clearly visible; text/control contrast ≥ WCAG AA; forms submit with Enter; errors are announced (`role="alert"`) | O |
| W4 | Considered empty, loading and error states on every list and form | O |
| W5 | People, amounts and timestamps formatted for people (display name + @handle, formatted money, readable local time); technical ids only where they help | O |
| W6 | Code another developer could maintain: UI assets as separate files with clear modules; money parsing/formatting and split computation unit-tested and shared with nothing duplicated | O: review |

## X. Concurrency (spec "Concurrent operations")

| # | Requirement | Check |
|---|---|---|
| X1 | Concurrent requests give the same results as some serial order and the invariants hold at every read: mixed bursts of payments, authorizations, captures, voids, settlements over the same wallets keep Σ total constant, `available ≥ 0`, `held` = Σ open remainders, no 5xx | O: 50-way mixed burst with invariant reads interleaved |
