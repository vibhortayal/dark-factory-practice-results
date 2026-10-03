"""Rows J: export / import between two independent servers."""
import json

from .base import ApiTestCase
from .support import Api, fixture, user


class ExportImportTests(ApiTestCase):
    def test_roundtrip_across_servers(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"]))
        pay = self.pay("ada", "bob", 100, "KP", note="é😀")[1]
        req = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 7}, who="bob", key="KR")[1]
        self.call("POST", "/splits", {"amount": 9, "participant_handles": ["ada", "bob"]}, who="ada", key="KS")
        st = self.call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 3}]},
                       who="ada", key="KT")[1]
        self.pay("cy", "ada", 9999, "KF")  # failed (insufficient) key must stay reusable
        new = self.call("POST", "/auth/signup", {"email": "n@x.com", "password": "longenough", "display_name": "N"})[1]
        s, doc, _ = self.api.call("GET", "/_test/export")
        self.assertEqual((s, doc["track"], doc["format_version"]), (200, "pocketful", 1))
        before = {h: self.balance(h) for h in ("ada", "bob", "cy")}
        feed_before = self.call("GET", "/activity?limit=200", who="ada")[1]
        reqs_before = self.call("GET", "/requests", who="ada")[1]

        other = Api()
        try:
            other.reset(fixture(users=[user("zed", 5)]))
            self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)
            self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)  # repeat: no dupes
            ada = self.tok["ada"]  # existing token still valid on the new server
            self.assertEqual(other.call("GET", "/me", token=ada)[1]["balance"], before["ada"])
            self.assertEqual(other.call("GET", "/me", token=new["token"])[1]["handle"], "n")
            self.assertEqual(other.call("GET", "/activity?limit=200", token=ada)[1], feed_before)
            self.assertEqual(other.call("GET", "/requests", token=ada)[1], reqs_before)
            s, b, _ = other.call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "é😀"}, token=ada, key="KP")
            self.assertEqual((s, b), (200, pay))
            self.assertEqual(other.call("POST", "/payments", {"to_handle": "bob", "amount": 101}, token=ada, key="KP")[0], 409)
            s, b, _ = other.call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 3}]},
                                 token=ada, key="KT")
            self.assertEqual((s, b), (200, st))
            self.assertEqual(other.call("GET", "/me", token=ada)[1]["balance"], before["ada"])
            self.assertEqual(other.call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"})[0], 401)
            self.assertEqual(other.call("GET", "/_test/export")[1], doc)
            cy = other.login("cy@example.com")
            self.assertEqual(other.call("POST", "/payments", {"to_handle": "ada", "amount": 9999}, token=cy, key="KF")[0], 409)
            self.assertEqual(other.call("POST", "/payments", {"to_handle": "ada", "amount": 1}, token=cy, key="KF")[0], 201)
            other.reset(fixture(users=[user("q", 1)]))
            self.assertEqual(other.call("GET", "/me", token=ada)[0], 401)
        finally:
            other.close()

    def test_export_is_snapshot(self):
        self.reset()
        doc = self.api.call("GET", "/_test/export")[1]
        self.pay("ada", "bob", 100, "K")
        self.assertEqual(doc["state"]["payments"], [])

    def test_import_errors_leave_state(self):
        self.reset()
        doc = self.api.call("GET", "/_test/export")[1]
        self.pay("ada", "bob", 100, "K")
        bad_state = json.loads(json.dumps(doc))
        bad_state["state"]["users"][0]["balance"] = -5
        wrong_ver = dict(doc, format_version=2)
        for bad in ({}, {"track": "pocketful"}, dict(doc, track="other"), wrong_ver,
                    dict(doc, state=[]), bad_state, dict(doc, state={"users": 1})):
            self.expect(422, "validation_failed", self.api.call("POST", "/_test/import", bad))
        self.expect(400, "malformed_request", self.api.call("POST", "/_test/import", raw=b"{x"))
        self.assertEqual(self.balance("ada"), 9900)
        self.assertEqual(self.api.call("POST", "/_test/import", doc)[0], 204)
        self.assertEqual(self.balance("ada"), 10000)
