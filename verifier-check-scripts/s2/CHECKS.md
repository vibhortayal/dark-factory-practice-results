# Verifier check list — stage 2 (Pocketful: wallet screens and payment authorisations)

Derived from `pocketful/spec/stage-2.md` (on top of `stage-1.md`) clause by clause, before any stage-2 revision
existed and without reading the Implementer's work or the supplied stage-2 tests. Acceptance-map rows in
brackets. Scripts live beside this file. `run.sh <revision> <name> start|p1|p2|p3|p4|finish`.

Legend: **strict** = the specification states it, a miss is a finding. **soft** = the specification leaves it
open (map decision E-n / D-n); a deviation is recorded in `notes.jsonl`, not failed.

Setup for every part: two containers of the `stage-2/` image and one of the accepted `stage-1/` image, each
`--cpus 2 --memory 2g`, on an `--internal` Docker network (no outbound); the browser is the Chromium of the
kickoff virtualenv (Playwright), driven from the host against the container address.

Universal (every HTTP call of the scripts and every request, response and script error of the browser pages;
asserted at the end of each part in `test_zz_universal.py`):
- U1 no status >= 500 from the API or to the browser (§5) [A6, K5]
- U2 each API request <= 5 s; reset/export/import <= 10 s [A5, K3]
- U3 every API 4xx carries the §5 error body and `application/json; charset=utf-8` [D1, A7, K5]
- U4 timestamps (`created_at`, `committed_at`, `expires_at`) RFC 3339 with offset; ids <= 64 chars; `amount`,
  `balance`, `total`, `available`, `held`, `captured_amount`, `remaining_amount` are JSON integers [A8, A10, B4]
- U5 the pages request nothing outside their own origin (§2 no outbound; all assets in the image) [K3]
- U6 no uncaught script error on any page during any flow [V1]

## Part 1 and 2 — stage 1 carried forward [K2] (`test_a…test_m`, 900 checks of the accepted stage-1 list)
The whole stage-1 list runs against the stage-2 image, adapted only where stage 2 changes the contract:
`GET /me` is compared on its stage-1 members (and must add `total`, `available`, `held`); `GET /` is a screen,
no longer a 404; the idempotency checks (F1-F9) run on seven paths (adds `POST /authorizations` and
`POST /authorizations/{id}/capture`); the import mutation sweep also covers the authorisation section.

## Part 3 — authorisation API and HTTP surface (`test_q_auth.py`, `test_u_http.py`)
### Q1/Q2 existing API changes
- Q1.1 `/me`: `balance == total`; `available == total - held`; no holds → all agree, `held` 0; signup user all 0
- Q1.2 a hold lowers the payer's `available`, raises `held`, moves nothing, reserves nothing for the receiver; void restores
- Q2.1 `insufficient_funds` on payments, request pay, settlements and new authorisations is judged on `available`;
  a settlement's net debit may use exactly `available` (soft: E-12); failed attempts change nothing
- Q2.2 `POST /payments` and request pay stay immediate: no hold, no authorisation, `authorization_id: null`; splits unchanged
- Q2.3 exactly `available` is spendable; received money is available at once
### Q3 fixture
- Q3.1 ttl defaults to 600; supplied 1, 30, 1234, 86400 used exactly; `authorizations` omitted = empty
- Q3.2 ttl 0, negative, 1.5, "600", booleans, array, object → 422 (or 400), nothing changes; `6e2`, `null`, 400 digits: soft, never 5xx
- Q3.3 seeded authorisations: only `open` and unexpired ones hold; `captured`, `voided`, `expired` and
  open-past-deadline hold nothing; listed for both parties with all members; `expires_at` kept as the same instant
  (soft: same spelling); seeded open holds can be captured and voided; none is a feed item
