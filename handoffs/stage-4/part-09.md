@vibhor15/nightshift-implementer STAGE 4 HANDOFF — part 9 of 15: stage-2 acceptance map (verbatim from acceptance/stage-2.md; still applies), piece 1 of 3. Do not start until part 15 (FINAL).

# Stage 2 acceptance map

Source: `pocketful/spec/stage-2.md` in the kickoff checkout (section numbers such as §5, §7
refer to `stage-1.md`). `stage-2/` is `stage-1/` copied forward and extended; every row of
`acceptance/stage-1.md` continues to hold for `stage-2/` except where a row below changes it.
"S" = at least partly covered by a shipped check (only 35% of the graded stage-2 suite is
shipped); "O" = must be covered by the band's own tests. **CHOICE** rows resolve points the
specification leaves open; if a shipped check contradicts one, the check wins and the
contradiction is reported to the Architect.

## K. Carry-forward and delivery

| # | Requirement | Check |
|---|---|---|
| K1 | `stage-2/` is a complete, buildable folder with its own `Dockerfile` and `RUN.md`; `stage-1/` is left byte-for-byte unchanged | O: `git diff <accepted stage-1 rev> -- stage-1` is empty |
| K2 | All stage-1 behaviour still holds (API, errors, idempotency, export/import, settlements) | S: harness `--stage 2` runs suite 1 against `stage-2/`; O: the stage-1 own tests still pass in `stage-2/` |
| K3 | Runs in isolation: no outbound network at run time; ALL UI assets (scripts, styles, fonts, icons) are served from the image — no CDN, no web fonts, no external URLs anywhere in the HTML/CSS/JS | S: `--mode isolated`; O: grep built assets for `http://`/`https://` hosts; browser run with network blocked shows no failed requests |
| K4 | No stage-3+ surface: no `as_of`/`known_at` handling, no `/statement`, no corrections/revisions endpoints, no `closed_at` on authorizations, no refunds, no correction batches | S: overshoot probe `stage 3: fail`, `claimed stage: 2`; O: route review |
| K6 | Carried-forward fix (stage-1 Verifier advisory F2): an `amount` literal is judged on its exact decimal value, so `1.0000000000000000000001` and `0.99999999999999999999999` are 422 `validation_failed`, while `1000`, `1000.0`, `1e3`, `1.5e1` stay valid. Applies to every amount field incl. authorizations and captures. `stage-1/` itself is NOT touched | O: raw-body tests |
| K5 | Resource limits unchanged (2 vCPU, 2 GiB, 60 s to healthy, 50 in flight, 5 s per request) | S (isolated) + O |

## L. Routes and content negotiation

| # | Requirement | Check |
|---|---|---|
| L1 | Screens reachable directly by URL: `/` (balance, pay form, request form, activity feed), `/requests`, `/split`, `/signup`, `/login`, `/authorizations` | S + O: `page.goto` each, signed in and signed out |
| L2 | `/requests` and `/authorizations` are shared: `Accept` containing `text/html` → the UI (200 HTML, no auth needed to load the shell); any request without `text/html` in `Accept` → the JSON API exactly as before (incl. 401 envelope without a token) | S + O: `curl` with and without the header; `Accept: */*` and no `Accept` → JSON |
| L3 | CHOICE: a signed-out visitor to a protected screen (`/`, `/requests`, `/split`, `/authorizations`) is sent to `/login`; after a successful login/signup the user lands on `/`. `/login` and `/signup` ALWAYS render their forms, also when already signed in (the shipped route check signs in and then expects `login-submit` / `signup-submit` at those URLs), with `current-user` shown as on every screen | S + O |
| L4 | Consistent navigation between `/`, `/requests`, `/split`, `/authorizations` on every signed-in screen; other screens (if any) reachable through the UI | O: click-through |
| L5 | The API remains JSON for every non-HTML client: `POST` endpoints never return HTML; UI routes `/`, `/split`, `/signup`, `/login` do not shadow any API path | O |

## M. Signup, login, session

| # | Requirement | Check |
|---|---|---|
| M1 | `signup-email`, `signup-password`, `signup-display-name`, `signup-submit`; success signs the user in | S |
| M2 | `login-email`, `login-password`, `login-submit` | S |
| M3 | `auth-error` present ONLY when there is an error (bad login, email/handle taken, short password, bad email); absent otherwise and cleared on a new attempt | S + O: each failure cause; assert absent on fresh load |
| M4 | `current-user` visible on EVERY screen when signed in, text contains the display name; `current-handle` text is exactly the handle (no `@`, no words, no whitespace padding) | S + O on all six routes |
| M5 | `logout-button` signs out: `current-user` disappears, protected data no longer shown | S |
| M6 | The session survives page navigation and reload (token kept client-side, e.g. localStorage); it also survives an export→import upgrade because tokens are preserved | O (see R) |

## N. Wallet and pay form — `/`

