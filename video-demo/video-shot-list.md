# Video shot list + narration — Nightshift Dark Factory submission

## The deal (from the participant guide)

- The video must show **the factory working**: the room, a handoff between seats,
  and the result it produced. A slideshow about the factory is not the factory.
- Cover: factory design, what it cost, a bad result it caught, the stage reached.
- Target length: ~2:30. Record each shot as a **separate clip** (easier to assemble).

## Timing constraint

Record AFTER the real (graded) run. The room footage must be the run that produced
the submitted entry. Rehearsal rooms are practice only.

## Setup (your Mac)

- BAND Desktop open, signed in on your profile, factory room loaded.
- Terminal ready: repo checked out at the submitted revision.
- Screen recording: Cmd+Shift+5 → record selected window (BAND Desktop, then Terminal).
- Audio: record SILENT. Do voiceover after from the script below — cleaner than live.
- OPSEC: hide anything with secrets. No API keys, tokens, or credential values on
  screen at any point. (Our own credential-scan rule applies to the video too.)

## Shots

### Shot 1 — The room (0:00–0:20)
**Show:** BAND Desktop, factory room. Slow scroll through seat messages —
architect, implementer, verifier talking to each other, not to you.
**Narration:**
> "This is Nightshift — a three-seat software factory running in BAND Desktop.
> An architect, an implementer, and a verifier, each with a written mandate,
> building a payments service from a 1,200-line spec with no human writing code."

### Shot 2 — A handoff (0:20–0:50)
**Show:** One concrete handoff chain, paused long enough to read: the architect's
spec-handoff message → the implementer's commit → the verifier's verdict.
**Narration:**
> "Work moves seat to seat as messages, never as meetings. The architect hands
> off the spec, the implementer commits, the verifier judges. Mandates stay
> generic — how the factory works, never the track it's pointed at."

### Shot 3 — The result (0:50–1:20)
**Show:** Terminal. `docker build`, `docker run` (clean container), then
`curl localhost:8080/health`. Then the harness: shipped checks passing.
**Narration:**
> "The result: a containerized payments and settlements service. It starts from
> a clean container with no network, and passes every shipped check — 147 out of
> 147 — plus the verifier's own spec-derived tests."

### Shot 4 — The catch (1:20–1:50)
**Show:** The verifier's BLOCK verdict on the first revision (room message or
report), then the fix commits that followed.
**Narration:**
> "The factory catches bad work. The first revision was blocked — 500s on
> malformed input the shipped checks never tried. It went back, got fixed, and
> passed. We also learned the hard way: no long-lived background tasks — a
> killed test container once ate an already-written verdict."

### Shot 5 — Cost and design (1:50–2:20)
**Show:** FACTORY.md open, slow scroll. Optionally the mandates/ folder listing.
**Narration:**
> "Design, costs, and failure handling are written up in FACTORY.md — measured
> build time, model spend, and what each seat owns. Stage one is complete, and
> the same factory points at stages two through four unchanged."

### Shot 6 — Close (2:20–2:30)
**Show:** Back on the room, seats idle. Hold 5 seconds.
**Narration:**
> "Nightshift. Point the factory at a spec, get a service."

## After recording

Hand me the clips (in order, named shot-1.mov … shot-6.mov) plus a voiceover
recording read from the script above. I assemble: trim, titles, pacing, captions
for the key numbers (147/147, the BLOCK, the spend). Nothing submits without
your go-ahead.
