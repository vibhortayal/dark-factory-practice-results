# Stage 2 acceptance map (Tablekeeper — online booking and combined tables)

Source: `dark-factory-wearedevs/tablekeeper/spec/stage-2.md` (plus all of stage-1.md, which
still applies). Folder: `stage-2/` = copy of accepted `stage-1/` (rev a8301bb), extended.
"H" = harness (`--stage 2`, which also runs suite 1), "B" = Verifier browser probe
(Playwright against the built container), "P" = HTTP probe, "R" = review.
Stage 2 must NOT implement stage-3+ features.

| Row | Requirement | Check |
|---|---|---|
| S2-0 | Every stage-1 acceptance row (acceptance/stage-1.md incl. Amendments) still holds for `stage-2/`; stage-1 suite 120 passed | H + rerun stage-1 probe set against stage-2 image |
| S2-D | `stage-2/` has own Dockerfile + RUN.md, builds clean, runs with `-e PORT`, no outbound network at run time; all UI assets (JS, CSS, fonts) served from the image, no CDN/external URLs | build + `--network none` + grep for `http(s)://` in assets |
| U1 | Routes `/`, `/signup`, `/login`, `/lookup` reachable by URL, return HTML (`text/html`); other screens reachable through the UI; API JSON conventions unchanged; unknown API routes still JSON 404 | H + P |
| U2 | Signup: `signup-email`, `signup-password`, `signup-display-name`, `signup-submit`; success signs the user in | H + B |
| U3 | Login: `login-email`, `login-password`, `login-submit`; bad login shows `auth-error` | H + B |
| U4 | `auth-error` present in DOM only when there is an error | H + B |
| U5 | `current-user` visible on every screen (all 4 routes) when signed in, text contains display name; `logout-button` signs out (current-user gone) | H + B |
| G1 | `/`: `restaurant-select` (option values = restaurant ids), `date-input` (`YYYY-MM-DD`), `party-size-input` (number), `search-button`, `availability-grid` | H + B |
| G2 | One cell `slot-{table_id}-{HH:MM}` per table per slot (every table of the restaurant, incl. those too small → `false`), `data-available` "true"/"false" exactly matching `available_table_ids` for the searched party size | H + B |
| G3 | `no-slots` shown instead of the grid when the day has no slots | H + B |
| G4 | Click available cell → booking form for that table+slot; click unavailable cell → nothing | H + B |
| G5 | Signed out + click available cell → `auth-error` or navigate to `/login` | H + B |
| F1 | Booking form: `booking-form`, `booking-summary` (contains table label(s) and local start time), `booking-party-size` (number, prefilled from search), `booking-submit`, `booking-error` (on failure) | H + B |
| F2 | Form stays on screen after success; resubmitting unchanged form → same `confirmation-reference`, no `booking-error`, no second booking (same Idempotency-Key + body, §7) | H + B |
| F3 | Changing a field → next submission is a new booking request (new key) | H + B |
| F4 | Double submit (rapid double click) leaves one reservation | H + B |
| K1 | Confirmation: `confirmation` container, `confirmation-reference` text exactly the reference, `confirmation-details` contains restaurant name, table label, local start time | H + B |
| L1 | `/lookup`: `lookup-reference-input`, `lookup-submit`; `reservation-detail` when found; `reservation-status` text exactly `confirmed`/`cancelled` | H + B |
| L2 | `reservation-cancel-button` cancels and UI updates without manual reload; button absent once cancelled; cancelling frees the slot | H + B |
| L3 | `reservation-error` when not found or when a cancel is refused (e.g. cutoff_passed) | H + B |
| R1 | Out-of-order searches: A started before B but finishing after → grid, table labels and booking form describe B; late A never restores | B: delay A's `/availability` response via route interception |
| R2 | 409 `table_unavailable` on submit → `booking-error` shown, availability refreshed (cell now `false`), form and its inputs preserved, no confirmation for that attempt | H + B |
| R3 | Lost booking response (connection fails after submit, incl. after commit) → nonempty `booking-uncertain`, no `booking-error`, no new confirmation; unchanged form retries with same key + body; successful retry removes uncertain/error elements and shows the original reference; confirmed rejection → `booking-error` | B: abort response via route interception, check server has exactly one booking |
| R4 | R1–R3 apply to combination bookings too | B |
| R5 | Browser never manufactures success from cached data; server authoritative | R + B |
| Q1 | Product quality: coherent warm hospitality look; consistent typography/spacing/colour/controls; clear hierarchy; primary actions obvious; human-readable restaurant and table labels prominent (ids not shown as main text); combos read as seating options (e.g. "Tables 1 + 2 · seats 6") | B screenshots + R |
| Q2 | Visually distinct states: available, unavailable, selected, loading, successful, refused, uncertain | B screenshots + R |
| Q3 | Usable at 375 CSS px and desktop widths with no horizontal page scroll (`scrollWidth <= innerWidth`) on all four routes incl. with a populated grid | B |
| Q4 | Inputs have visible labels; keyboard focus visible; sufficient contrast (WCAG AA for text/controls); considered empty, loading and error states; consistent navigation across the routes | B + R |
| X1 | Upgrade: stage-2 `POST /_test/import` accepts an unchanged export produced by the accepted stage-1 service (rev a8301bb) → 204; all stage-1 §10 guarantees hold (tokens, logins, references, idempotent receipts incl. move receipts) | P: export from stage-1 container → import into stage-2 container |
| X2 | Browser signed in before the export/import upgrade stays signed in after (no reload); retained reference works in lookup | B |
| X3 | Booking whose response was lost before export is retryable after import with same key+body; UI recovers the original confirmation; form + pending retry identity survive (no reload) | B |
| X4 | Stage-2 export → stage-2 import roundtrip still preserves everything incl. combined bookings | P |
| M1 | Fixture `combinable`: list of unordered pairs of table ids of that restaurant; optional (absent = none); invalid (not a pair, unknown table id, same id twice, wrong type) rejected per §5 (type → 400, value → 422) | P |
| M2 | Only listed pairs combinable; not transitive; never 3+ | P |
| M3 | Combination capacity = sum of capacities | H + P |
| M4 | Seeded reservations: `confirmed` unless `status: "cancelled"`; hold `table_id` or `table_ids` | H + P |
| M5 | `GET /restaurants/{id}` returns `combinable` in the fixture's shape (stage-1 rule: "in the fixture's shape") | P |
| AV1 | `GET /availability` slots gain `available_options` = `[{table_ids, capacity}]`: every single table and every declared pair with capacity >= party_size and no overlapping confirmed reservation on any member; singles first in fixture order, then pairs in `combinable` order; `table_ids` within pair in `combinable` order | H + P |
| AV2 | `available_table_ids` exactly as stage 1 (singles only) | H |
| BK1 | `POST /reservations` takes `table_ids`; `table_id` still accepted (= set of one); both → 422 `validation_failed`; neither → 422 | H + P |
| BK2 | Responses (create, get, list, cancel, patch, moves, replays of new requests) always carry `table_ids`; carry `table_id` only when exactly one member. Replays of stage-1-era receipts return the original stored body unchanged | H + P |
| BK3 | Pair not in `combinable` → 422 `combination_not_allowed` (order-insensitive match: `[t_2,t_1]` allowed if `[t_1,t_2]` declared) | H + P |
| BK4 | More than two tables → 422 `combination_not_allowed` | P |
| BK5 | Any member taken for overlapping interval → 409 `table_unavailable`; booking occupies both tables for full duration | H + P |
| BK6 | party_size > summed capacity → 422 `party_exceeds_capacity` | H + P |
| BK7 | Duplicate table id in set → 422 `validation_failed`; empty `table_ids` → 422; `table_ids` not an array / non-string member → 400 `malformed_request`; unknown table / other restaurant's table → 404 | P |
| BK8 | Precedence (decision, document it): shape 400/422 (both keys, dup, empty) → 404 unknown restaurant/table → `combination_not_allowed` → time checks (invalid_local_time, grid, hours) → `party_exceeds_capacity` → `table_unavailable` | R + P |
| PA1 | `PATCH` accepts `table_ids` under the same rules (single→pair, pair→single, pair→pair incl. overlapping own tables); `table_id` + `table_ids` both → 422; failed patch leaves original | P |
| PA2 | Cancel frees every table in the set | H + P |
| MV1 | `POST /reservation-moves` items accept `table_ids`; no table may belong to overlapping resulting bookings; swaps incl. pairs atomic | P |
| CC1 | Concurrency: racing pair/single bookings sharing a table → never two confirmed overlapping on any table; results serializable; invariants hold at every read; no 5xx under 50 in-flight | P load |
| UC1 | UI combination cells `slot-{t_a}+{t_b}-{HH:MM}` (ids in `combinable` order) shown when a declared pair is available for the searched party size, with `data-available` like a single cell | H + B |
| UC2 | `booking-summary` names every table in the selection; `confirmation-tables` text contains every table label; `reservation-tables` on lookup likewise; single-table cell testid, confirmation and lookup unchanged | H + B |
| UC3 | Combination booking through the UI end to end incl. lookup + cancel freeing both tables | B |
| N1 | `stage-2/` must not pass the stage-3 suite (no stage-3 features); `stage-1/` remains unchanged at a8301bb | H |
| N2 | Final check `--stage 2 --mode isolated`: suites 1 and 2 pass | H |

## Decisions (Architect)

- UI is static HTML/CSS/JS served by the same process, calling the JSON API. Token and pending
  booking identity live in the browser (token in localStorage so it survives navigation; the
  pending Idempotency-Key + body in page memory — no recovery across reload required).
- Idempotency key for the booking form is derived once per distinct form content (table set,
  slot, party size) and kept until a field changes; a lost response (fetch rejects) never
  rotates it.
- Stage-1 export `state` must import into stage 2: missing `combinable` = none; reservations
  with `table_id` only are read as a set of one. Keep `format_version: 1`.
