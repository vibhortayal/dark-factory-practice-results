@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: stage-2 map M1..Z2 and stage-1 map A1..K10 · Revision: f470dbb7a1fcf1868bb3a6ddf16440ca278d54a8 (maps and status; stage-1/ accepted at 77409dda43334b784ca1125d2d990ba51478abf6; stage-2/ does not exist yet) · Files: acceptance/stage-2.md, acceptance/stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-2/ to be built / not yet built · Repro: n/a · Next: Implementer builds stage-2/ and reports a committed revision; Verifier prepares its checks now and waits for that revision.

STAGE 2 HANDOFF, part 8 of 10. ACCEPTANCE MAP, stage 2 (part 3 of 3: sections T, U, V, Z and commands).

## T. Browser: requests, split, authorisations screens

| Row | Requirement | Check |
|---|---|---|
| T1 | `/requests`: `incoming-list` and `outgoing-list` are always present; `request-item-{id}` with `data-status`; `request-amount-{id}` exactly the formatted amount; `request-pay-{id}` and `request-decline-{id}` only on a pending incoming request; `request-cancel-{id}` only on a pending outgoing request; `empty-requests` when both lists are empty. Paid, declined and cancelled requests stay listed with their status. | H, B |
| T2 | Pay, decline and cancel act through the API and then refresh the lists: the item's `data-status` changes and its buttons disappear. A refusal shows `request-error` (insufficient funds; request no longer pending) and refreshes the list, so a request cancelled elsewhere loses its stale pay button. Pay uses a key that stays the same for retries of that request. | H, B |
| T3 | `/split`: `split-amount`, `split-handles` (comma-separated, order kept, spaces around handles ignored), `split-note`, `split-submit`; `split-preview` with one `split-share-{handle}` per participant, text exactly the formatted share, computed by the §9 rule before anything is posted and identical to the submitted split's shares, for every order and remainder, in EUR, JPY and BHD. `split-error` when refused (unknown handle, duplicate, empty, invalid amount). An unchanged form resubmitted creates no second split. | H, B |
| T4 | `/authorizations`: `authorization-list` always present, direct children are the items, newest first; `authorization-item-{id}` with `data-status` (clock-expired shows `expired`); `authorization-amount-{id}` exactly the formatted authorised amount; `authorization-captured-{id}` formatted captured amount, present only when status is `captured`; `authorization-expires-{id}` text is the RFC 3339 `expires_at` exactly as the API returns it; `empty-authorizations` when the list is empty. Seeded and newly created holds both appear. | B |
| T5 | `authorization-capture-amount-{id}` (decimal input pre-filled with the remaining amount in typed form, e.g. `20.00`) and `authorization-capture-{id}` only on an incoming open authorisation; `authorization-void-{id}` only on an outgoing open one. Capture sends the typed amount; the list and wallet numbers refresh. A refused capture or void (exceeds, expired, not open, invalid amount) shows `authorization-error` and refreshes the list so stale controls disappear. | B |

## U. Browser: upgrade without reload (S2 "Existing clients after an upgrade")

| Row | Requirement | Check |
|---|---|---|
| U1 | A browser signed in before an export/import stays signed in afterwards without a reload: its next action or refresh works with the same token. | B: sign in, export, import, click refresh |
| U2 | A pending request that existed before the import is payable through the request screen afterwards. | B |
| U3 | A payment whose response was lost before the export stays retryable after the import with the same key and body: the retry returns the original payment, the page clears `pay-uncertain` and shows the imported balance; money moved once. The form content and its retry key survive the upgrade in the open page. | B |
| U4 | **[D]** The UI tolerates reading from a service state that came from stage 1: `GET /me` fields `available` and `held` missing are treated as `balance` and 0; payments without `authorization_id` render normally. Reason: robustness of open pages across the upgrade. | I, B with stubbed responses |

## V. Product quality (S2 "Product and visual direction")

| Row | Requirement | Check |
|---|---|---|
| V1 | One coherent visual system across all six screens: shared typography scale, spacing scale, colour roles, control styles and feedback styles defined once (design tokens / one stylesheet); calm, trustworthy consumer-finance character; consistent header and navigation with the current screen marked. | I: screenshots of every screen at 375 px and 1280 px, attached to the verdict |
| V2 | Available funds is the clearest monetary value on the wallet; total and held are visibly secondary. | I |
| V3 | Payments, requests, splits and authorisations are easy to scan: direction (sent / received / between others), counterparty, amount, privacy (public / private), status and time are understandable without reading raw API data. People are shown by display name where known and handle; timestamps are formatted for people (the raw RFC 3339 value stays where S2 requires it); technical identifiers are not shown unless they help. | I, B |
| V4 | Primary actions are easy to identify. Available, held, pending, loading, successful, refused and uncertain states are visually distinct (not by colour alone). Considered empty, loading and error states on every screen. | I, B |
| V5 | Usable at a 375 CSS-pixel viewport and at desktop widths with no horizontal page scrolling (`document.documentElement.scrollWidth <= clientWidth` on every screen, with long notes, long handles and large amounts). | B at 375, 768, 1280 |
| V6 | Accessibility: every input has a visible label bound to it; keyboard focus is clearly visible; all flows work by keyboard; text and controls meet WCAG AA contrast; errors are announced (`role="alert"` or a live region); buttons are real buttons, forms submit with Enter. | I, B |
| V7 | Maintainable UI code: separated modules for API access, formatting/parsing of money, each screen, and shared components; no framework fetched at run time; unit tests for money formatting, decimal parsing and the split preview. The server side keeps the stage-1 structure (one place for validation, one for the ledger). | I |

## Z. Stage boundary

| Row | Requirement | Check |
|---|---|---|
| Z1 | `stage-2/` implements stages 1 and 2 only: nothing from a later stage. The harness run for stage 2 ends `claimed stage: 2 on the shipped checks` with stages 1 and 2 `pass` and the stage-3 overshoot line `fail`. | H, I |
| Z2 | Written to the specification, not to the supplied checks: no behaviour keyed to fixture names, test ids of the checks, or check-specific values. | I |

## Commands

From `/home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs`:

```sh
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --out ../band-work/checks/<new-name>
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/<new-name>
```

Every run needs a new `--out` directory. The final check of the stage is the isolated one.
(end of the stage-2 map; end of part 8 of 10)
