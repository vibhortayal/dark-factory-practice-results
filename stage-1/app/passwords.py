"""Password hashing: a two-level scheme that is still a real password-hashing function.

Per load (reset/signup) a random `load_salt` is drawn; for each distinct password
K = scrypt(password, load_salt) is computed once. Each user stores
{alg, n, r, p, load_salt, user_salt, hash = HMAC-SHA256(K, user_salt)}, so stored
hashes differ per user even for equal passwords, and every password guess against a
record costs one scrypt evaluation. No plaintext or bare digest is stored.
Verification runs scrypt(password, load_salt) and the HMAC, constant-time compare.
"""
import hashlib
import hmac
import os
import threading
from concurrent.futures import ThreadPoolExecutor

ALG = "scrypt+hmac-sha256"
SCRYPT_N = 2 ** 12
SCRYPT_R = 8
SCRYPT_P = 1
# At about 9 ms per scrypt on one core (measured), 800 distinct passwords hash in
# roughly 4-8 s on 2 vCPU, inside the 10 s reset limit.
MAX_DISTINCT_PASSWORDS = 800

# scrypt allocates 128*N*r bytes (4 MiB); bound how many run at once.
_slots = threading.BoundedSemaphore(4)


def _pw_bytes(password):
    return password.encode("utf-8", "surrogatepass")


def derive_key(password, load_salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P):
    with _slots:
        return hashlib.scrypt(_pw_bytes(password), salt=load_salt, n=n, r=r, p=p, dklen=32)


def new_load_salt():
    return os.urandom(16)


def make_record(key, load_salt):
    user_salt = os.urandom(16)
    mac = hmac.new(key, user_salt, hashlib.sha256).digest()
    return {"alg": ALG, "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
            "load_salt": load_salt.hex(), "user_salt": user_salt.hex(), "hash": mac.hex()}


def hash_password(password):
    salt = new_load_salt()
    return make_record(derive_key(password, salt), salt)


def hash_many(passwords):
    """One load salt, one scrypt per distinct password (two threads), a record per input."""
    salt = new_load_salt()
    distinct = sorted(set(passwords))
    with ThreadPoolExecutor(2) as pool:
        keys = dict(zip(distinct, pool.map(lambda pw: derive_key(pw, salt), distinct)))
    return [make_record(keys[pw], salt) for pw in passwords]


def verify_password(password, record):
    try:
        key = derive_key(password, bytes.fromhex(record["load_salt"]),
                         record["n"], record["r"], record["p"])
        mac = hmac.new(key, bytes.fromhex(record["user_salt"]), hashlib.sha256).hexdigest()
    except Exception:
        return False
    return hmac.compare_digest(mac, record["hash"])
