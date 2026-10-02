@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier
STAGE 1 HANDOFF, part 1 of 5.
Rows: all of acceptance/stage-1.md (A01 to I10) · Revision: 02d6b04 base plus the Architect's map commit at HEAD (no stage code yet) · Files: stage-1/ (to be created), acceptance/stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-1/ does not exist yet / must become a complete service meeting every map row · Repro: n/a · Next: Implementer builds; Verifier prepares its checks from the specification and gives no verdict until a committed revision is handed over.

STAGE 1 HANDOFF. This handoff has 5 numbered parts; it is complete only when you have the part marked FINAL. Parts 1 to 4 carry the task and the complete specification verbatim; the remaining parts carry the acceptance map verbatim.

== The human's task, verbatim ==
"You are the lead seat for our factory. Build stage 1 only, coordinating the other seats.

Workspace root: /home/ubuntu/nightshift-claude-check-s1f
Kickoff checkout (read-only reference): /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs
Track: pocketful
Result repository: /home/ubuntu/nightshift-claude-check-s1f/band-work/result

Read the full spec at /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs/pocketful/spec/stage-1.md and deliver it in /home/ubuntu/nightshift-claude-check-s1f/band-work/result/stage-1/ as a complete, buildable service with its own Dockerfile and RUN.md. Do not implement later stages.

Checks, run from the kickoff checkout: .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>. Run the final check with --mode isolated. Every run needs a new --out directory.

This is a dark-factory run: this message is the only input you will get. Finish with one final report."

== Paths ==
- Result repository (shared, one git repo, branch main): /home/ubuntu/nightshift-claude-check-s1f/band-work/result
- Target folder: /home/ubuntu/nightshift-claude-check-s1f/band-work/result/stage-1/ (complete service, Dockerfile, RUN.md, your tests; no nested .git; nothing outside this folder except that the Architect owns STATUS.md, acceptance/ and handoffs/)
- Kickoff checkout, read-only: /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs (spec: pocketful/spec/stage-1.md; supplied sample tests: pocketful/test/stage_1/, pocketful/test/conftest.py, pocketful/test/fixtures.py)
- Acceptance map file: /home/ubuntu/nightshift-claude-check-s1f/band-work/result/acceptance/stage-1.md (same text as pasted below)
- Check output directories: /home/ubuntu/nightshift-claude-check-s1f/band-work/checks/<new-name> (must not exist before the run)

== Commands ==
Supplied checks, run from /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs :
  .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>
Final check of a revision adds: --mode isolated (internal network, no outbound access; this is the graded mode). Suggested names: Implementer s1-impl-01, s1-impl-02, ...; Verifier s1-ver-01, ...
Manual run under the stated limits:
  docker build -t pocketful-s1 /home/ubuntu/nightshift-claude-check-s1f/band-work/result/stage-1
  docker run -d --rm --name pocketful-s1 --cpus 2 --memory 2g -e PORT=8080 -p 18080:8080 pocketful-s1
  docker stop pocketful-s1
The harness builds from the repository working tree, so commit before the run you report and report the full commit hash.

== Rules for this unit ==
- Implement the whole specification and every acceptance-map row, not only what the supplied checks ask; the supplied checks are a sample of the graded suite.
- Stage 1 only: HTTP API only, no UI and nothing from later stages. Do not read later-stage specs to build ahead.
- Language, framework and storage are the Implementer's choice. Architect's recommendation (not a requirement): a single process holding all state in memory, every state transition (money movement, request status change, idempotency claim, reset, import, export snapshot) serialised under one lock or one event loop so that invariants B01 to B03, E08 and H01 hold by construction; password hashing done outside that critical section so it cannot stall other requests; ids generated so they cannot collide with fixture or imported ids.
- Where the specification is silent, follow the "Choices" at the end of the acceptance map; if you find specification text that contradicts a choice, tell the Architect with the quote instead of silently diverging.
- Implementer: commit as "Nightshift Implementer" <nightshift-implementer@nightshift.invalid>, then hand the exact full revision to the Verifier with your row-by-row self-check, and report to the Architect. Verifier: verdict (PASS, BLOCK or INCONCLUSIVE) for the exact full revision at HEAD, to the Implementer and the Architect. A unit gets at most five BLOCK rounds.

== Specification: pocketful/spec/stage-1.md, verbatim, starts here and continues in the next parts ==

# Pocketful — Stage 1: payments and settlements

This stage defines the initial service and its API.

Build from the supplied requirements. Source code, API documentation and schemas from
existing products in this domain must not be used.

## 1. Scope

Users can send money by handle, request money and split bills. Payments appear in an
activity feed with public or private visibility. Authorized operators can submit groups
of transfers as settlements. Only the HTTP API is required.

The following apply to all operations, including concurrent requests and retries:

