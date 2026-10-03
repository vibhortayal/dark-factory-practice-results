"""Unauthenticated test endpoints: reset, export, import."""
from ..fixture import build_state
from ..jsonutil import dumps, parse_json, parse_object
from ..snapshot import export_document, import_document


def reset(holder, request):
    fixture = parse_object(request.body)
    new_state = build_state(fixture)
    with holder.lock:
        holder.state = new_state
    return 204, None


def export(holder, request):
    with holder.lock:
        return 200, dumps(export_document(holder.state))


def import_(holder, request):
    new_state = import_document(parse_json(request.body))
    with holder.lock:
        holder.state = new_state
    return 204, None
