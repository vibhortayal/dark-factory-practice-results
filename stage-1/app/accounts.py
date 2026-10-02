"""Signup, login, password hashing and bearer-token authentication."""
import hashlib
import hmac
import os
import re
import secrets

from .errors import ApiError, invalid, malformed, unauthenticated

_N, _R, _P = 2 ** 13, 8, 1
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
MAX_EMAIL = 254
MAX_PASSWORD = 4096


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(digest) // 2)
        return hmac.compare_digest(got.hex(), digest)
    except (ValueError, TypeError):
        return False


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_email(email):
    return len(email) <= MAX_EMAIL and bool(_EMAIL_RE.match(email))


def _strings(body, names):
    """Wrong JSON type -> 400, missing -> 422 (types are checked first)."""
    for name in names:
        if name in body and not isinstance(body[name], str):
            raise malformed("%s must be a string" % name)
    for name in names:
        if name not in body:
            raise invalid("%s is required" % name)
    return [body[n] for n in names]


def _session(store, user):
    token = secrets.token_urlsafe(32)
    store.data["tokens"][token_digest(token)] = user["id"]
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def signup(store, body):
    email, password, display_name = _strings(body, ["email", "password", "display_name"])
    if not valid_email(email):
        raise invalid("email must look like local@domain")
    if len(password) < 8 or len(password) > MAX_PASSWORD:
        raise invalid("password must be 8 to %d characters" % MAX_PASSWORD)
    if not display_name or len(display_name) > 200:
        raise invalid("display_name must be 1 to 200 characters")
    stored = hash_password(password)  # slow: outside the lock
    with store.lock:
        if email.lower() in store.by_email:
            raise ApiError("email already registered", "email_taken", 409)
        uid = store.next_id("user", "u_", store.data["users"])
        user = {"id": uid, "email": email, "display_name": display_name,
                "password_hash": stored}
        store.data["users"][uid] = user
        store.by_email[email.lower()] = user
        return _session(store, user)


_DUMMY = hash_password("dummy password")


def login(store, body):
    email, password = _strings(body, ["email", "password"])
    with store.lock:
        user = store.by_email.get(email.lower())
    ok = verify_password(password, user["password_hash"] if user else _DUMMY)
    if not user or not ok:
        raise unauthenticated("wrong email or password")
    with store.lock:
        return _session(store, user)


def authenticate(store, headers):
    """Return the user id for the bearer token, or raise 401."""
    header = headers.get("Authorization", "")
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise unauthenticated()
    with store.lock:
        uid = store.data["tokens"].get(token_digest(parts[1].strip()))
    if uid is None:
        raise unauthenticated()
    return uid