1. The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`.
2. No wallet balance may be negative, including transiently.
3. A payment request may move money at most once.

All amounts are exact integer counts of minor units. Deposits, top-ups, withdrawals,
cards and bank integrations are out of scope. Money moves only between existing wallets.

## 2. Delivery and deployment

Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and
starts the service without manual setup. Language, framework and storage are unrestricted.
A `docker-compose.yml` is optional.

The submission is a containerized HTTP service, not a Python package. Python is not
required in the implementation. TypeScript/JavaScript, Go, Rust, Java, Python and any
other language are equally valid. The harness builds the submitted `Dockerfile`, starts
the resulting image and tests only its HTTP behavior; it does not import or execute the
submission's source files on the judge host.

The image must run on its own with `-e PORT=<port>` and a port mapping. Runtime networking
has no outbound access. All runtime dependencies, initialization and seed data must work
within that single container. Compose configuration is not used to start the service.

### Resource limits

The service must operate within these limits:

| Limit | Value |
|---|---|
| CPU | 2 vCPU |
| Memory | 2 GiB |
| Start to first healthy response | 60 s |
| Concurrent requests | up to 50 in flight |
| Per-request timeout | 5 s (10 s for `POST /_test/reset`) |
| Outbound network | available during `docker build`, **none at run time** |
| Disk | ephemeral; state need not survive a container restart |

Runtime assets and dependencies must be included in the image. This includes fonts,
scripts and stylesheets; external services are unavailable at runtime.

## 3. Runtime contract

### 3.1 Listening

Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`.

### 3.2 Health

```http
GET /health  ->  200  {"status": "ok"}
```

Return 200 once the service and its data store can serve requests, within 60 seconds
of container start. Non-200 responses are permitted before the service is ready.

### 3.3 Reset and seed

```http
POST /_test/reset
Content-Type: application/json

{ ...fixture... }

->  204 No Content
```

Replace all service state with the fixture in the request body (§4). When reset returns
204, subsequent requests must see only that fixture. Repeated resets are supported.
This test endpoint must be enabled in the delivered image and requires no authentication.

### 3.4 Conventions

- Requests and responses are `application/json; charset=utf-8`.
- Timestamps in responses are RFC 3339 with an explicit offset, e.g. `2026-09-24T19:00:00+02:00`.
- Unknown fields in a request body are ignored, never an error.
- Unknown query parameters are ignored.
- IDs are opaque strings of at most 64 characters. Their format is yours.

## 4. Model

The service has **one currency**, declared in the fixture. Every amount in the API is an integer
count of its minor units: `1000` in a `minor_units: 2` service is €10.00, and `1000` in a
`minor_units: 0` service is ¥1000.

API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3` all represent the
same valid minor-unit amount. Booleans and strings are not numbers here.

### Users and handles

Every user has a **handle**: unique across the service, matching `^[a-z0-9_]{1,20}$`, and never
changing once set. Users identify recipients by handle. Directory and user-search
endpoints are out of scope.

Seeded users take their handle from the fixture. A user created through `POST /auth/signup`
(§6 — there is no `handle` field in the signup body) has one **derived** from their email: take the
local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20
characters. If that handle is already taken the signup fails; see the signup table in §6.

New users start with a balance of `0`. They can receive money and be asked for money immediately.

### Payments and requests

A **payment** moves money from one wallet to another, immediately and atomically. It is either sent
directly or created by paying a request.

A **request** asks someone for money. The `requester` will receive; the `payer` is being asked. A
request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`. Only the payer may
pay or decline it; only the requester may cancel it.

**A request may exceed the payer's balance.** That is a legal state, not an error at creation time:
the request stays `pending` until it is paid, declined or cancelled, and an attempt to pay it while
short is `409 insufficient_funds` and changes nothing. Money can arrive later and the same request
then becomes payable.

**Visibility belongs to the payment, not the request.** The payer chooses it when the money moves.
A request carries no visibility of its own and never appears in anyone else's feed.

### The feed contract

`GET /activity` returns payments only. A payment appears for a caller **if and only if** its
`visibility` is `public`, **or** the caller is its sender or its receiver. There is no other rule,
no follow graph and no mute list. Requests never appear in the activity feed; they are read through
`GET /requests`, which returns only requests where the caller is the requester or the payer.

A split is not a feed item. The requests it creates are visible to their own two parties, and the
payments that eventually fulfil them follow the rule above.

Visibility is **one value on the payment**, seen identically by both parties and by everyone else.
A `private` payment is hidden from third parties, not from its own receiver.

### Arithmetic range

`amount` is at most `1000000000` on any single request, and no operation produces a balance outside
±2⁵³. Monetary arithmetic must preserve exact minor-unit values without rounding error.

### Fixture format

```json
{
  "currency": "EUR",
  "minor_units": 2,
  "users": [
    { "id": "u_ada", "email": "ada@example.com", "password": "correct horse",
      "display_name": "Ada", "handle": "ada", "balance": 10000 },
    { "id": "u_bob", "email": "bob@example.com", "password": "correct horse",
      "display_name": "Bob", "handle": "bob", "balance": 2500 }
  ],
  "payments": [
    { "id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
      "amount": 500, "note": "coffee", "visibility": "public" }
  ],
  "requests": [
    { "id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
      "amount": 1200, "note": "taxi", "status": "pending" }
  ]
}
```

- Seeded users must be able to log in with the given password immediately.
- `balance` is the wallet balance **after** every seeded payment has been applied. Seeded
  numbers are consistent; you do not replay seeded payments against balances.
- A `balance` below zero in a fixture is a reset error: return `422 validation_failed` from
  `POST /_test/reset` and change nothing.
- `minor_units` is `0`, `2` or `3`. Fixtures use `EUR` (2), `JPY` (0) and `BHD` (3).

An administrative balance endpoint is out of scope.


== end of part 1 of 5; the specification continues in part 2 ==
