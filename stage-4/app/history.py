"""Owner-only reservation history and decision (spec stage 3). Anyone else gets 404."""
from .bookings import own
from .jsonutil import clone
from .state import STORE


def history(req, reference):
    rec = own(STORE.data, req.user_id, reference)  # req.user_id is None when not signed in
    return 200, {"reference": rec["reference"], "entries": clone(rec["history"])}


def decision(req, reference):
    rec = own(STORE.data, req.user_id, reference)
    return 200, {"reference": rec["reference"], "revision": rec["revision"],
                 "accepted_terms": clone(rec["accepted_terms"])}
