@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: N5 (blocking); N4, N11, S6, K2 (notes) · Revision: 1e2214f72f4feacaa076fc48157c516b1ca944a8 · Files: stage-2/pocketful/handlers/authorizations.py, stage-2/pocketful/timefmt.py (read only) · Command: `python3 /home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-2/repro_b1.py 16000` with `BASE_URL` set to a running container · Expected / actual: `expires_at - created_at` is always the ttl / it was 599 s for a ttl of 600 in 1 of 16,000 creations · Repro: B1 below · Next: Implementer

# VERDICT: BLOCK — stage 2, revision 1e2214f72f4feacaa076fc48157c516b1ca944a8

One blocking finding. Everything else I ran passes: the supplied checks, my stage-1 list against the
stage-2 image, my stage-2 API list and all 22 browser checks, with no note raised by the list itself.

## Blocking finding

**B1 — `expires_at` is sometimes `created_at` plus ttl minus one second.** Map row N5.
Specification, stage 2, `POST /authorizations`: "`expires_at` is `created_at` plus `authorization_ttl_seconds`."
Observed over HTTP on this revision (fixture `authorization_ttl_seconds: 600`):
`created_at: "2026-10-02T22:21:00+00:00"`, `expires_at: "2026-10-02T22:30:59+00:00"` — a lifetime of 599 s.
Expected: `expires_at: "2026-10-02T22:31:00+00:00"`.
Frequency: 1 of 4,000 creations in the first run, 0 of 12,000 in the second, so about 1 in 16,000.
Reproduction over HTTP (probabilistic): `BASE_URL=http://127.0.0.1:<port> python3 /home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-2/repro_b1.py 16000` — it posts authorizations and prints every response whose difference is not 600.
Reproduction of the cause (deterministic, inside the image, clock replaced by two instants 6 µs apart):
```
docker run --rm <stage-2 image> python -c "
from datetime import datetime, timezone
from pocketful import timefmt
ticks = iter([datetime(2026,10,2,22,20,58,999999,tzinfo=timezone.utc), datetime(2026,10,2,22,20,59,5,tzinfo=timezone.utc)])
timefmt.now_dt = lambda: next(ticks)
e = timefmt.iso_at_or_after_now(600); c = timefmt.iso_at_or_after_now()
print('expires_at', e, 'created_at', c)"
```
prints `expires_at 2026-10-02T22:30:59+00:00 created_at 2026-10-02T22:21:00+00:00`.
Cause: `handlers/authorizations.py` `_create` builds the record with two separate clock reads, `iso_at_or_after_now(store.authorization_ttl)` for `expires_at` and `iso_at_or_after_now()` for `created_at`; each rounds up to a whole second, so when a second boundary falls between the two reads they disagree by one second. Reading the clock once and deriving both values from it removes the fault. In my list as AZ-18.

## What I ran

