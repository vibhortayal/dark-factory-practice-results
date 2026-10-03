"""Shared helpers for the stage-4 verifier checks (helpers of stages 1-3 carried forward). No dependency on the repository under review."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import threading
import time
import uuid

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:18081").rstrip("/")
BASE2 = (os.environ.get("BASE2") or "").rstrip("/") or None
BASE1 = (os.environ.get("BASE1") or "").rstrip("/") or None  # a container of the accepted stage-1 image
BASEP2 = (os.environ.get("BASEP2") or "").rstrip("/") or None  # a container of the accepted stage-2 image
BASEP3 = (os.environ.get("BASEP3") or "").rstrip("/") or None  # a container of the accepted stage-3 image
VOUT = os.environ.get("VOUT", "/tmp/nsv-s4-out")
os.makedirs(VOUT, exist_ok=True)

PW = "correct horse"
CONTROL = ("/_test/reset", "/_test/export", "/_test/import")
MAX_AMOUNT = 1_000_000_000

_clients: dict[str, httpx.Client] = {}
_lock = threading.Lock()
VIOLATIONS: list[dict] = []
NOTES: list[dict] = []
CALLS = {"n": 0, "max_s": 0.0, "max_path": "", "max_ctl_s": 0.0}

TS_NUM = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")
TS_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
_NO = object()


def _client(base: str) -> httpx.Client:
    with _lock:
        c = _clients.get(base)
        if c is None:
            c = httpx.Client(base_url=base, timeout=httpx.Timeout(20.0),
                             limits=httpx.Limits(max_connections=100, max_keepalive_connections=100))
            _clients[base] = c
        return c


def _record(store: list, fname: str, entry: dict) -> None:
    with _lock:
        store.append(entry)
        with open(os.path.join(VOUT, fname), "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def violation(kind: str, **kw) -> None:
    _record(VIOLATIONS, "violations.jsonl", {"kind": kind, **kw})


def note(kind: str, **kw) -> None:
    """A deviation from the map's reading where the specification leaves the point open."""
    _record(NOTES, "notes.jsonl", {"kind": kind, **kw})


def soft(cond: bool, kind: str, **kw) -> bool:
    if not cond:
        note(kind, **kw)
    return cond


def _walk(v, fn, key=None):
    if isinstance(v, dict):
        for k, x in v.items():
            _walk(x, fn, k)
    elif isinstance(v, list):
        for x in v:
            _walk(x, fn, key)
    else:
        fn(key, v)


def _universal(method: str, path: str, r: httpx.Response, elapsed: float, limit_s: float, opaque: bool,
               kind: str = "json") -> None:
    where = {"method": method, "path": path[:200], "status": r.status_code}
    if r.status_code >= 500:
        violation("5xx", **where, body=r.text[:300])
    if elapsed > limit_s:
        violation("slow", **where, elapsed=round(elapsed, 3), limit=limit_s)
    ctype = r.headers.get("content-type", "")
    if method == "HEAD" or (kind == "any" and r.status_code < 400):
        return
    if r.status_code == 204:
        if r.content:
            violation("204-body", **where, body=r.text[:100])
        return
    if r.content:
        norm = ctype.lower().replace(" ", "")
        if norm != "application/json;charset=utf-8":
            violation("ctype", **where, content_type=ctype)
    try:
        body = r.json()
    except ValueError:
        violation("not-json", **where, body=r.text[:200])
        return
    if r.status_code >= 400:
        e = body.get("error") if isinstance(body, dict) else None
        if not (isinstance(e, dict) and isinstance(e.get("code"), str) and e["code"]
                and isinstance(e.get("message"), str)):
            violation("envelope", **where, body=r.text[:300])
        return
    if opaque:
        return

    def leaf(k, v):
        if k in ("created_at", "committed_at", "recorded_at"):
            if not isinstance(v, str) or not (TS_NUM.match(v) or TS_Z.match(v)):
                violation("timestamp", **where, key=k, value=v)
            else:
                if TS_Z.match(v):
                    note("timestamp-Z", **where, value=v)
                try:
                    dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    violation("timestamp", **where, key=k, value=v)
        elif k in ("expires_at",):
            if not isinstance(v, str) or not (TS_NUM.match(v) or TS_Z.match(v)):
                violation("timestamp", **where, key=k, value=v)
        elif k is not None and (k.endswith("_id") or k == "id"):
            if v is not None and not (isinstance(v, str) and 1 <= len(v) <= 64):
                violation("id", **where, key=k, value=str(v)[:100])
        elif k in ("amount", "balance", "total", "available", "held", "captured_amount", "remaining_amount"):
            if type(v) is not int:
                violation("non-integer-amount", **where, key=k, value=repr(v))

    _walk(body, leaf)


