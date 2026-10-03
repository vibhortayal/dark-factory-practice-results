# Stage 2 — Verifier check list (Tablekeeper)

Derived from `tablekeeper/spec/stage-2.md` (sections named by their headings) and the stage-2
acceptance map, before the implementation or the supplied stage-2 tests were read.
Scripts: `run2.sh` (build, containers, harness), `probe1_on_stage2.py` (the whole stage-1 list,
row S2-0), `probe2.py` (API, ids P2.*), `ui_probe.py` (browser, ids UI.*).
"NOTE" = observation where the spec is silent; never blocks.

## Delivery (S2-D, N1, N2, S2-0)
- D.1 [S2-D, stage-1 §2] `stage-2/` builds clean (`--no-cache`) from a git export; RUN.md command works.
- D.2 [S2-D, §2] runs on an internal network under `--cpus 2 --memory 2g`, healthy ≤ 60 s; default port 8080.
- D.3 [S2-D, §2 "Runtime assets … must be included in the image"] browser makes no request to any other origin during all UI probes; no `http(s)://` asset URLs in shipped HTML/CSS/JS.
- D.4 [N1] `stage-1/` byte-identical to a8301bb; stage-3 suite fails on `stage-2/`; no stage-3 features.
- D.5 [N2] harness `--stage 2` host and isolated: suites 1 and 2 pass, nothing skipped.
- S0.* [S2-0] every stage-1 check (CHECKS.md of stage 1, 392 checks) against the stage-2 image; response-equality checks adapted only for the added `table_ids` field.

## API — combined tables (probe2.py)
- P2.M1 [M1, Model] reset accepts `combinable`; absent = none; wrong type (`"x"`, member not array, id not string) → 400; value errors (3 ids, 1 id, unknown table, same id twice) → 422.
- P2.M5 [M5, stage-1 §8 "in the fixture's shape"] `GET /restaurants/{id}` returns `combinable` as in the fixture.
- P2.AV1 [AV1, API/GET availability] `available_options`: singles in fixture order then pairs in `combinable` order, `table_ids` in `combinable` order, `capacity` = sum; filter `capacity >= party_size` at the boundary (party = capacity, capacity + 1); restaurant without `combinable` → singles only.
- P2.AV2 [AV2] `available_table_ids` unchanged (singles only).
- P2.AV3 [AV1] a booking on one member removes every pair containing it for overlapping slots only; a pair booking removes both singles and all pairs sharing a member.
- P2.BK1 [BK1, POST] `table_ids` pair → 201; `table_id` → 201; `table_ids` of one → 201; both keys → 422 `validation_failed`; neither → 422.
- P2.BK2 [BK2] responses of create/get/list/cancel/PATCH/moves/replay carry `table_ids`; `table_id` present exactly when one member.
- P2.BK3 [BK3, M2] undeclared pair (incl. transitive `t_1+t_3`) → 422 `combination_not_allowed`; reversed order of a declared pair → 201.
- P2.BK4 [BK4] three tables → 422 `combination_not_allowed`.
- P2.BK5 [BK5] a member taken for an overlapping interval → 409 `table_unavailable`; adjacent slot → 201; pair blocks each member for the full duration.
- P2.BK6 [BK6, M3] party = summed capacity → 201; + 1 → 422 `party_exceeds_capacity`.
- P2.BK7 [BK7] duplicate id → 422 `validation_failed`; empty array → 422; not an array / non-string member → 400 `malformed_request`; unknown table in set → 404.
- P2.PA1 [PA1, PATCH] single→pair, pair→single (`table_id` returns), pair→pair sharing a table; both keys → 422; undeclared pair → 422 `combination_not_allowed`; member taken → 409; party over capacity → 422; every failed PATCH leaves booking and availability unchanged.
- P2.PA2 [PA2] cancel frees every table of the set.
- P2.MV1 [MV1, UI section last paragraph] moves items accept `table_ids`; exchange between a pair booking and a single booking → 201; a table in two overlapping results → 409 `table_unavailable`, nothing changed; both keys in an item → 422; undeclared pair → 422 `combination_not_allowed`.
- P2.ID1 [stage-1 §7] replay of a pair booking → 200 identical; different body → 409.
- P2.M4 [M4, Model] seeded reservation with `table_ids` pair (occupies both), with `table_id`, and with `status: "cancelled"` (does not occupy, status shown).
- P2.X4 [X4, stage-1 §10] stage-2 export → import (same and second container): pair bookings, cancelled status, receipts preserved; `combinable` preserved.
- P2.X1 [X1, "Existing clients after an upgrade"] export of the accepted stage-1 image imported into stage 2 → 204; tokens, password login, restaurants, reservations (now with `table_ids` + `table_id`), statuses, timestamps preserved; replay of stage-1 create and moves receipts → 200 with the original body unchanged; used key + different body → 409; failed key still first use; availability has `available_options`; new bookings do not collide.
- P2.CC1 [CC1, "Concurrent bookings and amendments"] 50 concurrent bookings mixing pairs and singles that share tables: no table in two overlapping confirmed bookings, every response 201/409, no 5xx; 4 rounds of 50 in-flight mixed create/PATCH/cancel with pairs: same invariant, availability consistent with bookings at the end.

