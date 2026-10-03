"""Password hashing (scrypt) and bearer-token helpers."""
import hashlib
import hmac
import os
import secrets

N, R, P = 2 ** 12, 8, 1


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=N, r=R, p=P, dklen=32)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                              n=int(n), r=int(r), p=int(p), dklen=len(digest) // 2)
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def new_token():
    return secrets.token_urlsafe(32)
