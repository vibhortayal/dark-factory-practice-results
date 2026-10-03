# Stage 1 — Verifier verdict, round 1: BLOCK

Rows: C3/E2 (F1), MV5 (F2); all other rows D1–S2 pass · Revision: 228f8d1bc356eb1285e6fe9cc0a52015fddd8690 · Files: stage-1/app/snapshot.py, stage-1/app/bookings.py (read), verification/stage-1/* (written) · Command: `bash verification/stage-1/run.sh 228f8d1bc356eb1285e6fe9cc0a52015fddd8690 <evidence-dir>` · Expected / actual: 373 own checks expected to pass / 366 pass, 7 fail (two findings) · Repro: see F1, F2 · Next: Implementer

Repository state: working tree clean; HEAD efc1232 differs from 228f8d1 only in STATUS.md. The
image was built with `--no-cache` from `git archive 228f8d1… stage-1`.

## Blocking findings

### F1 — reset answers 422 for fixture fields of the wrong JSON type (rows C3, E2; spec §5)
Spec §5: "400 `malformed_request` — Unparseable body, or a field of the wrong JSON type" and
"Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type."
§5 names only `party_size` and `starts_at_local` strings as exceptions.

Repro (any running container):
```
curl -s -X POST -H 'Content-Type: application/json' $BASE/_test/reset \
  -d '{"users":"x","restaurants":[],"reservations":[]}'
```
Actual: `422 {"error":{"code":"validation_failed","message":"users must be an array"}}`
Expected: `400 malformed_request`.
Same result for `"restaurants": {}`, `"reservations": 5`, `"slot_minutes": "30"`,
restaurant `"id": 7`, `"capacity": "2"`, user `"email": 5`, a user entry that is a string
(evidence/reset-wrong-types.txt; checks C3.4b–C3.4f). A value of the right type that is out of
range or too long (65-character id, bad reference format) is correctly 422 and must stay 422.

### F2 — moves: an invalid field value is reported before a cutoff error that precedes it (row MV5; spec §11)
Spec §11: "Non-occupancy errors use ordinary amendment codes and take precedence in input order,
with cutoff errors preceding other changes for that booking."

Repro: `P` = caller's booking whose start is in the past (cutoff passed), `H` = caller's future
booking in the same restaurant.
```
POST /reservation-moves {"moves":[{"reference":P,"party_size":0}]}
POST /reservation-moves {"moves":[{"reference":P},{"reference":H,"party_size":0}]}
```
Actual (both): `422 validation_failed` ("party_size must be an integer >= 1").
Expected (both): `409 cutoff_passed` — in the first the cutoff error precedes the other change of
the same booking; in the second the first item's error precedes the second item's.
Also `{"reference":P,"starts_at_local":"…T19:00:00"}` → 422 instead of 409
(evidence/moves-precedence.txt; checks MV5.2e, MV5.2f). Cause: `bookings._moves` runs
`_parse_changes` for every item before the per-item cancelled/cutoff loop. The same list with an
off-grid or unknown-table change is ordered correctly (MV5.2a–d pass).

## What was run

| What | Command | Result |
|---|---|---|
| Clean build | `docker build --no-cache` of the exported `stage-1/` | OK |
| RUN.md command, as written | `docker build -t tablekeeper-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-1` | `/health` 200 within ~2 s |
| Start under limits | `docker run --network <internal> --cpus 2 --memory 2g -e PORT=9000` | healthy after 0.34 s; outbound "Network is unreachable" |
| Default port | same without `PORT` | healthy on 8080 |
| Port mapping | `-e PORT=9123 -p 127.0.0.1:19123:9123` | 200 `{"status": "ok"}` |
| Harness, host | `.venv/bin/python -m harness run --track tablekeeper --repo ../band-work/result --stage 1 --mode host --out ../band-work/checks/verifier-s1-r1-host` | stage 1: 120 passed, 0 skipped |
| Harness, isolated | same with `--mode isolated --out ../band-work/checks/verifier-s1-r1-isolated` | stage 1: 120 passed, 0 skipped |
| Stage-2 suite on stage-1 | part of both harness runs | stage 2: fail (first test, UI route `/`), as required by S1; `GET /` and `GET /lookup` → 404; no `table_ids` in the code |
| Implementer's tests | `python -m unittest discover -s tests` in the export | 20 tests OK |
| Own probes | `probe.py` against the two limited containers on the internal network | 373 checks: 366 pass, 7 fail (F1: C3.4b–f, F2: MV5.2e–f), 4 observations |

`--stage 2 --mode isolated` as a separate invocation cannot run (there is no `stage-2/` folder
yet); the stage-2 result above comes from the `--stage 1` runs, which also run the stage-2 suite.

Own probes cover every row of the map: health/reset (C1–C7), fixture and seeded bookings (M1–M5),
error shape and codes (E1–E8, audited on every response), auth (A1–A8), idempotency incl. other
path, failed-key reuse, 20 concurrent identical requests, replay after cancel/PATCH (I1–I9),
restaurants and availability (R, V), create/list/get/cancel/PATCH incl. dynamic cutoff around the
current time (B, L, G, X, P), DST for Europe/Berlin and America/New_York incl. overlap on
instants (T1–T5), export/import incl. a second fresh container, rejected imports, generator
collisions (IE1–IE6), moves (MV1–MV8), load: 50 concurrent logins, signups, racing creates and
4 rounds of 50 in-flight mixed requests (no 5xx, every request < 5 s, no overlapping confirmed
bookings, container not OOM-killed, 241 MiB after load, nothing on stderr).

Architect's points: (a) unparseable body + valid token → 400 (pass); (b) no-op amend/move — no
spec statement contradicted; (c) keys scoped (user, path, key), failed keys reusable (pass);
(d) null/wrong-type string fields → 400, missing → 422 (pass); (e) bad seeded reference → 422
(harness, pass); (f) New York transitions (pass); (g) load (pass); (h) fresh-container import
(pass); (i) stage-2 suite fails (pass).

## Notes (not blocking)

1. Reset hashes every fixture user with scrypt while holding the global lock: 50 users take about
   1 s (≈20 ms per user), so a fixture of roughly 500 users would pass the 10 s reset limit and
   stall other requests meanwhile. The spec states no fixture size.
2. `Data.new_reservation_id` rebuilds the set of all reservation ids on every booking (linear in
   stored reservations). No stated limit on stored records.
3. Spec is silent on, and the service does: signup without `display_name` → 422; `x@localhost`
   accepted as an email; emails compared case-insensitively; `PATCH {}` → 200 unchanged; wrong
   method → 405 `method_not_allowed`; body over 8 MiB → 400.
4. Unparseable body without a token → 401 (auth is checked before the body is parsed); §7 gives no
   order between the two.
5. Single `PATCH` of a past-cutoff booking with an invalid `party_size` → 422, not 409. §8 states
   no order for PATCH (only §11 does for moves), so this is not a finding; if F2 is fixed by
   reordering shared code, keep PATCH behaviour deliberate.
6. Maintainability: small modules with clear jobs, one lock, validation helpers shared; the
   fixture validators in `snapshot.py` (`_obj`, `_list`, `_str`, `_id`, `_posint`) mix type and
   range errors in one 422, which is the cause of F1.

## Remaining risk not tested

- The exact cutoff boundary (`now == starts_at − cutoff`) cannot be hit with real time; tested
  about 1 h inside and outside the cutoff.
- The harness states its shipped suite is only part of the judging suite.
- Load was run on this 4-CPU host with the container limited to 2 CPUs, not on a 2-vCPU machine.
