@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: stage-4 map GG1..JJ3, stage-3 map AA1..ZZ3, stage-2 map M1..V7 with Q11, stage-1 map A1..K10 · Revision: e57b830ffcc4e8716660c93348a830a927836079 (maps and status; accepted: stage-1/ 77409dda43334b784ca1125d2d990ba51478abf6, stage-2/ 88b9223d3e56cd9a668499f3cd5b87575d0ea114, stage-3/ aedbe2c666e7b1b97661ad869d77f002bb103eca; stage-4/ does not exist yet) · Files: acceptance/stage-4.md, stage-3.md, stage-2.md, stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-4/ to be built / not yet built · Repro: n/a · Next: Implementer builds stage-4/ and reports a committed revision; Verifier prepares its checks now and waits for that revision.

STAGE 4 HANDOFF, part 9 of 15. ACCEPTANCE MAP, stage 3, as it stands (part 1 of 2: header, vocabulary, sections AA, BB, CC, DD). It continues to apply to stage-4/, except row ZZ1 which JJ1 replaces.

# Acceptance map: stage 3

Sources: `pocketful/spec/stage-3.md` ("S3"), `stage-2.md` ("S2") and `stage-1.md` (§ numbers)
in the kickoff checkout. Target folder: `stage-3/`, created by copying the accepted `stage-2/`
(revision 88b9223d3e56cd9a668499f3cd5b87575d0ea114) and extending that code.
Every row of `acceptance/stage-1.md` (A1..K10 with A12, A13) and `acceptance/stage-2.md`
(M1..V7 with Q11) continues to apply to `stage-3/` except where a row here says it changes;
rows L1 and Z1 are replaced by ZZ1.
"Check": `H` = supplied harness run, `P` = the Verifier's own HTTP probe, `B` = browser probe,
`I` = inspection. Rows marked **[D]** are the Architect's resolution of an open choice, with the reason.

Vocabulary used below. A payment's **selected revision** in a view with knowledge instant K is its
latest revision whose `recorded_at` is at or before K (with no `known_at`: its latest revision at
the moment the read begins); a payment with no such revision is absent from the view. A payment's
**movement** in a view is one transfer of the selected revision's `amount` from sender to receiver
at the selected revision's `effective_at`. A **boundary** is any instant at which a movement or a
hold event takes place.

## AA. Carry-over and upgrade

| Row | Requirement | Check |
|---|---|---|
| AA1 | `stage-3/` is a complete, buildable folder of its own (source, `Dockerfile`, `RUN.md`), copied from `stage-2/` and extended; `stage-1/` and `stage-2/` are not modified. No `.git`, symlink or submodule inside; everything needed at run time is in the image. | I; H isolated |
| AA2 | Every stage-1 and stage-2 row still holds on `stage-3/`: suites 1 and 2 pass, the Verifier's stage-1 and stage-2 API and browser probes pass. The browser product is unchanged in behaviour and keeps working against the corrected ledger (the wallet shows current corrected values; the feed shows original payments). No new screen is required by S3. | H, P, B |
| AA3 | A stage-3 service accepts an unchanged export produced by the stage-1 service and by the stage-2 service (`format_version: 1`). Everything those stages preserved is preserved (accounts, logins, tokens, balances, payments, requests, settlements, operator grants, authorisations, captures, lifetime setting, idempotency records). In addition the ledger accounts for them historically: every imported payment has revision 1 with `effective_at = recorded_at = created_at` (settlement members: their `committed_at`); opening balances are derived so that every historical view sums to the seeded total; holds and captures take part in historical `held` and `available` by their recorded times. | H, P: export from real stage-1 and stage-2 containers with rich state |
| AA4 | **[D]** An imported authorisation that is closed but carries no close time (stage-2 states) gets `closed_at`: the `expires_at` if `expired`; the time of its last capture if it has captures; otherwise its `created_at`. Reason: S3 lets seeded closed holds skip reconstructing a lifecycle; the earliest consistent time means such a hold never inflates historical `held`. | P |
| AA5 | Stage-3 export/import (§10) also preserves every revision of every payment (amounts, effective and recorded times, reasons), `closed_at`, statement snapshot tokens (they keep paging the same frozen result after import), and the idempotency records of all eight write paths. The export keeps `track: "pocketful"`, `format_version: 1`; state layouts of stages 1, 2 and 3 are told apart inside `state`. Tampered or inconsistent states are 422 with the destination unchanged; no 5xx. | P |
| AA6 | After reset and after import the service's clock never runs behind the state: every timestamp it issues is strictly later than the reset instant and not earlier than any instant already recorded in the imported state. | P |

## BB. Instants