- Q3.4 `expires_at` spellings: `Z`, `+02:00`, fractional seconds with `-05:30`
- Q3.5 seeded unexpired open holds above the balance → 422, nothing changes; exactly the balance accepted
- Q3.6 31 invalid authorisation records (unknown or wrong-typed users, bad status, bad or impossible `expires_at`,
  bad amount, duplicate / missing / over-long id, missing members, wrong shapes) → 422/400, nothing changes
  (4 of them soft: amount 0, amount above 1e9, self authorisation, note of 201 characters); `authorizations` not an array
### Q4 expiry by the clock (ttl 2 s, no request at the deadline)
- Q4.1 first request after the deadline is a read: `/me` released, list shows `expired`, filters follow, capture → 409
  `authorization_expired`, void → 409 `authorization_not_open`; a partly captured one keeps its captures
- Q4.2 first request after the deadline is a write: payment, capture, new authorisation each see the expiry
- Q4.3 still open before the deadline; expiry also holds across export/import
### Q5-Q7 create
- Q5.1 201 with every member, defaults, `expires_at = created_at + ttl`; listed identically for both parties; third parties see nothing; never in any feed
- Q6.1 errors: insufficient available, self, unknown handle, note, visibility, missing members, wrong type, unparseable,
  key absent / empty / 256, no or bad token; nothing changes; unknown members ignored; 255-character key
- Q6.2 amount rules on 15 number spellings (exact, per stage-1 clarification C-5)
- Q6.3 holds stack up to exactly `available`; held money funds nothing; the receiver cannot spend a hold
### Q8-Q11 capture
- Q8.1 final capture (default): payment in the `/payments` shape with `authorization_id`, note and visibility copied;
  remainder released in the same step; authorisation `captured` with `captured_amount`, `payment_id`, `payment_ids`;
  feed visibility by the ordinary rule; second capture and void → 409 `authorization_not_open`
- Q8.2 amount defaults to everything; body-less capture (soft); capture succeeds when `available` is 0
- Q10.1 `final:false`: stays open, remainder held, cumulative `captured_amount`, `payment_id` latest, `payment_ids`
  in order, `remaining_amount`; exceeding the remainder → 422 `capture_exceeds_authorization`; a later final capture releases
- Q10.2 a non-final capture of the whole remainder closes; `final:true` explicit
- Q11.1 errors: unknown → 404; payer, third party, operator → 403; eight invalid amounts → 422 `validation_failed`;
  above remainder → 422 `capture_exceeds_authorization`; `final` of a wrong type → 400 (soft 422); key and token
  rules; unparseable body; nothing changes; unknown members ignored
- Q11.2 eight odd ids on capture and void → 404; seven other routes/methods under `/authorizations` → JSON 4xx
### Q12 idempotency specifics (the generic F-rows run in part 1 on all seven paths)
- Q12.1 `{}`, `{"amount":N}`, `{"final":true}` are different bodies → 409; `2e3` equals `2000`
- Q12.2 replays answer 200 after close, after expiry and after void
- Q12.3 keys are per user and per path (two authorisations, one key); failed keys are reusable
### Q13 void
- Q13.1 payer only; receiver, third party, operator → 403; unknown → 404; no token → 401; 200 `voided`, repeat 200,
  hold released; `captured` → 409; no key needed, key and body harmless
- Q13.2 void after a partial capture releases only the remainder and keeps the capture records
### Q14 listing
- Q14.1 only the caller's; `direction` × `status` filters; clock-expired matches `expired`, never `open`; 14 bad
  parameters → 422; zero-padded integers; 401 without token
