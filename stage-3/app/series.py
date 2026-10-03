"""Recurring reservations: adopt a booking as occurrence zero of a series (spec stage 3).

Order: (router) body 400, 401 -> idempotency key, replay/reuse -> shape 422 -> anchor 404 ->
reservation_cancelled -> already_in_series -> cutoff_passed -> occurrences 1..count-1 in
index order, each with the ordinary booking precedence. Nothing is written until every
occurrence has passed.
"""
from datetime import timedelta

from . import bookings, idempotency, records, scheduling, timeutil
from .errors import ApiError, invalid, not_found
from .records import public
from .state import STORE
from .validate import is_int


def view(data, series):
    return {"series_id": series["id"], "revision": series["revision"],
            "interval_weeks": series["interval_weeks"],
            "occurrences": [{"index": o["index"], "reference": o["reference"], "exception": o["exception"],
                             "reservation": public(data.reservations[o["reference"]])}
                            for o in series["occurrences"]]}


def _shape(body):
    anchor, count, weeks = body.get("anchor_reference"), body.get("count"), body.get("interval_weeks")
    if not isinstance(anchor, str) or not anchor:
        raise invalid("anchor_reference must be a string")
    if not is_int(count) or not 2 <= count <= 12:
        raise invalid("count must be an integer 2..12")
    if not is_int(weeks) or not 1 <= weeks <= 4:
        raise invalid("interval_weeks must be an integer 1..4")
    return anchor, count, weeks


def _create(user_id):
    def produce(data, body):
        anchor_ref, count, weeks = _shape(body)
        anchor = bookings.own(data, user_id, anchor_ref)
        if anchor["status"] == "cancelled":
            raise ApiError(409, "reservation_cancelled", "the anchor reservation is cancelled")
        if anchor.get("series"):
            raise ApiError(409, "already_in_series", "the reservation already belongs to a series")
        bookings.check_cutoff(anchor)
        rest = data.restaurants[anchor["restaurant_id"]]
        first = timeutil.parse_local(anchor["starts_at_local"])
        planned = []
        for i in range(1, count):
            naive = first + timedelta(days=7 * weeks * i)
            start, end, ids, terms = bookings.plan(data, rest, anchor["table_ids"], naive, anchor["party_size"])
            if not scheduling.table_free(data, rest["id"], ids, start, end):
                raise ApiError(409, "table_unavailable", "a table is taken at that time")
            planned.append((ids, start, end, naive, terms))
        series = {"id": data.new_series_id(), "user_id": user_id, "interval_weeks": weeks,
                  "revision": 1, "occurrences": [{"index": 0, "reference": anchor["reference"], "exception": False}]}
        anchor["series"] = {"id": series["id"], "index": 0}
        for i, (ids, start, end, naive, terms) in enumerate(planned, start=1):
            rec = records.new_record(data, user_id, rest, ids, start, end, naive, anchor["party_size"], terms)
            rec["series"] = {"id": series["id"], "index": i}
            series["occurrences"].append({"index": i, "reference": rec["reference"], "exception": False})
        data.series[series["id"]] = series
        records.bump_restaurant(data, rest["id"])
        return view(data, series)
    return produce


def create(req):
    return idempotency.run(req, _create(req.user_id))


def get(req, series_id):
    data = STORE.data
    series = data.series.get(series_id)
    if series is None or series["user_id"] != req.user_id:
        raise not_found("no such series")
    return 200, view(data, series)
