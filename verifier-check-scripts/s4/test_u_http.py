"""U2 / K5 / M1 over plain HTTP: content negotiation, UI shells and assets, stage-1 export into stage 2."""
import copy
import re
import socket
from urllib.parse import urljoin, urlsplit

import pytest

from lib import BASE, BASE1, GET, POST, PW, World, call, check_payment, code_of, err, fixture, k, me_core, ok, soft, ts, user

UI_ROUTES = ["/", "/requests", "/split", "/signup", "/login", "/authorizations"]
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
_u = urlsplit(BASE)


def html(path, accept="text/html", **kw):
    return call("GET", path, headers={"Accept": accept} if accept is not None else None, kind="any", **kw)


def is_html(r):
    return r.status_code == 200 and r.headers.get("content-type", "").lower().replace(" ", "") == "text/html;charset=utf-8" \
        and "<html" in r.text.lower()


@pytest.fixture(scope="module")
def w():
    return World().login_all()


@pytest.mark.parametrize("path", UI_ROUTES)
@pytest.mark.parametrize("accept", ["text/html", BROWSER_ACCEPT, "text/html; charset=utf-8", "TEXT/HTML"])
def test_u1_ui_routes_answer_html_without_a_token(w, path, accept):
    r = html(path, accept)
    if accept == "TEXT/HTML" and not is_html(r):
        soft(False, "accept-header-case-sensitive", path=path, status=r.status_code)
        return
    assert is_html(r), f"{path} with Accept {accept!r}: {r.status_code} {r.headers.get('content-type')} {r.text[:80]!r}"
    assert "<title" in r.text.lower()


@pytest.mark.parametrize("path", ["/requests", "/authorizations"])
@pytest.mark.parametrize("accept", [None, "*/*", "application/json", "application/json, text/plain, */*",
                                    "application/xhtml+xml", "text/plain"])
def test_u2_shared_routes_answer_json_without_text_html(w, path, accept):
    r = call("GET", path, headers={"Accept": accept} if accept else None)
    err(r, 401, "unauthenticated", f"{path} Accept {accept!r} without a token")
    r = call("GET", path, w.t("ada"), headers={"Accept": accept} if accept else None)
    j = ok(r, 200)
    assert set(j) >= {"requests" if path == "/requests" else "authorizations", "has_more"}


@pytest.mark.parametrize("path", ["/requests", "/authorizations"])
def test_u2_shared_routes_with_token_and_text_html(w, path):
    r = html(path, BROWSER_ACCEPT, token=w.t("ada"))
    assert is_html(r)
    r = html(path + "?status=open&limit=5", "text/html")
    assert is_html(r) or r.status_code == 200
    # writes on the shared path stay API calls whatever the Accept header says
    r = call("POST", "/requests", w.t("ada"), key=k(), body={"payer_handle": "bob", "amount": 5},
             headers={"Accept": "text/html"})
    assert ok(r, 201)["status"] == "pending"
    r = call("POST", "/authorizations", w.t("ada"), key=k(), body={"to_handle": "bob", "amount": 5},
             headers={"Accept": BROWSER_ACCEPT})
    assert ok(r, 201)["status"] == "open"


@pytest.mark.parametrize("path", ["/me", "/activity", "/health", "/_test/export"])
def test_u2_api_only_routes_stay_json_for_browsers(w, path):
    r = call("GET", path, w.t("ada"), headers={"Accept": BROWSER_ACCEPT}, kind="any")
    assert r.status_code == 200
    soft("application/json" in r.headers.get("content-type", ""), "api-route-html-for-browser-accept", path=path,
         content_type=r.headers.get("content-type"))


@pytest.mark.parametrize("path", ["/", "/split", "/signup", "/login"])
def test_u1_ui_only_routes_without_accept(w, path):
    r = call("GET", path, kind="any")
    assert r.status_code < 500
    soft(is_html(r), "ui-route-needs-accept-html", path=path, status=r.status_code)
    r = html(path + "?next=%2Frequests&x=1")
    assert is_html(r)


@pytest.mark.parametrize("path", UI_ROUTES)
@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
def test_k5_ui_routes_other_methods_never_5xx(w, path, method):
    if method in ("POST", "PUT", "PATCH"):
        r = call(method, path, headers={"Accept": "text/html"}, kind="any", body={})
    else:
        r = call(method, path, headers={"Accept": "text/html"}, kind="any")
    assert r.status_code < 500, f"{method} {path}: {r.status_code}"


def _assets(w):
    found = set()
    for path in UI_ROUTES:
        text = html(path).text
        for m in re.finditer(r'''(?:src|href)\s*=\s*["']([^"'#]+)["']''', text):
            found.add((path, m.group(1)))
    return found


def test_k3_pages_reference_only_same_origin_assets(w):
    refs = _assets(w)
    external = sorted({ref for _, ref in refs if re.match(r"^(https?:)?//", ref) and urlsplit(urljoin(BASE, ref)).netloc != _u.netloc})
    assert not external, f"pages reference another origin: {external}"
    for path in UI_ROUTES:
        text = html(path).text
        hits = [u for u in re.findall(r'''https?://[^\s"'<>)]+''', text)
                if "w3.org" not in u and urlsplit(u).netloc != _u.netloc]
        assert not hits, f"{path} mentions external URLs: {hits[:5]}"
        assert "@import" not in text or "http" not in text.split("@import", 1)[1][:80]


