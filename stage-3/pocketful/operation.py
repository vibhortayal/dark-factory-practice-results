"""Start of every locked operation: read the clock once, apply expiry with it.

`store.locked()` calls `begin` when an operation first takes the lock, so every
handler gets this for free. Everything the operation assigns (created_at,
committed_at, expires_at) and every expiry or "as of now" decision it makes uses
`store.now`.
"""
from . import clock, holds
from .store import store


def begin():
    store.now = clock.tick()
    holds.sweep()
    return store.now


store.on_begin = begin
