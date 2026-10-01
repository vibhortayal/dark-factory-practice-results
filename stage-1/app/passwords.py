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
SCRYPT_R = 8
SCRYPT_P = 1
SIGNUP_N = 2 ** 14  # a signup hashes one password: full strength
# A reset fixture hashes one scrypt per DISTINCT password. The cost parameter steps down as the
# number of distinct passwords grows so that the hashing phase stays near 5 s on 2 vCPU (measured
# per hash with two threads in a --cpus 2 container: 26.9 / 12.1 / 6.3 / 3.1 / 1.6 ms for
# n = 2**14 .. 2**10). Beyond the floor's capacity the fixture is refused (422).
WORK_STEPS = ((150, 2 ** 14), (350, 2 ** 13), (700, 2 ** 12), (1400, 2 ** 11), (2800, 2 ** 10))
MAX_DISTINCT_PASSWORDS = 4000  # 4000 x 1.6 ms = 6.5 s at the floor
ALLOWED_N = frozenset(n for _, n in WORK_STEPS) | {SIGNUP_N}


def work_factor(distinct):
    for limit, n in WORK_STEPS:
        if distinct <= limit:
            return n
    return WORK_STEPS[-1][1]

# scrypt allocates 128*N*r bytes (4 MiB); bound how many run at once.
_slots = threading.BoundedSemaphore(4)


def _pw_bytes(password):
    return password.encode("utf-8", "surrogatepass")


def derive_key(password, load_salt, n=SIGNUP_N, r=SCRYPT_R, p=SCRYPT_P):
    with _slots:
        return hashlib.scrypt(_pw_bytes(password), salt=load_salt, n=n, r=r, p=p, dklen=32)


def new_load_salt():
    return os.urandom(16)


def make_record(key, load_salt, n):
    user_salt = os.urandom(16)
    mac = hmac.new(key, user_salt, hashlib.sha256).digest()
    return {"alg": ALG, "n": n, "r": SCRYPT_R, "p": SCRYPT_P,
            "load_salt": load_salt.hex(), "user_salt": user_salt.hex(), "hash": mac.hex()}


def hash_password(password):
    salt = new_load_salt()
    return make_record(derive_key(password, salt, SIGNUP_N), salt, SIGNUP_N)


def hash_many(passwords):
    """One load salt, one scrypt per distinct password (two threads), a record per input."""
    salt = new_load_salt()
    distinct = sorted(set(passwords))
    n = work_factor(len(distinct))
    with ThreadPoolExecutor(2) as pool:
        keys = dict(zip(distinct, pool.map(lambda pw: derive_key(pw, salt, n), distinct)))
    return [make_record(keys[pw], salt, n) for pw in passwords]


def verify_password(password, record):
    try:
        key = derive_key(password, bytes.fromhex(record["load_salt"]),
                         record["n"], record["r"], record["p"])
        mac = hmac.new(key, bytes.fromhex(record["user_salt"]), hashlib.sha256).hexdigest()
    except Exception:
        return False
    return hmac.compare_digest(mac, record["hash"])