def test_k5_assets_have_proper_types_and_exist(w):
    refs = _assets(w)
    assets = sorted({urlsplit(urljoin(BASE + page, ref)).path for page, ref in refs
                     if not ref.startswith(("data:", "mailto:", "javascript:")) and urlsplit(urljoin(BASE + page, ref)).path not in UI_ROUTES})
    for a in assets:
        r = call("GET", a, kind="any")
        assert r.status_code == 200, f"asset {a}: {r.status_code}"
        ct = r.headers.get("content-type", "").lower()
        if a.endswith(".js") or a.endswith(".mjs"):
            assert "javascript" in ct, f"{a}: {ct}"
        elif a.endswith(".css"):
            assert ct.startswith("text/css"), f"{a}: {ct}"
        elif a.endswith(".svg"):
            assert "svg" in ct, f"{a}: {ct}"
        elif a.endswith((".woff2", ".woff", ".ttf")):
            assert "font" in ct or "octet-stream" in ct, f"{a}: {ct}"
        elif a.endswith((".png", ".ico", ".jpg", ".webp")):
            assert ct.startswith("image/"), f"{a}: {ct}"
        if a.endswith((".js", ".css")):
            ext = [u for u in re.findall(r'''https?://[^\s"'<>)`\\]+''', r.text)
                   if "w3.org" not in u and urlsplit(u).netloc not in (_u.netloc, "")]
            soft(not ext, "asset-mentions-external-url", asset=a, urls=ext[:5])
            assert "@import url(http" not in r.text and "fonts.googleapis" not in r.text
        for method in ("HEAD", "POST", "DELETE"):
            assert call(method, a, kind="any").status_code < 500


def raw_get(target: str) -> tuple[int, str]:
    s = socket.create_connection((_u.hostname, _u.port), timeout=6)
    try:
        s.sendall(f"GET {target} HTTP/1.1\r\nHost: x\r\nAccept: text/html\r\nConnection: close\r\n\r\n".encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    text = buf.decode("latin-1")
    status = int(text.split()[1]) if text.startswith("HTTP/") else -1
    return status, text


TRAVERSALS = ["/../app.py", "/static/../app.py", "/static/../../etc/passwd", "/..%2fapp.py", "/static/..%2f..%2fapp.py",
              "/%2e%2e/%2e%2e/etc/passwd", "/static/%2e%2e/app.py", "/assets/../app.py", "/static//etc/passwd",
              "/static/..\\app.py", "//etc/passwd", "/static/%00", "/static/", "/static", "/assets/", "/app.py",
              "/Dockerfile", "/static/.", "/static/..", "/.git/config", "/ui/../app.py", "/etc/passwd"]


@pytest.mark.parametrize("target", TRAVERSALS)
def test_k5_no_path_traversal_and_no_5xx(w, target):
    status, text = raw_get(target)
    assert 0 < status < 500, f"{target}: {status}"
    body = text.split("\r\n\r\n", 1)[-1]
    assert "root:x:0" not in body and "ThreadingHTTPServer" not in body and "import hashlib" not in body \
        and "FROM python" not in body, f"{target} leaks a file from the image"
    refs = sorted({urlsplit(urljoin(BASE, ref)).path for _, ref in _assets(w) if ref.endswith((".js", ".css"))})
    for a in refs[:3]:
        base_dir = a.rsplit("/", 1)[0]
        for t in (f"{base_dir}/../app.py", f"{base_dir}/..%2fapp.py", f"{base_dir}/%2e%2e/app.py"):
            st, tx = raw_get(t)
            assert 0 < st < 500 and "import hashlib" not in tx and "def " not in tx.split("\r\n\r\n", 1)[-1][:2000], t


# ---------------------------------------------------------------- M1: an export of the accepted stage-1 service

def build_stage1():
    """State on the stage-1 container covering all five stage-1 paths (no stage-2 members anywhere)."""
    assert BASE1, "BASE1 (a container of the accepted stage-1 image) is not set"
    pays = [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee ☕",
             "visibility": "public"}]
    reqs = [{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
            {"id": "rq_dec", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 5, "note": "", "status": "declined"}]
    w = World(fixture(payments=pays, requests=reqs), base=BASE1).login_all()
    done = []

    def rec(who, path, body, expect=201):
        key = k()
        r = call("POST", path, w.t(who), key=key, body=body, base=BASE1)
        assert r.status_code == expect, r.text
        if expect == 201:
            done.append({"who": who, "path": path, "key": key, "body": body, "resp": r.json()})
        return key, r.json()

    su = w.signup("late.comer@example.com", display_name="Late")
    rec("ada", "/payments", {"to_handle": "bob", "amount": 100, "note": "pub 😀", "ratio": 0.5})
    rec("ada", "/payments", {"to_handle": "cy", "amount": 250, "note": "prv", "visibility": "private"})
    _, q1 = rec("bob", "/requests", {"payer_handle": "ada", "amount": 40, "note": "r1"})
    rec("bob", "/requests", {"payer_handle": "cy", "amount": 99999, "note": "too much"})
    rec("ada", f"/requests/{q1['request_id']}/pay", {"visibility": "private"})
    _, s = rec("ada", "/splits", {"amount": 100, "participant_handles": ["ada", "bob", "cy"], "note": "split"})
    rec("op", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "s"},
                                             {"from_handle": "bob", "to_handle": "dan", "amount": 50, "visibility": "private"}]})
    failed_key, _ = rec("ada", "/payments", {"to_handle": "ghost", "amount": 1}, expect=404)
    tokens = {h: w.t(h) for h in w.handles()}
    return w, done, tokens, failed_key, su


