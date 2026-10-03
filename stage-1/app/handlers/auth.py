"""POST /auth/signup and POST /auth/login (they hash passwords outside the lock)."""
import re
import secrets

from ..errors import ApiError, conflict, invalid, malformed, unauthenticated
from ..jsonutil import parse_object
from ..passwords import hash_password, verify_password
from ..store import new_id
from ..validation import require_string

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
_HANDLE_BAD = re.compile(r"[^a-z0-9_]")


def derive_handle(email: str) -> str:
    return _HANDLE_BAD.sub("_", email.split("@", 1)[0].lower())[:20]


def _session(state, user) -> dict:
    token = secrets.token_urlsafe(32)
    state.tokens[token] = user["id"]
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def signup(holder, request):
    body = parse_object(request.body)
    email = require_string(body, "email")
    password = require_string(body, "password")
    display_name = require_string(body, "display_name")
    if not _EMAIL_RE.match(email):
        raise invalid("email must look like local@domain")
    if len(password) < 8:
        raise invalid("password must be at least 8 characters")
    if not display_name:
        raise invalid("display_name must not be empty")
    handle = derive_handle(email)
    pw_hash = hash_password(password)
    with holder.lock:
        state = holder.state
        if email.lower() in state.emails:
            raise conflict("email_taken", "email already registered")
        if handle in state.handles:
            raise conflict("handle_taken", "derived handle is already taken")
        user = {"id": new_id("u_"), "email": email, "display_name": display_name,
                "handle": handle, "balance": 0, "pw_hash": pw_hash}
        state.add_user(user)
        return 201, _session(state, user)


def login(holder, request):
    body = parse_object(request.body)
    email = require_string(body, "email")
    password = require_string(body, "password")
    with holder.lock:
        state = holder.state
        uid = state.emails.get(email.lower())
        user = state.users.get(uid) if uid else None
        stored = user["pw_hash"] if user else None
    ok = verify_password(password, stored) if stored else False
    if not ok:
        raise unauthenticated("wrong email or password")
    with holder.lock:
        if holder.state is not state or user["id"] not in state.users:
            raise unauthenticated("wrong email or password")
        return 200, _session(state, user)