| Row | Requirement | Check |
|---|---|---|
| BB1 | An instant parameter or field (`as_of`, `known_at`, `from`, `to`, `effective_at`, seeded `created_at`) is valid iff it is an RFC 3339 date-time with an explicit offset: `YYYY-MM-DDTHH:MM:SS`, optional fraction of any length, then `Z` or `±HH:MM`, naming a real calendar date and time. A naive local time, a bare date, an empty value, an impossible date (`2026-02-30`), hour 24, a number, anything else -> 422 `validation_failed`. **[D]** `t` and `z` in lower case are accepted; a seconds value of 60 is rejected. | P |
| BB2 | Instants are compared exactly as instants at whatever fractional precision they were given (microseconds from a client must not be truncated or rounded into an equal or different instant); different spellings of one instant (offsets, `Z`, trailing zeros) are equal. | P: instants one microsecond either side of a payment's `created_at` |
| BB3 | A supplied instant that the service returns is returned exactly as given: `as_of` and `known_at` echoes, a correction's `effective_at`, a seeded `created_at`. Echo fields are present only when the parameter was supplied (`GET /me` without `as_of` has no `as_of` key). | H, P |
| BB4 | **[D]** In a query string an instant written with a raw `+` (which URL decoding turns into a space) is read as that `+` offset and echoed with `+`. Reason: the instant is unambiguous and the specification's own example needs `%2B` only because of this decoding. | P |
| BB5 | **[D]** "Not later than now" for `effective_at` is judged to the service's clock tick: an instant inside the current millisecond is not in the future. Reason: clients send microsecond instants taken a fraction of a millisecond before the service reads its millisecond clock. | P |

## CC. Payment timestamps, seeding, opening balances (S3 "Payment timestamps", "Effective time…")

| Row | Requirement | Check |
|---|---|---|
| CC1 | Every payment on every endpoint carries `created_at`, an RFC 3339 instant with offset naming when it moved money. `GET /activity` keeps ordering newest first by it and keeps showing the original payment (original amount) after any correction. | H, P |
| CC2 | A seeded payment may supply `created_at` (returned as given); omitted means the reset instant, which is strictly before every payment later created through the API. A seeded `created_at` in the future, or not a valid instant, makes reset 422 `validation_failed` with no state change. | P |
| CC3 | The fixture `balance` is still the balance after all seeded payments; loading them changes no balance. Opening balance of a seeded user = seeded balance minus the net effect of the original seeded payments; of a signed-up user = 0. Corrections never change an opening balance. Opening balances sum to the seeded total. | P |
| CC4 | Revision 1 of every payment has the original `amount`, `effective_at = recorded_at = created_at`, `reason: ""`. For a settlement member all three equal the shared `committed_at`. | P |

## DD. Historical `GET /me` (S3 "GET /me as of an instant", "known_at", "Historical holds")

| Row | Requirement | Check |
|---|---|---|
| DD1 | Without `as_of` and `known_at`, `GET /me` is as in stage 2 and reports current corrected values (the effect of every latest revision). | H, P |
| DD2 | `GET /me?as_of=T`: `balance` = opening balance plus every movement of the caller with effective time at or before T (a payment at exactly T counts). T at or after the latest movement gives the current balance; T before the earliest gives the opening balance; T may be in the future. The response echoes `as_of`. | H, P |
| DD3 | `known_at=K` selects revisions as in the vocabulary: revisions recorded after K are ignored, payments first recorded after K contribute nothing; then the selected revisions apply by their effective times. K may be in the future. Without `as_of`, the view instant is the instant the request began. The response echoes `known_at`. | P |
| DD4 | In every such view all four money fields describe the same view: `balance = total`, `available = total − held`, `held` = holds standing at T as known at K. A hold starts at the authorisation's `created_at`; a non-final capture reduces it at the capture's time; a final capture, a void or expiry releases the remainder at that event's time; expiry takes effect at `expires_at` (at T equal to `expires_at` the hold is released). Creation, captures and voids are known from their event time; once creation is known, the expiry deadline is known too. For T beyond now an open hold is released at its deadline. | P: views before, between and after each event, with K before and after it |
| DD5 | Seeded open holds start at the reset instant unless the fixture supplies `created_at`. Seeded closed holds (and seeded `open` ones already past `expires_at` at reset) contribute no historical hold. | P |
| DD6 | Every authorisation response carries `closed_at`: null while open; the event time when closed (final or completing capture time, void time, `expires_at` for expiry). | P |
| DD7 | In every historical view (any T, any K) the sum of all users' `total` equals the seeded total, and no user's `total` or `available` is negative at any boundary. | P: sweep T and K over all boundaries after a sequence of payments, holds and corrections |

(end of part 9 of 15)
