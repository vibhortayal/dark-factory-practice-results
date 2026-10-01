# Stage 1 self-check (row by row)

Evidence: `tests/test_api.py` + `tests/test_concurrency.py` (69 tests, all pass against the built
container: `BASE_URL=http://localhost:8080 python3 -m unittest discover -s tests`), the supplied
harness (`claimed stage: 1`), and manual `docker` runs. "Own T" = named test class in `tests/`.

| Rows | How checked | Result |
|---|---|---|
| D1 | Inspection: `app.py`, `Dockerfile`, `RUN.md`; no `.git` inside; RUN.md command run verbatim | OK |
| D2 R1 | `docker run -e PORT=8080 -p 8080:8080`; also run with no `-e PORT` mapped `8099:8080` (default 8080, Dockerfile ENV and code default) | OK |
| D3 | Stdlib only, no network use in code; harness `--mode isolated` run (see handoff) | OK |
| D4 | `--cpus 2 --memory 2g`; healthy 0.6 s after start | OK |
| D5 | Own concurrency: 50-way bursts finish < 5 s (asserted); export/import/reset take milliseconds | OK |
| D6 D7 | Inspection: state in process memory; own code only | OK |
| D8 | Own `Runtime.test_unknown_route` (stage-2+ routes 404); harness prints `claimed stage: 1` | OK |
| R2 R3 R4 R5 R6 R9 R10 | `Runtime`, `Payments.test_shape_and_money` (Content-Type, timestamp regex, id length, reset wipes tokens/data, JPY/BHD reset) | OK |
| R7 R8 | `Runtime.test_unknown_fields_and_query_ignored`, settlement entry `junk` field | OK |
| M1-M9 | `Runtime.test_reset_*`, `test_fixture_values`, `Auth.test_signup_login`, `Auth.test_long_handle_truncated` | OK |
| M10 M11 | `Runtime.test_reset_negative_balance_changes_nothing`; `Settlements` (operator from fixture) | OK |
| M12 | `Payments.test_big_balances_exact` (balance 2^53, exact) | OK |
| M13 M14 | `Requests.test_create_shape`, `test_pay_errors`, `test_pay_flow`, race tests | OK |
| M15 | `Runtime.test_unknown_route` (users, deposits, admin/balance -> 404) | OK |
| I1-I5 | `Concurrency` (drain, all-in, cycle conservation, pay/decline/cancel race, mixed load with settlements+export, fuzz of bad bodies) | OK |
| E1-E13 | `err()` helper checks status, code, JSON content type everywhere; `Payments.test_errors`, `test_amounts`, `Requests.test_list_filters_paging` (limit 0/201/1e2/4.0/+4/empty/abc, offset -1), `Idempotency.test_key_length` (255 ok, 256 -> 422) | OK |
| A1-A11 | `Auth` class; export contains no plaintext password (scrypt hashes) | OK |
| K1-K8 K10 K11 | `Idempotency.test_all_four` (4 paths), `Settlements.test_replay_and_reuse`; K5 `test_failed_key_reusable`; K6/K7 `test_user_scope_and_path_scope`; K8 `test_k8_empty_vs_explicit`, `test_number_equality` | OK |
| K9 | `Concurrency.test_same_key_once` (payments, requests, splits), `test_pay_race`, `test_settlement_same_key` | OK |
| P1-P10 | `Payments` | OK |
| P11-P17 | `Requests` | OK |
| P18-P21 | `Requests.test_list_filters_paging` | OK |
| P22-P25 | `Splits` | OK |
| P26-P29 | `Feed.test_visibility`, `Requests.test_not_visible_to_third_party` | OK |
| S1-S4 | `Splits.test_rounding_table`, `test_zero_share_payable`, `test_paid_in_full_conserves` | OK |
| X1-X11 | `ExportImport` (round trip incl. tokens, receipts, replays, settlements, operators; invalid imports leave destination unchanged; fresh second container import done by hand: replay -> 200 with original body) | OK |
| N1-N13 | `Settlements`, `Concurrency.test_failed_settlements_leave_nothing`, mixed load | OK |

Known incomplete: none. Interpretation choices (also in the handoff):
Q1-Q6 followed as given. Further choices: pay with an empty body is treated as `{}`; the idempotency
claim is scoped to (user, key, path); a settlement entry whose handle field has the wrong JSON
type is 400, while a non-array/non-object `transfers` shape is 422; email lookup is case-insensitive.

## Round 1 (Verifier BLOCK on 8409993) fixes

| Finding | Fix | Test |
|---|---|---|
| F1a huge exponents | Floats that overflow Decimal become an opaque `Huge` value: invalid as an amount (422), ignored as an unknown field | `Hardening.test_huge_exponents` |
| F1b/F1d unsupported method, bad version/request line/target | Every `do_*` method routes to the same handler (404 for unknown routes); parser errors always answered with a real status line and a 400 `malformed_request` body | `Hardening.test_odd_methods_and_targets` |
| F1c lone surrogates | Passwords are encoded with `surrogatepass`; all JSON output is ASCII-escaped | `Hardening.test_surrogate_password`, `test_body_fuzz_never_5xx` |
| F1e invalid import state | `State.load` rejects non-plain-JSON values anywhere, timestamps without offset, non-object split/settlement records; any exception while loading is 422 and destination unchanged | `Hardening.test_invalid_import_states`, `test_mutated_exports_fuzz` (every state field mutated one at a time) |
| F2 / Q7 integral fixture numbers | `fx_int` accepts `10000`, `10000.0`, `1e4` for balance, minor_units, seeded payment and request amounts | `Hardening.test_fixture_integral_forms` |
| Notes | Per-user salt now really used (hashing parallel over 4 threads; 300 distinct users reset in < 8 s asserted); idempotency key length counted in characters (UTF-8 decoded); SIGTERM exits at once | `test_many_users_reset_fast`; `docker stop` 0.2 s |