def strip2(v):
    """Drop the members stage 2 adds, to compare with stage-1 answers."""
    if isinstance(v, dict):
        return {kk: strip2(x) for kk, x in v.items() if kk not in ("authorization_id", "total", "available", "held", "refund_of")}
    if isinstance(v, (list, tuple)):
        return [strip2(x) for x in v]
    return v


def snap1(w, tokens, base):
    out = {}
    for h, tk in sorted(tokens.items()):
        out[h] = {"me": call("GET", "/me", tk, base=base).json(),
                  "activity": call("GET", "/activity?limit=200", tk, base=base).json(),
                  "requests": call("GET", "/requests?limit=200", tk, base=base).json()}
    return out


def test_m1_stage1_export_imports_into_stage2():
    w, done, tokens, failed_key, su = build_stage1()
    before = snap1(w, tokens, BASE1)
    e = call("GET", "/_test/export", base=BASE1)
    assert e.status_code == 200
    World(fixture(users=[user("zed", 9)], auths=[]))            # the stage-2 destination holds something else
    r = call("POST", "/_test/import", raw=e.content)
    assert r.status_code == 204, f"stage-2 import of the stage-1 export: {r.status_code} {r.text[:300]}"
    after = snap1(w, tokens, BASE)
    assert strip2(after) == strip2(before)
    for h, v in after.items():
        m = v["me"]
        assert m["balance"] == m["total"] == m["available"] and m["held"] == 0, m
        for p in v["activity"]["payments"]:
            check_payment(p, authorization_id=None)
    # tokens, password login, operator, replays, failed key, pending request, defaults for the new parts
    for h, tk in tokens.items():
        assert call("GET", "/authorizations", tk).json() == {"authorizations": [], "has_more": False}
    assert call("POST", "/auth/login", body={"email": "ada@example.com", "password": PW}).status_code == 200
    assert call("GET", "/me", su["token"]).json()["handle"] == "late_comer"
    for d in done:
        r = call("POST", d["path"], tokens[d["who"]], key=d["key"], body=d["body"])
        assert r.status_code == 200, f"replay {d['path']} after the upgrade: {r.status_code} {r.text[:200]}"
        assert strip2(r.json()) == strip2(d["resp"]), f"replayed body differs on {d['path']}"
        err(call("POST", d["path"], tokens[d["who"]], key=d["key"], body={**d["body"], "changed": 1}), 409,
            "idempotency_key_reuse")
    assert strip2(snap1(w, tokens, BASE)) == strip2(before)
    assert call("POST", "/payments", tokens["ada"], key=failed_key, body={"to_handle": "bob", "amount": 1}).status_code == 201
    p = check_payment(ok(call("POST", "/requests/rq_seed/pay", tokens["ada"], key=k(), body={}), 201), request_id="rq_seed",
                      amount=1200, authorization_id=None)
    a = ok(call("POST", "/authorizations", tokens["ada"], key=k(), body={"to_handle": "bob", "amount": 10}), 201)
    assert (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == 600, "ttl defaults to 600 after a stage-1 import"
    assert ok(call("POST", "/settlements", tokens["op"], key=k(),
                   body={"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2}]}), 201)
    err(call("POST", "/settlements", tokens["ada"], key=k(),
             body={"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2}]}), 403, "forbidden")
    old_p = {x["payment_id"] for h in before for x in before[h]["activity"]["payments"]}
    assert p["payment_id"] not in old_p
    total = sum(call("GET", "/me", tokens[h]).json()["total"] for h in tokens)
    assert total == w.seeded_total()
    # and the stage-2 export of that state imports again
    e2 = call("GET", "/_test/export")
    assert call("POST", "/_test/import", raw=e2.content).status_code == 204


def test_m1_stage2_export_is_refused_or_harmless_in_reverse_is_not_required():
    """Only the forward direction is specified; this records that the stage-1 container is the accepted image."""
    assert BASE1
    r = call("GET", "/authorizations", base=BASE1, kind="any")
    assert r.status_code in (401, 404), "BASE1 does not look like a stage-1 service"
    r = call("GET", "/", base=BASE1, headers={"Accept": "text/html"}, kind="any")
    assert r.status_code == 404
