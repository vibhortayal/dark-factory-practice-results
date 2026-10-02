"""POST /auth/signup, POST /auth/login and bearer-token authentication."""
import re

from ..errors import ApiError, invalid, unauthenticated
from ..passwords import hash_password, verify_password
from ..store import store
from ..validation import string_field

NON_HANDLE_CHAR = re.compile(r"[^a-z0-9_]")


def authenticate(req):
    """Resolve the bearer token to a user id, or raise 401."""
    header = req.header("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        raise unauthenticated("a bearer token is required")
    with store.locked():
        user = store.user_for_token(token)
    if user is None:
        raise unauthenticated("unknown token")
    return user["id"]


def derive_handle(email):
    local = email.split("@", 1)[0]
    return NON_HANDLE_CHAR.sub("_", local.lower())[:20]


def _valid_email(email):
    local, sep, domain = email.partition("@")
    return bool(sep and local and domain and "@" not in domain and not any(c.isspace() for c in email))


def _session(user, token):
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def _check_available(email, handle):
    if email in store.by_email:
        raise ApiError(409, "email_taken", "email is already registered")
    if handle in store.by_handle:
        raise ApiError(409, "handle_taken", "the derived handle is already taken")


def signup(req):
    body = req.json_body()
    email = string_field(body, "email")
    password = string_field(body, "password")
    display_name = string_field(body, "display_name")
    if not _valid_email(email):
        raise invalid("email must look like local@domain")
    if len(password) < 8:
        raise invalid("password must be at least 8 characters")
    if not display_name:
        raise invalid("display_name must not be empty")
    handle = derive_handle(email)
    with store.locked():
        _check_available(email, handle)
    password_hash = hash_password(password)  # slow: kept outside the lock
    with store.locked():
        _check_available(email, handle)
        user = {"id": store.new_id("u"), "email": email, "display_name": display_name,
                "handle": handle, "password_hash": password_hash, "balance": 0}
        store.add_user(user)
        return 201, _session(user, store.issue_token(user["id"]))


def login(req):
    body = req.json_body()
    email = string_field(body, "email")
    password = string_field(body, "password")
    with store.locked():
        user = store.by_email.get(email)
        stored_hash = user["password_hash"] if user else None
    if stored_hash is None or not verify_password(password, stored_hash):
        raise unauthenticated("wrong email or password")
    with store.locked():
        if store.state["users"].get(user["id"]) is not user:
            raise unauthenticated("wrong email or password")
        return 200, _session(user, store.issue_token(user["id"]))