def call(method: str, path: str, token: str | None = None, key=None, body=_NO, raw: bytes | str | None = None,
         headers: dict | None = None, base: str | None = None, ctype: str | None = "application/json",
         kind: str = "json") -> httpx.Response:
    """One HTTP request. `path` is sent as written (query string included)."""
    h: dict[str, str] = {}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    content = None
    if raw is not None:
        content = raw.encode("utf-8") if isinstance(raw, str) else raw
    elif body is not _NO:
        content = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if content is not None and ctype:
        h["Content-Type"] = ctype
    if headers:
        h.update(headers)
    c = _client(base or BASE)
    bare = path.split("?")[0]
    limit_s = 10.0 if bare in CONTROL else 5.0
    t0 = time.perf_counter()
    r = c.request(method, path, headers=h, content=content)
    elapsed = time.perf_counter() - t0
    with _lock:
        CALLS["n"] += 1
        if bare in CONTROL:
            CALLS["max_ctl_s"] = max(CALLS["max_ctl_s"], elapsed)
        elif elapsed > CALLS["max_s"]:
            CALLS["max_s"], CALLS["max_path"] = elapsed, f"{method} {bare}"
    _universal(method, path, r, elapsed, limit_s, opaque=(bare == "/_test/export"), kind=kind)
    r.elapsed_s = elapsed  # type: ignore[attr-defined]
    return r


def GET(path, token=None, **kw):
    return call("GET", path, token, **kw)


def POST(path, token=None, body=_NO, key=None, **kw):
    return call("POST", path, token, key=key, body=body, **kw)


def k() -> str:
    return "k-" + uuid.uuid4().hex


def err(r: httpx.Response, status, code=None, msg: str = "") -> None:
    statuses = status if isinstance(status, (tuple, list, set)) else (status,)
    assert r.status_code in statuses, f"{msg} expected {status} {code}, got {r.status_code} {r.text[:300]}"
    if code is not None:
        codes = code if isinstance(code, (tuple, list, set)) else (code,)
        got = (r.json().get("error") or {}).get("code")
        assert got in codes, f"{msg} expected code {code}, got {got!r} ({r.status_code} {r.text[:300]})"


def ok(r: httpx.Response, status: int, msg: str = ""):
    assert r.status_code == status, f"{msg} expected {status}, got {r.status_code} {r.text[:400]}"
    return r.json() if r.content else None


def code_of(r: httpx.Response):
    try:
        return (r.json().get("error") or {}).get("code")
    except Exception:
        return None


# ---------------------------------------------------------------- fixtures

def user(handle: str, balance: int = 0, **kw) -> dict:
    u = {"id": f"u_{handle}", "email": f"{handle}@example.com", "password": PW,
         "display_name": handle.capitalize(), "handle": handle, "balance": balance}
    u.update(kw)
    return u


def fixture(users=None, payments=None, requests=None, ops=_NO, currency="EUR", minor=2, auths=None, ttl=_NO) -> dict:
    if users is None:
        users = [user("ada", 10000), user("bob", 2500), user("cy", 0), user("dan", 500), user("op", 1000)]
    f = {"currency": currency, "minor_units": minor, "users": users,
         "payments": payments if payments is not None else [],
         "requests": requests if requests is not None else []}
    if ops is _NO:
        ops = ["u_op"] if any(u["id"] == "u_op" for u in users) else []
    if ops is not None:
        f["settlement_operator_ids"] = ops
    if auths is not None:
        f["authorizations"] = auths
    if ttl is not _NO:
        f["authorization_ttl_seconds"] = ttl
    return f


def iso(delta_seconds: float = 0, offset: str = "+00:00") -> str:
    """An RFC 3339 instant `delta_seconds` from now."""
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta_seconds)
    return t.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S") + offset


def seeded_auth(aid, frm, to, amount, status="open", expires_in=7200, **kw) -> dict:
    a = {"id": aid, "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": amount, "note": "",
         "visibility": "public", "status": status, "expires_at": iso(expires_in)}
    a.update(kw)
    return a


ME_CORE = ("user_id", "display_name", "handle", "balance", "currency", "minor_units")


def me_core(me: dict) -> dict:
    """The stage-1 members of GET /me (stage 2 adds total, available, held)."""
    return {kk: me[kk] for kk in ME_CORE}


