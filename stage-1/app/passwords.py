"""Password hashing with scrypt (stdlib). Parameters are stored with each hash."""
import hashlib
import hmac
import os

N, R, P = 2 ** 12, 8, 1  # cost tuned so 200 seeded users hash well inside 10 s on 2 vCPU
_MAXMEM = 64 * 1024 * 1024


def _derive(password, salt, n, r, p):
    return hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                          n=n, r=r, p=p, maxmem=_MAXMEM)


def hash_password(password):
    salt = os.urandom(16)
    return f"scrypt${N}${R}${P}${salt.hex()}${_derive(password, salt, N, R, P).hex()}"


def verify_password(password, encoded):
    try:
        algo, n, r, p, salt, expected = encoded.split("$")
        if algo != "scrypt":
            return False
        value = _derive(password, bytes.fromhex(salt), int(n), int(r), int(p))
        return hmac.compare_digest(value.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False
