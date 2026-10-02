"""Start of every locked operation: read the clock once, apply expiry with it.

Everything the operation assigns (created_at, committed_at, expires_at) and every
expiry decision it makes uses `store.now`. Callers hold `store.lock`.
"""
from . import clock, holds
from .store import store


def begin():
    store.now = clock.tick()
    holds.sweep()
    return store.now