class World:
    """A reset service plus lazily fetched tokens."""

    def __init__(self, fx: dict | None = None, base: str | None = None, do_reset: bool = True):
        self.base = base or BASE
        self.fx = copy.deepcopy(fx) if fx is not None else fixture()
        self.tok: dict[str, str] = {}
        self.extra: dict[str, str] = {}  # handle -> token of signed-up users
        if do_reset:
            r = call("POST", "/_test/reset", body=self.fx, base=self.base)
            assert r.status_code == 204, f"reset failed: {r.status_code} {r.text[:300]}"

    def _u(self, handle: str) -> dict:
        return next(u for u in self.fx["users"] if u["handle"] == handle)

    def t(self, handle: str) -> str:
        if handle in self.extra:
            return self.extra[handle]
        if handle not in self.tok:
            u = self._u(handle)
            r = call("POST", "/auth/login", body={"email": u["email"], "password": u["password"]}, base=self.base)
            assert r.status_code == 200, f"login {handle}: {r.status_code} {r.text[:200]}"
            self.tok[handle] = r.json()["token"]
        return self.tok[handle]

    def login_all(self):
        for u in self.fx["users"]:
            self.t(u["handle"])
        return self

    def signup(self, email: str, display_name: str = "New", password: str = "longenough1") -> dict:
        r = call("POST", "/auth/signup", body={"email": email, "password": password, "display_name": display_name},
                 base=self.base)
        assert r.status_code == 201, f"signup {email}: {r.status_code} {r.text[:200]}"
        j = r.json()
        me = call("GET", "/me", j["token"], base=self.base).json()
        self.extra[me["handle"]] = j["token"]
        return {**j, "handle": me["handle"]}

    def handles(self) -> list[str]:
        return [u["handle"] for u in self.fx["users"]] + list(self.extra)

    def me(self, handle: str) -> dict:
        r = call("GET", "/me", self.t(handle), base=self.base)
        assert r.status_code == 200, r.text[:200]
        return r.json()

    def bal(self, handle: str) -> int:
        return self.me(handle)["balance"]

    def bals(self) -> dict[str, int]:
        return {h: self.bal(h) for h in self.handles()}

    def seeded_total(self) -> int:
        return sum(u["balance"] for u in self.fx["users"])

    def assert_conserved(self) -> dict[str, int]:
        b = self.bals()
        assert all(type(v) is int and v >= 0 for v in b.values()), f"negative or non-integer balance: {b}"
        assert sum(b.values()) == self.seeded_total(), f"sum {sum(b.values())} != seeded {self.seeded_total()}: {b}"
        return b

    def activity(self, handle: str, q: str = "limit=200") -> list[dict]:
        r = call("GET", f"/activity?{q}", self.t(handle), base=self.base)
        assert r.status_code == 200, r.text[:200]
        return r.json()["payments"]

    def requests(self, handle: str, q: str = "limit=200") -> list[dict]:
        r = call("GET", f"/requests?{q}", self.t(handle), base=self.base)
        assert r.status_code == 200, r.text[:200]
        return r.json()["requests"]

    def pay(self, frm: str, to: str, amount: int, key: str | None = None, **extra):
        return call("POST", "/payments", self.t(frm), key=key or k(),
                    body={"to_handle": to, "amount": amount, **extra}, base=self.base)

    def request(self, requester: str, payer: str, amount: int, key: str | None = None, **extra):
        return call("POST", "/requests", self.t(requester), key=key or k(),
                    body={"payer_handle": payer, "amount": amount, **extra}, base=self.base)

    def new_request(self, requester: str, payer: str, amount: int, **extra) -> dict:
        r = self.request(requester, payer, amount, **extra)
        assert r.status_code == 201, r.text[:300]
        return r.json()

    def pay_request(self, payer: str, rid: str, key: str | None = None, body=None):
        return call("POST", f"/requests/{rid}/pay", self.t(payer), key=key or k(),
                    body={} if body is None else body, base=self.base)

    def wallet(self, handle: str) -> dict:
        """GET /me with the stage-2 consistency rules asserted."""
        m = self.me(handle)
        for kk in ("balance", "total", "available", "held"):
            assert type(m.get(kk)) is int, f"/me.{kk} missing or not an integer: {m}"
        assert m["balance"] == m["total"], f"balance != total: {m}"
        assert m["available"] == m["total"] - m["held"], f"available != total - held: {m}"
        assert m["available"] >= 0 and m["held"] >= 0, f"negative available or held: {m}"
        return m

    def wallets(self) -> dict[str, tuple[int, int, int]]:
        return {h: (lambda m: (m["total"], m["available"], m["held"]))(self.wallet(h)) for h in self.handles()}

    def authorize(self, frm: str, to: str, amount, key: str | None = None, **extra):
        return call("POST", "/authorizations", self.t(frm), key=key or k(),
                    body={"to_handle": to, "amount": amount, **extra}, base=self.base)

    def new_auth(self, frm: str, to: str, amount: int, **extra) -> dict:
        r = self.authorize(frm, to, amount, **extra)
        assert r.status_code == 201, r.text[:300]
        return r.json()

    def capture(self, who: str, aid: str, key: str | None = None, body=None):
        return call("POST", f"/authorizations/{aid}/capture", self.t(who), key=key or k(),
                    body={} if body is None else body, base=self.base)

    def void(self, who: str, aid: str):
        return call("POST", f"/authorizations/{aid}/void", self.t(who), base=self.base)

    def auths(self, handle: str, q: str = "limit=200") -> list[dict]:
        r = call("GET", f"/authorizations?{q}", self.t(handle), base=self.base)
        assert r.status_code == 200, r.text[:200]
        return r.json()["authorizations"]

    def auth(self, handle: str, aid: str) -> dict:
        return next(a for a in self.auths(handle) if a["authorization_id"] == aid)

    def snapshot(self, tokens: dict[str, str] | None = None, base: str | None = None) -> dict:
        """Everything a caller can read, per user, as JSON."""
        tokens = tokens or {h: self.t(h) for h in self.handles()}
        base = base or self.base
        out = {}
        for h, tk in sorted(tokens.items()):
            me = call("GET", "/me", tk, base=base)
            act = call("GET", "/activity?limit=200", tk, base=base)
            rq = call("GET", "/requests?limit=200", tk, base=base)
            au = call("GET", "/authorizations?limit=200", tk, base=base)
            out[h] = {"me": (me.status_code, me.json()), "activity": (act.status_code, act.json()),
                      "requests": (rq.status_code, rq.json()), "authorizations": (au.status_code, au.json())}
        return out