1. Tree clean at 1e2214f72f4feacaa076fc48157c516b1ca944a8 before and after. `git diff d02b8f6..1e2214f -- stage-1` is empty.
2. Clean build of `stage-2/` (`git archive` + `docker build --no-cache`) -> exit 0; no nested .git, symlink or submodule. Healthy after 0.47 s on the default port 8080, 0.46 s with `-e PORT=9123` and a mapping, under 0.2 s on an internal no-outbound network with `--cpus 2 --memory 2g`. After the API run: 132 MiB, no restart, no OOM, no `internal error` line in the container logs.
3. RUN.md command exactly as written, from the clean export -> `/health` 200, `/` serves HTML.
4. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/s2-ver-01` -> `stage 1: pass` (147 passed), `stage 2: pass` (35 passed), none skipped or deselected, `stage 3: fail`, `claimed stage: 2 on the shipped checks`. Stage-1 folder again with `--stage 1 --mode isolated --out ../band-work/checks/s2-ver-01-stage1` -> stage 1 pass, claimed stage 1.
5. My list, on the internal network under the limits, with the stage-1 image as the previous service:
   - API: **111 checks, 111 pass, 0 fail, 0 error, 0 notes**, 5,531 HTTP requests. That is my whole stage-1 list (94 checks, the idempotency ones now over seven paths) rerun against the stage-2 image, plus 17 stage-2 checks: `/me` fields; authorization creation with every row of its table and the boundary values (available equal to the amount, amount 1 and 1000000000, note 200/201); held funds refused for payments, request payments, settlement net debits and further holds; final and non-final captures with `captured_amount`, `remaining_amount`, `payment_id`, `payment_ids`; the capture table (remainder accepted, remainder + 1 refused); void, including after a partial capture; expiry by the clock with a 2 s lifetime and with seeded past times; seeded holds of every status; holds above, equal to and below a balance in a fixture; ttl 1, 0, -1; list filters and paging; concurrency at 48-50 in flight (10 of 49 debits fit, one of 50 final captures wins, 33 of 50 partial captures fit, capture against void on 24 holds, a mixed burst with settlements); HTML against JSON on `/requests` and `/authorizations`; export/import into a second container; import of a stage-1 export.
   - Browser (Chromium, 375 px and 1280 px): **22 checks, 22 pass, 0 notes**: every route and test id; signup and login errors; EUR, JPY and BHD formats; decimal input with no request on bad input; the unchanged pay form not paying twice and every field change paying again; refusals; a competing client; `wallet-refresh` with the first refresh's answers delivered after the second's; lost responses before and after the server committed, retried with the same key and body; the request screen including a request cancelled elsewhere; split previews over the §9 table; wallet available/held with seeded holds; the authorise form; the authorizations screen with all statuses, capture, partial capture, void and their refusals; the upgrade (page talks to the stage-1 container, response lost, export, import into stage 2, same form retried with no reload, old request paid on the request screen); no horizontal scrolling at 375, 768, 1280 and 1920 px on all six routes with a 200-character unbroken note, a 20-character handle and amounts of 1000000000; visible labels, contrast, focus change on every control reached by Tab; loading and read-failure states; no request to another origin and no script error in the whole run. In the first browser run one check (UI-02) failed through my own script (it read `current-handle` without waiting); corrected and rerun.
   - Probes after the code read: API 95 (94 pass, 1 fail = B1): 23 wrong-typed authorization values in fixtures and 22 in imports -> 4xx with state unchanged; 4301-digit amounts and 65520-character keys on the two new paths -> 422; nine attempts to read outside the UI folder through `/static/` -> 404; `available` never released before `expires_at` and always after it over 160 reads around the deadline. Browser 17 (17 pass): markup in display names and notes shown as text; signed-out visits lead to `/login`; the request, authorise and split forms do not act twice on a double click.
6. Screenshots of every screen at both widths, with the filled, empty, error, uncertain, loading and read-failure states, looked at one by one: one visual system, available funds as the headline, lists with status and direction badges, readable dates.
7. Implementer's own tests from the clean export: `python3 -m unittest discover -s tests -t .` -> Ran 82 tests, OK.
8. Stage boundary: the stage-3 supplied checks fail at `test_as_of_in_the_future_is_the_current_balance` (KeyError `as_of`); I found nothing in `stage-2/` beyond stage 2.

## Notes (do not block)

- **N1** Every Architect [reading] row I checked is met: authorise form and wallet numbers on both `/` and `/authorizations`; non-boolean `final` 400; invalid authorization entries in a fixture 422; capture pre-filled as `4.00`; one key per unchanged form on request, authorise and split; signed-out visits lead to `/login`; Enter submits.
- **N2** An authorization's `created_at` is rounded up to the next whole second, so it can lie up to a second in the future (I saw +0.75 s), while payments round down; a capture payment can therefore carry a `created_at` earlier than its authorization's. No statement in the specification speaks to it.
- **N3** `void` relies on the expiry sweep done at the start of the request and does not sweep again under its own lock, unlike capture; a deadline falling in those microseconds would let an expired hold be voided. Not reproduced.
- **N4** Funds checks scan every open hold. With 4,000 open holds on one wallet: `POST /payments` 3 ms, `GET /me` 3 ms, export 0.08 s (3.8 MB). No weakness at that figure.
- **N5** My contrast measurement skips text on a gradient, which is the wallet card; by eye its text is dark on a pale background. Elsewhere nothing measured under 4.5:1.
- **N6** The working tree holds untracked, ignored `__pycache__` folders in `stage-1/` and `stage-2/`; they are in neither the revision nor the image.
- **N7** The idle timeout is now 120 s with a `Keep-Alive: timeout=110` header and is documented in RUN.md (stage-1 note N11).
- **N8** Maintainability: `statecodec.py` was split into `fixture.py`, `statecheck.py` and `statebase.py`; holds live in `holds.py`; the UI is small ES modules under `pocketful/ui/js` with one file per screen and one place for requests (`api.js`); RUN.md's map matches. `tests/ui_check.py` is 588 lines in one file.
- **N9** scrypt cost unchanged (N=4096, r=8, p=1).

## Remaining risk I could not test

- The judged test set is larger than the shipped checks. In particular I do not know how the hidden upgrade check moves a signed-in browser from the stage-1 to the stage-2 service; I used request interception as map row L5 describes.
- Visual quality is my judgement of screenshots; only Chromium was used.
- Latency was measured with the client on the same 4-core host as the 2-vCPU container.
- B1 is rare; other faults of that frequency would not show in runs of this size.

## Where things are

- `verification/stage-2/CHECKLIST.md` and this file, in the commit named in the room message.
- Scripts, logs and screenshots outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-2/` (`run.sh`, `main.py`, `checks_a.py`, `checks_b.py`, `checks_c.py`, `ui.py`, `probes5.py`, `ui_probes.py`, `repro_b1.py`, `runs/r1-api.log`, `runs/r2-ui.log`, `runs/probes5-r1.log`, `runs/ui-probes-r1.log`, `runs/repro-b1.log`, `runs/r2ui/shots/`). Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s2-ver-01/`.
