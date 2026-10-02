"""POST /auth/signup and POST /auth/login."""
import re
import secrets

from . import fields, passwords
from .errors import ApiError, conflict, invalid
from .jsonutil import parse_object
from .store import LOCK, current


def _credentials(req, names):
    body = parse_object(req.raw_body)
    return body, fields.handles(body, names)


def _issue_token(store, user):
    token = secrets.token_urlsafe(32)
    store.tokens[token] = user["id"]
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def derive_handle(email):
    local = email.split("@", 1)[0].lower()
    return re.sub(r"[^a-z0-9_]", "_", local)[:20]


def signup(req):
    _, (email, password, display_name) = _credentials(req, ("email", "password", "display_name"))
    local, _, domain = email.partition("@")
    if email.count("@") != 1 or not local or not domain:
        raise invalid("email must look like local@domain")
    if len(password) < 8:
        raise invalid("password must be at least 8 characters")
    handle = derive_handle(email)
    with LOCK:
        store = current()
        if email in store.by_email:
            raise conflict("email_taken", "email already registered")
        if handle in store.by_handle:
            raise conflict("handle_taken", "derived handle already taken")
    pw_hash = passwords.hash_password(password)  # slow: outside the lock
    with LOCK:
        if store is not current():
            store = current()
        if email in store.by_email:
            raise conflict("email_taken", "email already registered")
        if handle in store.by_handle:
            raise conflict("handle_taken", "derived handle already taken")
        user = {"id": store.new_id("u_", store.users), "email": email,
                "password_hash": pw_hash, "display_name": display_name, "handle": handle}
        store.add_user(user, 0)
        return 201, _issue_token(store, user)


def login(req):
    _, (email, password) = _credentials(req, ("email", "password"))
    with LOCK:
        store = current()
        uid = store.by_email.get(email)
        stored = store.users[uid]["password_hash"] if uid else None
    ok = passwords.verify_password(password, stored) if stored else False
    if not ok:
        raise ApiError(401, "unauthenticated", "wrong email or password")
    with LOCK:
        user = store.users.get(uid)
        if store is not current() or user is None or user["password_hash"] != stored:
            raise ApiError(401, "unauthenticated", "wrong email or password")
        return 200, _issue_token(store, user)