- Q14.2 newest first (items 1.1 s apart), `limit` / `offset` / `has_more`, filters before paging; default 50 of 56
### P / Q15 invariants under concurrency (50 in flight, with a concurrent `/me` poller asserting
`balance == total`, `available == total - held >= 0` on every read)
- P2.1 50 authorisations of 300 from 10000: exactly 33 succeed; P2.2 payments and authorisations mixed: 33 succeed
- P3.1 50 final captures, distinct keys: one 201; P3.2 same key: one 201, 49 × 200 (also for authorisations)
- P3.3 49 non-final captures of 100 on 3000: exactly 30 succeed, never more than authorised
- Q15.1 capture against void, 6 rounds: one consistent outcome; Q15.2 captures around the deadline: none accepted after it
- P4.1 mixed load (authorise, pay, capture, void, settle, read), 4 rounds: conservation, `held` = sum of open remainders
### Q16 / M1 export, import, reset
- Q16.1 state with every authorisation status and keys on both new paths: import into the same container restores it; all keys replay
- Q16.2 import into a fresh container: snapshots equal, replays, ttl kept, failed key reusable, new ids do not collide, holds live; reset clears
- Q16.3 mutation of every member of an authorisation record (8 values): import answers 204 or 422 only, never
  negative `available`, export still works; a hold larger than the wallet is not importable
- M1.1 export of the accepted stage-1 container imports into stage 2 with 204: `/me`, `/activity`, `/requests`
  equal on their stage-1 members; `held` 0; payments carry `authorization_id: null`; tokens, login, operator,
  replays (incl. a fractional ignored field), failed key, pending request, ttl default 600; re-export imports
### U2 / K3 / K5 over HTTP
- U1.1 six routes answer `text/html; charset=utf-8` for `Accept: text/html` and a browser Accept header, without a token
- U2.1 `/requests` and `/authorizations` answer JSON (401 without token) for no Accept, `*/*`, `application/json`,
  `application/xhtml+xml`, `text/plain`; POST on them is the API whatever the Accept header says
- U2.2 API-only routes stay JSON for a browser Accept header (soft); UI-only routes without Accept (soft)
- K5.1 other methods on the six routes never 5xx
- K3.1 pages and their scripts/styles name no other origin; K5.2 every referenced asset exists with its proper type
- K5.3 22 path-traversal and odd targets: no 5xx, no file of the image leaks

## Part 4 — browser (`test_ui_*.py`; flows run at 375 px and at 1280 px unless noted)
- W2/W5/U3 login; `current-user`, `current-handle` (exact), `logout-button` on all six routes after full page loads; `auth-error` absent
- W1 signup signs in, derived handle shown, balance `0.00 EUR`, empty feed, account usable
- W3 `auth-error` on wrong password / unknown email / taken email / short password / bad email / taken handle; gone after success
- W4 logout removes `current-user` on every protected route; a second context is not signed in; login again works
- U3 the same links to `/`, `/requests`, `/split`, `/authorizations` on every route, and they work by clicking
- keyboard: login by typing, Tab and Enter (wide)
- X2 `wallet-balance` / `wallet-available` text and `data-amount` for 13 values in EUR, JPY, BHD up to 2^53-1; `wallet-held` absent
- X3 every pay and request form element; `pay-visibility` option values; no error elements initially
- X4 11 decimal spellings converted exactly (request body inspected); 17 invalid inputs show `pay-error` and send
  nothing; 5 borderline spellings never misconvert (soft); JPY and BHD decimal rules
- X5 eight refusals show `pay-error`, keep the inputs, change nothing; success clears the error
- X6 unchanged resubmission pays once (same key and body if sent at all); each changed field is a new payment;
  double click and 8 rapid clicks pay once; the button works from the keyboard
- X7 request form: refusals, exact conversion, no resend of an unchanged form, appears on `/requests`
- Y1/Y2 feed: one item per visible payment, DOM order = newest first, `data-visibility`, parties, exact amount, exact
  note (empty, Unicode, markup-like, 200 characters), odd payment id; whitespace notes (soft); no sideways scroll
- Y3 `empty-activity`; 60 payments all listed; Y4 settlement members and captures appear, open holds do not
- C1 refresh updates balance, available, held and feed and keeps the pay form
- C2 latest refresh wins: answers of an earlier refresh delivered after a later one do not overwrite it (also for the first page load)
- C3 balance spent elsewhere: `pay-error`, refreshed balance and feed, inputs kept; the unchanged form succeeds later
- C5 lost response after commit / before commit: `pay-uncertain`, no `pay-error`, inputs kept, retry with the same
  key and body, money moved once; unreadable answer (soft); changed form while uncertain is a new payment; a refusal on retry is shown as refusal
