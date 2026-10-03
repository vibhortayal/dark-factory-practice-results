"""Shared helpers for the stage-2 verifier checks (stage-1 helpers carried forward). No dependency on the repository under review."""
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
VOUT = os.environ.get("VOUT", "/tmp/nsv-s2-out")
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
        if k in ("created_at", "committed_at"):
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
            "note", "visibility", "request_id", "settlement_id", "authorization_id", "created_at"}
AUTH_KEYS = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "captured_amount",
             "remaining_amount", "currency", "note", "visibility", "status", "expires_at", "payment_id",
             "payment_ids", "created_at"}
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