## Browser (ui_probe.py; desktop 1280 px unless stated)
- UI.U1 [U1] `/`, `/signup`, `/login`, `/lookup` → 200 `text/html`; unknown path still JSON 404; `/restaurants` still JSON.
- UI.U2 [U2] signup inputs + submit; success signs in (`current-user` contains display name).
- UI.U3 [U3] login inputs + submit; success → `current-user`.
- UI.U4 [U4] `auth-error` absent from the DOM on fresh `/login` and `/signup`; present and nonempty after a bad login, a duplicate signup, a short password.
- UI.U5 [U5] `current-user` visible on all four routes when signed in; `logout-button` signs out (gone on all routes).
- UI.G1 [G1] `restaurant-select` option values = restaurant ids, option text shows restaurant names; `date-input`, `party-size-input`, `search-button`, `availability-grid`.
- UI.G2 [G2] one `slot-{table}-{HH:MM}` cell for every table and slot; `data-available` equals membership in `available_table_ids` for the searched party (party 2, 4 and 6).
- UI.G3 [G3] day without slots → `no-slots` visible, no slot cells; searching an open day afterwards brings the grid back and removes `no-slots`.
- UI.G4 [G4] click unavailable cell → no booking form; click available → form for that table and slot.
- UI.G5 [G5] signed out, click available cell → `auth-error` or `/login`.
- UI.F1 [F1] `booking-summary` contains table label and local start time (distinct labels "Fenster"); `booking-party-size` prefilled.
- UI.K1 [K1] `confirmation`, `confirmation-reference` exactly the server's reference, `confirmation-details` has restaurant name, table label, start time; the reservation exists on the server.
- UI.F2 [F2] form stays; resubmit unchanged → same reference, no `booking-error`, one reservation, same Idempotency-Key and body on the wire.
- UI.F3 [F3] after changing `booking-party-size` the next submit uses a new key and the new body.
- UI.F4 [F4] double click on submit → one reservation.
- UI.R1 [R1] search A held, search B completes, then A released: grid shows B's cells only, form opened afterwards describes B.
- UI.R2 [R2] other client takes the table after the form opens: `booking-error` nonempty, no confirmation, form and party input preserved, the cell turns `false`.
- UI.R3 [R3] response lost after commit: `booking-uncertain` nonempty, no `booking-error`, no confirmation, exactly one reservation on the server; retry of the unchanged form sends the same key and body, shows the original reference, removes the uncertainty; response lost before commit: uncertain, nothing on server, retry → confirmation; retry answered by a rejection → `booking-error`, no confirmation.
- UI.UC1 [UC1] party 6: `slot-t_1+t_2-HH:MM` and `slot-t_3+t_2-HH:MM` cells (ids in `combinable` order, no reversed testid), `data-available` true exactly when the pair is in `available_options`.
- UI.UC2/UC3 [UC2, UC3, R4] combo end to end with distinct labels: summary names both tables (no raw `id+id` text), lost response → uncertain → retry recovers the reference; `confirmation-tables` names both; 409 on a combo → `booking-error` + refresh; lookup shows `reservation-tables` with both labels; cancel frees both tables.
- UI.L1 [L1] lookup of own reference → `reservation-detail`, `reservation-status` exactly `confirmed`.
- UI.L2 [L2] cancel → status `cancelled` without reload, cancel button absent, slot free on the server; lookup of a cancelled booking has no cancel button.
- UI.L3 [L3] unknown reference → `reservation-error`, no detail; refused cancel (past booking) → `reservation-error`, status stays `confirmed`.
- UI.Q3 [Q3] at 375 px and 1280 px: no horizontal page scroll on the four routes and on `/` with grid, form and confirmation; screenshots saved.
- UI.Q4 [Q4] every required input has a visible label; keyboard focus changes the control's outline/shadow; text contrast ≥ 4.5:1 (3:1 large) on required elements; same navigation links on the four routes.
- UI.Q1/Q2 [Q1, Q2] screenshots of available / unavailable / selected / loading / success / refused / uncertain states reviewed by eye (recorded as a review note with the screenshot names).
- UI.X2 [X2] browser signed in against the stage-1 service; after export → import into stage 2 (no reload) it is still signed in; the retained reference opens in lookup.
- UI.X3 [X3] booking sent to the stage-1 service, response lost; after the upgrade the unchanged form retries with the same key and body and shows the original reference.
- UI.EXT [S2-D] no request left the service origin during any UI probe; NOTE console errors.

## Round 2 additions (code changed in 0d321ce)
- UI.X3d [X3, K1] the confirmation recovered after the upgrade still shows restaurant name, table label and local start time.
- UI.X2e [X2, UC2] lookup of a stage-1-era reservation after the upgrade shows its table label.
