"""Signup and login (spec §6). Emails are case-insensitive: ada@x.com == Ada@X.com.
Password hashing runs outside the global lock."""
from . import auth
from .errors import ApiError, invalid, unauthenticated
from .state import LOCK, STORE
from .validate import EMAIL_RE, require_str


def _session(data, user):
    token = auth.new_token()
    data.tokens[token] = user["id"]
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def signup(req):
    body = req.json_object()
    email = require_str(body, "email")
    password = require_str(body, "password")
    name = require_str(body, "display_name")
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise invalid("email must look like local@domain")
    if len(password) < 8:
        raise invalid("password must be at least 8 characters")
    if not name.strip() or len(name) > 200:
        raise invalid("display_name must be 1 to 200 characters")
    hashed = auth.hash_password(password)
    with LOCK:
        data = STORE.data
        if email.lower() in data.emails:
            raise ApiError(409, "email_taken", "email already registered")
        uid = data.new_user_id()
        user = {"id": uid, "email": email, "display_name": name, "password_hash": hashed}
        data.users[uid] = user
        data.emails[email.lower()] = uid
        return 201, _session(data, user)


def login(req):
    body = req.json_object()
    email = require_str(body, "email")
    password = require_str(body, "password")
    with LOCK:
        data = STORE.data
        user = data.users.get(data.emails.get(email.lower()))
        stored = user["password_hash"] if user else None
    if stored is None:
        auth.hash_password(password)  # keep timing alike for unknown emails
        raise unauthenticated("wrong email or password")
    if not auth.verify_password(password, stored):
        raise unauthenticated("wrong email or password")
    with LOCK:
        data = STORE.data
        if data.users.get(user["id"]) is not user:  # state replaced meanwhile
            raise unauthenticated("wrong email or password")
        return 200, _session(data, user)
