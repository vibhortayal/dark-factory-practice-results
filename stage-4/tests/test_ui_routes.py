import json
import random
import threading

from .helpers import World, call


class UiRouteTests(World):
    def test_html_for_ui_routes_and_json_for_api(self):
        for path in ("/", "/split", "/signup", "/login"):
            for accept in ({}, {"Accept": "application/json"}, {"Accept": "text/html"}):
                r = call("GET", path, headers=accept)
                self.assertEqual(r.status, 200, (path, accept))
                self.assertTrue(r.headers["Content-Type"].startswith("text/html"))
                self.assertIn(b"/static/js/app.js", r.raw)
        for path in ("/requests", "/authorizations"):
            html = call("GET", path, headers={"Accept": "text/html,application/xhtml+xml"})
            self.assertTrue(html.headers["Content-Type"].startswith("text/html"), path)
            self.assertErr(call("GET", path), 401, "unauthenticated")
            self.assertEqual(call("GET", path, token=self.tok["ada"]).status, 200)
            self.assertTrue(call("GET", path, token=self.tok["ada"], headers={"Accept": "application/json"}).headers["Content-Type"].startswith("application/json"))

    def test_static_assets_and_traversal(self):
        for asset, kind in (("styles.css", "text/css"), ("js/app.js", "javascript"), ("js/pages/home.js", "javascript")):
            r = call("GET", "/static/" + asset)
            self.assertEqual(r.status, 200, asset)
            self.assertIn(kind, r.headers["Content-Type"])
        for bad in ("/static/nothing.js", "/static/../server.py", "/static/%2e%2e/server.py", "/static/js", "/static/"):
            self.assertErr(call("GET", bad), 404, "not_found")

    def test_assets_use_no_other_origin(self):
        import os
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pocketful", "ui")
        for folder, _, files in os.walk(root):
            for name in files:
                text = open(os.path.join(folder, name), encoding="utf-8").read()
                self.assertNotIn("http://", text.replace("http://www.w3.org", ""), name)
                self.assertNotIn("https://", text, name)


class GapTests(World):
    def test_concurrent_signups_same_email_and_handle(self):
        out = []

        def go(email):
            out.append(call("POST", "/auth/signup", {"email": email, "password": "longenough", "display_name": "N"}).status)
        ts = [threading.Thread(target=go, args=("same@x.io" if i % 2 else "same@y.io",)) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        # same@x.io and same@y.io derive the same handle: exactly one account is created
        self.assertEqual(out.count(201), 1)
        self.assertTrue(set(out) <= {201, 409})

    def test_random_split_sweep(self):
        rng = random.Random(7)
        for _ in range(40):
            n = rng.randint(1, 3)
            handles = rng.sample(["ada", "bob", "cy"], n)
            amount = rng.randint(1, 2000)
            r = self.post("ada", "/splits", {"amount": amount, "participant_handles": handles})
            self.assertEqual(r.status, 201)
            base, extra = divmod(amount, n)
            self.assertEqual([s["amount"] for s in r.json["shares"]], [base + (i < extra) for i in range(n)])
            self.assertEqual(sum(s["amount"] for s in r.json["shares"]), amount)