- Z1/Z2 request lists, `data-status`, exact amounts (incl. `0.00 EUR`), buttons only where allowed, odd id
- Z3 pay / decline / cancel without reload; double click pays once; refused pay shows `request-error` and stays payable
- C4 request cancelled / declined elsewhere: `request-error`, stale button gone, status updated
- Z4 `empty-requests`; 55 requests all listed
- S2 preview equals the server's shares before anything is posted, for 12 amount / order cases, JPY and BHD;
  preview follows edits; submitted body and response inspected; unchanged form splits once
- S3 nine refusals show `split-error`, nothing created
- R1 wallet numbers right after a reset with seeded holds; available is the headline number (font size / weight); paying against available
- R2 authorise form: elements, decimal rule without request, refusals, success, unchanged form holds once, numbers update
- R3/R4 list: order, `data-status` (clock-expired `expired`), exact amounts, `authorization-captured` only when captured,
  `expires_at` text, capture input pre-filled with the remainder, buttons only where allowed, odd id
- R4/R5 capture (partial, default) and void through the UI; refused capture / void show `authorization-error` and refresh the list;
  expiry reaches the UI; `empty-authorizations`; 55 authorisations all listed
- V5 no sideways scroll and no element outside the viewport on all six routes at 375, 768, 1280, 1920 px with long names, notes, amounts
- V6 every input has a visible label; focused elements show an outline or ring; text contrast meets WCAG AA
- V7/V4 loading state shows no wrong number (soft); screenshots of every route and state at both widths for V1-V4 review
- U5 user text (names, notes) is never markup on any route
- M2-M4 a page signed in against the stage-1 service: lost payment, export, import into stage 2, then without reload
  the same key and body recover the original payment and the imported balance; still signed in; the pending request is payable

## Delivery (run.sh start / finish, and by hand)
- K1 `stage-2/` complete, no nested `.git`, clean clone builds without cache; `stage-1/` unchanged since 43ecb3c; RUN.md command followed literally
- A2 PORT set / unset; A4 healthy within 60 s; restart; K3 limits and no outbound
- K4 supplied stage-3 probe on `stage-2/` is not a full pass; route review
- supplied checks: `harness run --stage 2 --mode isolated`

## Hardening (first revision of this unit only, <= 15 minutes by the clock, chosen after the list has run)

## N. Stage-2 fix round 1 (test_n_s2round1.py, part 4) — added for revision 54ab7a9: checks for the changed code only
- N1 (finding 1) every screen on stage-1 answers at both widths: no script error; home shows balance, available, feed; pay, refresh, requests, split work; `/authorizations` shows a message
- N1b `/me` with members missing or added; one failed read (`/activity` or `/me`: aborted, 500, null, array, HTML) leaves the rest of the screen and a later refresh recovers; list screens tolerate bad reads; no error banner in normal use; refresh button present while the first read is pending (T3)
- N4 `Accept` parsed as media ranges (20 headers on both shared routes); 8 odd headers never 5xx
- N5 icon served and linked; `/favicon.ico` answers without error
- N2 capture without a body: 201, same body identity as `{}`, replay, export/import; other paths unchanged
- the upgrade check (`test_ui_upgrade.py`) now asserts balance, available and feed before the import, and no script error

## O. Stage-2 fix round 2 (test_o_s2round2.py, part 4) — added for revision 4a9c357: read-ordering code only
- O1 home: first read in {page load, refresh click, own payment} withheld, state changed elsewhere, second read in {refresh click, own payment}, then the withheld answers delivered as success / 500 / abort: wallet numbers and feed stay at the newest state (18 combinations)
- O2 only the feed read late (both widths); requests list and authorisation list with withheld reads (3 deliveries each); late boot read of `/me` on the other screens
