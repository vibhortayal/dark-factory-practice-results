"""Password hashing with scrypt (salted, constant-time verify)."""
import base64
import hashlib
import hmac
import os

_N, _R, _P = 2 ** 12, 8, 1


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                          n=n, r=r, p=p, dklen=32)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = _derive(password, salt, _N, _R, _P)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(),
                                       base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False