def burst(fns: list) -> list:
    """Run callables at the same instant, at most 50 in flight. Returns results in order."""
    n = len(fns)
    assert 1 <= n <= 50, "the specification limits concurrency to 50 in flight"
    bar = threading.Barrier(n)
    out: list = [None] * n

    def run(i):
        try:
            bar.wait(timeout=30)
            out[i] = fns[i]()
        except Exception as exc:  # noqa: BLE001
            out[i] = exc

    th = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in th:
        t.start()
    for t in th:
        t.join(timeout=120)
    assert not any(t.is_alive() for t in th), "a concurrent request never returned (hang)"
    for r in out:
        if isinstance(r, Exception):
            raise r
    return out


def statuses(rs) -> dict[int, int]:
    d: dict[int, int] = {}
    for r in rs:
        d[r.status_code] = d.get(r.status_code, 0) + 1
    return d


PAY_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency",
            "note", "visibility", "request_id", "settlement_id", "authorization_id", "created_at", "refund_of"}
AUTH_KEYS = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "captured_amount",
             "remaining_amount", "currency", "note", "visibility", "status", "expires_at", "payment_id",
             "payment_ids", "created_at", "closed_at"}
AUTH_STATUSES = ("open", "captured", "voided", "expired")


def check_auth(a: dict, **expect) -> dict:
    assert isinstance(a, dict), a
    missing = AUTH_KEYS - set(a)
    assert not missing, f"authorization lacks {missing}: {a}"
    soft(set(a) == AUTH_KEYS, "authorization-extra-keys", keys=sorted(set(a) - AUTH_KEYS))
    assert isinstance(a["authorization_id"], str) and a["authorization_id"]
    for kk in ("amount", "captured_amount", "remaining_amount"):
        assert type(a[kk]) is int and a[kk] >= 0, a
    assert a["status"] in AUTH_STATUSES, a
    assert isinstance(a["payment_ids"], list), a
    assert a["captured_amount"] + a["remaining_amount"] <= a["amount"], a
    if a["status"] != "open":
        assert a["remaining_amount"] == 0, f"closed authorisation still holds: {a}"
    assert a["payment_id"] == (a["payment_ids"][-1] if a["payment_ids"] else None) or a["status"] == "captured", a
    ts(a["expires_at"])
    ts(a["created_at"])
    for kk, v in expect.items():
        assert a[kk] == v, f"authorization.{kk}: expected {v!r}, got {a[kk]!r} in {a}"
    return a
REQ_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount", "currency",
            "note", "status", "payment_id", "created_at"}


def check_payment(p: dict, **expect) -> dict:
    assert isinstance(p, dict), p
    missing = PAY_KEYS - set(p)
    assert not missing, f"payment lacks {missing}: {p}"
    soft(set(p) == PAY_KEYS, "payment-extra-keys", keys=sorted(set(p) - PAY_KEYS))
    assert isinstance(p["payment_id"], str) and p["payment_id"]
    assert type(p["amount"]) is int, p
    assert p["visibility"] in ("public", "private"), p
    assert isinstance(p["note"], str), p
    for kk, v in expect.items():
        assert p[kk] == v, f"payment.{kk}: expected {v!r}, got {p[kk]!r} in {p}"
    return p


def check_request(q: dict, **expect) -> dict:
    assert isinstance(q, dict), q
    missing = REQ_KEYS - set(q)
    assert not missing, f"request lacks {missing}: {q}"
    soft(set(q) == REQ_KEYS, "request-extra-keys", keys=sorted(set(q) - REQ_KEYS))
    assert isinstance(q["request_id"], str) and q["request_id"]
    assert type(q["amount"]) is int, q
    assert q["status"] in ("pending", "paid", "declined", "cancelled"), q
    for kk, v in expect.items():
        assert q[kk] == v, f"request.{kk}: expected {v!r}, got {q[kk]!r} in {q}"
    return q


def ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def assert_newest_first(items: list[dict]) -> None:
    """Non-increasing by created_at, compared at whole seconds (order inside one second is unspecified)."""
    secs = [int(ts(i["created_at"]).timestamp()) for i in items]
    assert secs == sorted(secs, reverse=True), f"not newest first: {[i['created_at'] for i in items]}"


def shares(amount: int, n: int) -> list[int]:
    q, r = divmod(amount, n)
    return [q + 1 if i < r else q for i in range(n)]



# ====================================================================== stage 3: instants and the reference model
from fractions import Fraction  # noqa: E402
from urllib.parse import quote  # noqa: E402

INST = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[Tt](\d\d):(\d\d):(\d\d)(?:\.(\d+))?(?:([Zz])|([+-])(\d\d):(\d\d))$")
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
US = Fraction(1, 10 ** 6)
INF = Fraction(10 ** 15)