| # | Requirement | Check |
|---|---|---|
| N1 | `wallet-balance`: text exactly the formatted `total`; `data-amount` = minor units as plain digits | S |
| N2 | Formatted amount: decimal with exactly `minor_units` places, one space, currency code — `100.00 EUR`, `0.05 EUR`, `1200 JPY` (no decimal point for 0), `1.500 BHD`; no thousands separators, no sign, no symbol. Used for every "formatted amount" testid | S + O: unit test of the formatter for 0/2/3 units incl. values < 1 unit |
| N3 | `pay-handle`, `pay-amount`, `pay-note`, `pay-visibility` (a `<select>` whose option values are exactly `public` and `private`), `pay-submit` | S |
| N4 | Decimal input rule (shared by pay, request, split, authorize, capture inputs): `15.00` → 1500, `15` → 1500, `15.5` → 1550 for 2 units; more than `minor_units` decimals (`15.005`; any `.` fraction when units = 0) or nonnumeric/empty/negative input shows the form's error element and sends NO request. Conversion is exact string arithmetic, never float multiplication | S + O: unit tests of the parser (e.g. `0.29`, `1.1`, `4.35`, `.5`, `5.`, ` 5 `, `1e3`, `-1`, `abc`); network spy proves no request |
| N5 | CHOICE for parser edge cases: surrounding whitespace is trimmed; `.5` and `5.` are rejected; a leading `+`, exponent or thousands separator is rejected; zero is passed through and the server refuses it. Reason: "as a person would type it" with no rounding or guessing | O |
| N6 | `pay-error` shown when the payment is refused (insufficient funds, unknown handle, self payment, validation, bad input); absent after a later success | S + O |
| N7 | Pay form keeps its values after success. Submitting again with NO field changed sends no new payment (same idempotency key and body → replay): balance falls once, feed has one payment, `pay-error` absent | S |
| N8 | Changing any field (handle, amount, note, visibility) makes the next submission a new payment (new key). CHOICE (after stage-2 Verifier observation 2): "changed" is judged on the RAW field values as typed, compared with the values the current key was minted for — so editing `16` to `16.00` IS a change and pays again, while re-entering the identical text (or changing a field and changing it back before submitting) is not. Reason: the literal text "changing a field makes the next submission a new payment request" | S + O per field, incl. `16` → `16.00` |
| N9 | A double click / rapid double submit leaves exactly one payment | S |
| N10 | `request-handle`, `request-amount`, `request-note`, `request-submit`; `request-error` when refused (unknown handle, self request, bad amount) | O |
| N11 | CHOICE: request form uses the same retry identity rule as the pay form (unchanged form re-submitted = replay). Reason: "Retries follow §7" and consistency | O |
| N12 | After any successful action the balance, feed and request lists on the same page show the new state without a manual reload, and only after the write succeeded | S + O |

## P. Activity feed — `/`

| # | Requirement | Check |
|---|---|---|
| P1 | `activity-list` container; children newest first in the DOM; each child is `activity-item-{payment_id}` with `data-visibility` `public`/`private` | S |
| P2 | `activity-parties-{id}` contains both handles; `activity-amount-{id}` exactly the formatted amount; `activity-note-{id}` text exactly the note, present even when empty | S |
| P3 | Notes are rendered as text, never as HTML: a note of `<img src=x onerror=...>` or `<b>x</b>` appears literally and runs nothing; leading/trailing spaces and emoji preserved in `textContent` | O |
| P4 | `empty-activity` shown INSTEAD of the list when nothing is visible (CHOICE: `activity-list` is not rendered in that case) | S |
| P5 | Feed follows the API visibility rule (a private payment between two others never rendered) | S |
| P6 | CHOICE: the feed renders the newest 200 visible payments (one API page at the maximum limit) with a "load more" control when `has_more`; reason: spec sets no feed size, tests need every recent payment visible | O |
| P7 | Direction, counterparty, privacy and time are understandable without raw API data (sent/received wording or sign, lock/"Private" label, human timestamp) | O: visual review |

## Q. Requests and split screens

| # | Requirement | Check |
|---|---|---|
| Q1 | `/requests`: `incoming-list`, `outgoing-list` — both containers are ALWAYS in the DOM once the screen has loaded, also when empty (the shipped route check waits for `incoming-list` attached with no requests seeded); `request-item-{id}` with `data-status`; `request-amount-{id}` exactly formatted | S |
| Q2 | `request-pay-{id}` and `request-decline-{id}` ONLY on pending incoming; `request-cancel-{id}` ONLY on pending outgoing; none on paid/declined/cancelled | S + O for each status |
| Q3 | Pay/decline/cancel work and the lists and status refresh without reload; `request-error` shown when one is refused (insufficient funds, not pending) | S |
| Q4 | `empty-requests` shown when BOTH lists are empty (and not otherwise) | S + O |
| Q5 | Stale state: a request cancelled elsewhere while its pay button is visible → clicking pay shows `request-error` AND refreshes the list so the stale button disappears. Same for decline/cancel on a request already resolved elsewhere | O: second API client cancels, then click |
| Q6 | CHOICE: paying from the request screen uses default visibility `public` unless the user picks otherwise from a per-request selector; the pay click carries an idempotency key that is reused if the same click is retried after an uncertain outcome. Reason: visibility is the payer's choice (§4) | O |
| Q7 | `/split`: `split-amount` (decimal rule N4), `split-handles` (comma-separated, order kept, surrounding spaces trimmed), `split-note`, `split-submit` | S |
| Q8 | `split-preview` shows, BEFORE anything is posted, one `split-share-{handle}` per participant with text exactly the formatted share, computed by §9 (first participants get the extra unit); updates as inputs change; no request is sent for the preview to be correct; preview shares equal the submitted split's shares | S + O: 10.00/3 → 3.34,3.33,3.33; 0.01/3; order swap; JPY |
| Q9 | `split-error` when refused (unknown handle, duplicate, empty, bad amount) | S + O |
| Q10 | Successful split is confirmed to the user and the created requests appear under outgoing requests | S |