def inst(s: str) -> Fraction:
    """An RFC 3339 instant as exact seconds since the epoch (fractions of any length kept exactly)."""
    m = INST.match(s)
    assert m, f"not an RFC 3339 instant with offset: {s!r}"
    y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
    base = dt.datetime(y, mo, d, h, mi, sec, tzinfo=dt.timezone.utc) - _EPOCH
    out = Fraction(base.days * 86400 + base.seconds)
    if m.group(7):
        out += Fraction(int(m.group(7)), 10 ** len(m.group(7)))
    if m.group(9):
        off = int(m.group(10)) * 3600 + int(m.group(11)) * 60
        out -= off if m.group(9) == "+" else -off
    return out


def fmt(x, offset_minutes: int = 0, z: bool = False) -> str:
    """Write exact seconds since the epoch as an RFC 3339 instant (as many fraction digits as needed)."""
    x = Fraction(x)
    local = x + offset_minutes * 60
    whole = local.numerator // local.denominator
    frac = local - whole
    t = _EPOCH + dt.timedelta(seconds=whole)
    out = f"{t.year:04d}-" + t.strftime("%m-%dT%H:%M:%S")
    if frac:
        digits = ""
        f = frac
        while f:
            f *= 10
            dgt = f.numerator // f.denominator
            digits += str(dgt)
            f -= dgt
            assert len(digits) <= 2000, "fraction is not a finite decimal"
        out += "." + digits
    if z and offset_minutes == 0:
        return out + "Z"
    sign = "+" if offset_minutes >= 0 else "-"
    return out + f"{sign}{abs(offset_minutes) // 60:02d}:{abs(offset_minutes) % 60:02d}"


def now_f() -> Fraction:
    return Fraction(time.time_ns() // 1000, 10 ** 6)


def q(**params) -> str:
    """A query string with every value percent-encoded ('+' and ':' included)."""
    return "&".join(f"{kk}={quote(str(v), safe='')}" for kk, v in params.items() if v is not None)


def pid_path(pid: str) -> str:
    if pid and set(pid) <= {"."}:
        return pid.replace(".", "%2E")       # a client would otherwise collapse the dot segment before sending
    return quote(pid, safe="")


REV_KEYS = {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"}
ENTRY_KEYS = {"payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"}
STMT_KEYS = {"opening_balance", "entries", "closing_balance", "has_more", "snapshot"}


def check_revision(r: dict, **expect) -> dict:
    assert isinstance(r, dict), r
    missing = REV_KEYS - set(r)
    assert not missing, f"revision lacks {missing}: {r}"
    soft(set(r) - REV_KEYS <= {"correction_batch_id"}, "revision-extra-keys", keys=sorted(set(r) - REV_KEYS))
    assert type(r["revision"]) is int and r["revision"] >= 1, r
    assert type(r["amount"]) is int and 0 <= r["amount"] <= MAX_AMOUNT, r
    assert isinstance(r["reason"], str), r
    inst(r["effective_at"])
    inst(r["recorded_at"])
    for kk, v in expect.items():
        assert r[kk] == v, f"revision.{kk}: expected {v!r}, got {r[kk]!r} in {r}"
    return r


def correct(w: "World", who: str, pid: str, expected: int, amount, effective_at, reason="fix", key=None, **extra):
    body = {"expected_revision": expected, "amount": amount, "effective_at": effective_at, "reason": reason, **extra}
    return call("POST", f"/payments/{pid_path(pid)}/corrections", w.t(who), key=key or k(), body=body, base=w.base)


def revisions(w: "World", who: str, pid: str):
    return call("GET", f"/payments/{pid_path(pid)}/revisions", w.t(who), base=w.base)


def me_at(w: "World", handle: str, as_of=None, known_at=None, extra: str = ""):
    qs = q(as_of=as_of, known_at=known_at)
    return call("GET", "/me" + ("?" + qs if qs else "") + extra, w.t(handle), base=w.base)


def statement(w: "World", handle: str, **params):
    qs = q(**params)
    return call("GET", "/statement" + ("?" + qs if qs else ""), w.t(handle), base=w.base)


def check_statement_shape(body: dict) -> dict:
    assert isinstance(body, dict), body
    missing = STMT_KEYS - set(body)
    assert not missing, f"statement lacks {missing}: {str(body)[:300]}"
    soft(set(body) == STMT_KEYS, "statement-extra-keys", keys=sorted(set(body) - STMT_KEYS))
    assert type(body["opening_balance"]) is int and type(body["closing_balance"]) is int, body
    assert type(body["has_more"]) is bool, body
    assert isinstance(body["snapshot"], str) and body["snapshot"], body
    assert isinstance(body["entries"], list)
    for e in body["entries"]:
        miss = ENTRY_KEYS - set(e)
        assert not miss, f"statement entry lacks {miss}: {e}"
        soft(set(e) == ENTRY_KEYS, "entry-extra-keys", keys=sorted(set(e) - ENTRY_KEYS))
        check_payment(e["payment"])
        assert type(e["delta"]) is int and type(e["balance_after"]) is int and type(e["revision"]) is int, e
        inst(e["effective_at"])
        inst(e["recorded_at"])
        inst(e["payment"]["created_at"])
    return body


def full_statement(w: "World", handle: str, page: int = 200, **params) -> dict:
    """The whole window: the first read, then its snapshot paged to the end. Asserts the pages agree."""
    first = ok(statement(w, handle, limit=page, **params), 200)
    check_statement_shape(first)
    entries = list(first["entries"])
    more, off = first["has_more"], len(first["entries"])
    while more:
        nxt = ok(statement(w, handle, snapshot=first["snapshot"], limit=page, offset=off), 200)
        assert (nxt["opening_balance"], nxt["closing_balance"]) == (first["opening_balance"], first["closing_balance"])
        assert nxt["entries"], "has_more was true but the next page is empty"
        entries += nxt["entries"]
        off += len(nxt["entries"])
        more = nxt["has_more"]
    return {**first, "entries": entries, "has_more": False}


class Model:
    """Brute-force reference: every historical view is recomputed from the raw revision and hold-event lists."""

    def __init__(self):
        self.opening: dict[str, int] = {}
        self.pay: dict[str, dict] = {}
        self.auth: dict[str, dict] = {}

    # ---- building
    def add_payment(self, obj: dict, revs: list[dict] | None = None):
        p = {"obj": obj, "frm": obj["from_user_id"], "to": obj["to_user_id"], "revs": []}
        self.pay[obj["payment_id"]] = p
        if revs is None:
            revs = [{"payment_id": obj["payment_id"], "revision": 1, "amount": obj["amount"],
                     "effective_at": obj["created_at"], "recorded_at": obj["created_at"], "reason": ""}]
        for r in revs:
            self.add_revision(obj["payment_id"], r)
        return p

    def add_revision(self, pid: str, r: dict):
        self.pay[pid]["revs"].append({**r, "eff": inst(r["effective_at"]), "rec": inst(r["recorded_at"])})

    def set_auth(self, a: dict, nohist: bool = False):
        caps = []
        for cp in a["payment_ids"]:
            po = self.pay[cp]["obj"]
            caps.append((inst(po["created_at"]), po["amount"]))
        self.auth[a["authorization_id"]] = {
            "obj": a, "frm": a["from_user_id"], "amount": a["amount"], "created": inst(a["created_at"]),
            "expires": inst(a["expires_at"]), "caps": caps, "status": a["status"], "nohist": nohist,
            "closed": inst(a["closed_at"]) if a.get("closed_at") else None}

    # ---- views
    @staticmethod
    def selected(p: dict, K=None):
        best = None
        for r in p["revs"]:
            if K is None or r["rec"] <= K:
                best = r
        return best

    def total(self, uid: str, T=None, K=None, strict: bool = False) -> int:
        t = self.opening[uid]
        for p in self.pay.values():
            if uid not in (p["frm"], p["to"]):
                continue
            r = self.selected(p, K)
            if r is None:
                continue
            if T is not None and (r["eff"] >= T if strict else r["eff"] > T):
                continue
            t += r["amount"] if p["to"] == uid else -r["amount"]
        return t

    def held(self, uid: str, T, K=None) -> int:
        h = 0
        for a in self.auth.values():
            if a["frm"] != uid or a["nohist"]:
                continue
            if a["created"] > T or (K is not None and a["created"] > K):
                continue
            if T >= a["expires"]:
                continue
            z = a["closed"]
            if a["status"] in ("captured", "voided") and z is not None and z <= T and (K is None or z <= K):
                continue
            rem = a["amount"]
            for (ct, amt) in a["caps"]:
                if ct <= T and (K is None or ct <= K):
                    rem -= amt
            h += rem
        return h

    def statement(self, uid: str, frm=None, to=None, K=None):
        rows = []
        for pid, p in self.pay.items():
            if uid not in (p["frm"], p["to"]):
                continue
            r = self.selected(p, K)
            if r is None:
                continue
            if (frm is not None and r["eff"] < frm) or (to is not None and r["eff"] >= to):
                continue
            rows.append((r["eff"], pid, p, r))
        rows.sort(key=lambda x: (x[0], x[1]))
        opening = self.opening[uid] if frm is None else self.total(uid, frm, K, strict=True)
        bal, entries = opening, []
        for (_, pid, p, r) in rows:
            delta = r["amount"] if p["to"] == uid else -r["amount"]
            bal += delta
            entries.append({"payment": {**p["obj"], "amount": r["amount"]}, "delta": delta, "balance_after": bal,
                            "revision": r["revision"], "effective_at": r["effective_at"],
                            "recorded_at": r["recorded_at"]})
        return opening, entries, bal

    def boundaries(self, uids=None) -> list:
        b = set()
        for p in self.pay.values():
            if uids is None or p["frm"] in uids or p["to"] in uids:
                for r in p["revs"]:
                    b.add(r["eff"])
                    b.add(r["rec"])
        for a in self.auth.values():
            if uids is None or a["frm"] in uids:
                b.add(a["created"])
                b.add(a["expires"])
                if a["closed"] is not None:
                    b.add(a["closed"])
                for (ct, _) in a["caps"]:
                    b.add(ct)
        return sorted(b)

    def overdraft(self, uids, now) -> tuple | None:
        """First (user, instant, total, available) that is negative at a past boundary under the latest revisions."""
        for uid in uids:
            bs = set()
            for p in self.pay.values():
                if uid in (p["frm"], p["to"]):
                    bs.add(p["revs"][-1]["eff"])
            for a in self.auth.values():
                if a["frm"] == uid and not a["nohist"]:
                    bs.update([a["created"], a["expires"]] + [c for (c, _) in a["caps"]]
                              + ([a["closed"]] if a["closed"] is not None else []))
            for b in sorted(x for x in bs if x <= now):
                t = self.total(uid, b)
                av = t - self.held(uid, b)
                if t < 0 or av < 0:
                    return (uid, fmt(b), t, av)
        return None


def all_pages(w: "World", handle: str, path: str, member: str) -> list[dict]:
    out, off = [], 0
    while True:
        r = call("GET", f"{path}?limit=200&offset={off}", w.t(handle), base=w.base)
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        out += j[member]
        if not j["has_more"]:
            return out
        off += 200


def build_model(w: "World", opening_from_fixture: bool = True, nohist=()) -> Model:
    """Rebuild the reference model from what the service itself reports (feed, revisions, authorisations)."""
    m = Model()
    by_id = {}
    handle_of = {}
    for h in w.handles():
        me = w.me(h)
        handle_of[me["user_id"]] = h
        for p in all_pages(w, h, "/activity", "payments"):
            by_id[p["payment_id"]] = p
    for pid, p in by_id.items():
        r = revisions(w, handle_of[p["from_user_id"]], pid)
        assert r.status_code == 200, f"revisions of {pid}: {r.status_code} {r.text[:200]}"
        revs = r.json()["revisions"]
        assert [x["revision"] for x in revs] == list(range(1, len(revs) + 1)), revs
        for x in revs:
            check_revision(x, payment_id=pid)
        m.add_payment(p, revs)
    seen = {}
    for h in w.handles():
        for a in all_pages(w, h, "/authorizations", "authorizations"):
            seen[a["authorization_id"]] = a
    for aid, a in seen.items():
        m.set_auth(a, nohist=aid in nohist)
    if opening_from_fixture:
        seeded = {u["id"]: u["balance"] for u in w.fx["users"]}
        for sp in w.fx.get("payments") or []:
            seeded[sp["from_user_id"]] += sp["amount"]
            seeded[sp["to_user_id"]] -= sp["amount"]
        for uid in handle_of:
            m.opening[uid] = seeded.get(uid, 0)
    else:
        for uid, h in handle_of.items():
            m.opening[uid] = 0
            m.opening[uid] = w.me(h)["balance"] - m.total(uid)
    m.handle_of = handle_of
    return m


def grid_instants(m: Model, extra=()) -> list:
    pts = set(extra)
    for b in m.boundaries():
        pts.update([b - US, b, b + US])
    bs = m.boundaries() or [now_f()]
    pts.update([bs[0] - 86400, now_f() + 86400 * 365])
    lo, hi = inst("0001-01-02T00:00:00Z"), inst("9999-12-30T00:00:00Z")
    return sorted(x for x in pts if lo <= x <= hi)        # instants the notation can express, in any offset


def check_me(w: "World", m: Model, handle: str, T=None, K=None, hard_held: bool = True) -> dict:
    uid = next(u for u, h in m.handle_of.items() if h == handle)
    a, kn = (fmt(T) if T is not None else None), (fmt(K) if K is not None else None)
    before = now_f()
    r = me_at(w, handle, a, kn)
    body = ok(r, 200, f"/me as_of={a} known_at={kn}")
    after = now_f()
    total = m.total(uid, T, K)
    assert body["balance"] == total and body["total"] == total, \
        f"{handle} as_of={a} known_at={kn}: total expected {total}, got {body}"
    assert body["available"] == body["total"] - body["held"], body
    if T is not None:
        held = {m.held(uid, T, K)}
    else:
        held = {m.held(uid, before, K), m.held(uid, after, K)}
    if hard_held:
        assert body["held"] in held, f"{handle} as_of={a} known_at={kn}: held expected {held}, got {body}"
    else:
        soft(body["held"] in held, "historical-held-differs", handle=handle, as_of=a, known_at=kn, got=body["held"],
             want=sorted(held))
    if a is not None:
        assert body.get("as_of") == a, f"as_of not echoed exactly: {body.get('as_of')!r} vs {a!r}"
    else:
        assert "as_of" not in body, body
    if kn is not None:
        assert body.get("known_at") == kn, f"known_at not echoed exactly: {body.get('known_at')!r} vs {kn!r}"
    else:
        assert "known_at" not in body, body
    return body


def same_entry(got: dict, want: dict, where: str = "") -> None:
    for kk in ("delta", "balance_after", "revision"):
        assert got[kk] == want[kk], f"{where} entry.{kk}: expected {want[kk]}, got {got[kk]} ({got})"
    assert got["payment"] == want["payment"], f"{where} entry.payment differs:\n got {got['payment']}\nwant {want['payment']}"
    for kk in ("effective_at", "recorded_at"):
        assert inst(got[kk]) == inst(want[kk]), f"{where} entry.{kk}: expected {want[kk]}, got {got[kk]}"
        soft(got[kk] == want[kk], "instant-not-echoed-verbatim", member=kk, got=got[kk], want=want[kk])


def check_statement(w: "World", m: Model, handle: str, frm=None, to=None, K=None, page: int = 200) -> dict:
    uid = next(u for u, h in m.handle_of.items() if h == handle)
    params = {}
    if frm is not None:
        params["from"] = fmt(frm)
    if to is not None:
        params["to"] = fmt(to)
    if K is not None:
        params["known_at"] = fmt(K)
    got = full_statement(w, handle, page=page, **params)
    opening, entries, closing = m.statement(uid, frm, to, K)
    where = f"{handle} statement {params}"
    assert got["opening_balance"] == opening, f"{where}: opening expected {opening}, got {got['opening_balance']}"
    assert got["closing_balance"] == closing, f"{where}: closing expected {closing}, got {got['closing_balance']}"
    ids = [e["payment"]["payment_id"] for e in got["entries"]]
    assert ids == [e["payment"]["payment_id"] for e in entries], \
        f"{where}: entries expected {[e['payment']['payment_id'] for e in entries]}, got {ids}"
    for g, e in zip(got["entries"], entries):
        same_entry(g, e, where)
    assert opening + sum(e["delta"] for e in got["entries"]) == closing
    return got


def check_everything(w: "World", m: Model, rng, me_points: int = 60, st_points: int = 25, hard_held: bool = True,
                     handles=None) -> None:
    """Compare /me and /statement with the model on a grid of instants around every boundary."""
    handles = handles or list(m.handle_of.values())
    pts = grid_instants(m)
    seeded_total = sum(m.opening.values())
    for h in handles:                                    # the plain reads
        check_me(w, m, h, hard_held=hard_held)
        check_statement(w, m, h)
    pairs = [(t, None) for t in pts] + [(None, kk) for kk in pts]
    pairs += [(rng.choice(pts), rng.choice(pts)) for _ in range(me_points)]
    if len(pairs) > me_points * 3:
        pairs = rng.sample(pairs, me_points * 3)
    for (T, K) in pairs:
        s = 0
        for h in handles:
            s += check_me(w, m, h, T, K, hard_held=hard_held)["balance"]
        if len(handles) == len(m.handle_of):
            assert s == seeded_total, f"sum of balances at as_of={T and fmt(T)} known_at={K and fmt(K)} is {s}, seeded {seeded_total}"
    for h in handles:
        for _ in range(st_points):
            a, b = sorted([rng.choice(pts), rng.choice(pts)])
            kk = rng.choice([None, None, rng.choice(pts)])
            frm = rng.choice([a, a, None])
            to = rng.choice([b, b, None])
            if to is None and frm is not None and frm > now_f() - 5:
                to = b                      # `to` defaults to now: a later `from` is not a window (map G-9: 422)
            check_statement(w, m, h, frm, to, kk, page=rng.choice([200, 3, 7]))



# ====================================================================== stage 4: refunds and correction batches
def refund(w: "World", who: str, pid: str, amount, key=None, **extra):
    return call("POST", f"/payments/{pid_path(pid)}/refunds", w.t(who), key=key or k(), body={"amount": amount, **extra},
                base=w.base)


def item(p: dict, amount, expected=1, effective_at=None, reason="batch", **extra) -> dict:
    return {"payment_id": p["payment_id"], "expected_revision": expected, "amount": amount,
            "effective_at": p["created_at"] if effective_at is None else effective_at, "reason": reason, **extra}


def batch(w: "World", items: list, who: str = "op", key=None, **extra):
    return call("POST", "/correction-batches", w.t(who), key=key or k(), body={"corrections": items, **extra}, base=w.base)


BATCH_KEYS = {"correction_batch_id", "recorded_at", "revisions"}


def check_batch(j: dict, items: list) -> dict:
    assert isinstance(j, dict) and BATCH_KEYS <= set(j), j
    soft(set(j) == BATCH_KEYS, "batch-extra-keys", keys=sorted(set(j) - BATCH_KEYS))
    assert isinstance(j["correction_batch_id"], str) and 1 <= len(j["correction_batch_id"]) <= 64, j
    rec = inst(j["recorded_at"])
    assert [r["payment_id"] for r in j["revisions"]] == [i["payment_id"] for i in items], "revisions must be in input order"
    for r, i in zip(j["revisions"], items):
        check_revision(r, amount=i["amount"], reason=i["reason"], revision=i["expected_revision"] + 1)
        assert inst(r["recorded_at"]) == rec, f"all revisions of a batch share recorded_at: {r['recorded_at']} vs {j['recorded_at']}"
        assert r.get("correction_batch_id") == j["correction_batch_id"], f"revision does not expose the batch id: {r}"
        assert inst(r["effective_at"]) == inst(i["effective_at"])
    return j


def refunded(m: Model, pid: str) -> int:
    return sum(p["obj"]["amount"] for p in m.pay.values() if p["obj"].get("refund_of") == pid)


def members(m: Model, sid: str) -> list:
    return [pid for pid, p in m.pay.items() if p["obj"].get("settlement_id") == sid]
