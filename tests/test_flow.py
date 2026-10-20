"""End-to-end test of the POC on the mock data. Run: python -m unittest -v"""
import os
import tempfile
import time
import unittest

TMP = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(TMP, "test.sqlite3")
os.environ["CCC_NO_SCHEDULER"] = "1"
os.environ["SLA_SECONDS_PER_HOUR"] = "0.05"      # 24 h SLA = 1.2 s, so escalation is testable
os.environ["OPENAI_API_KEY"] = ""             # set, not removed, so a key in .env cannot switch tests to the LLM

from app import actions, db, pipeline, seed          # noqa: E402
from app.agents import links, replies, sla          # noqa: E402


def release_future(minutes=60):
    """Move the demo clock forward: everything scheduled within `minutes` is now on the platforms."""
    with db.tx() as c:
        c.execute("UPDATE mock_feed SET release_at=replace(datetime(release_at, ?), ' ', 'T') || '+00:00'", (f"-{minutes} minutes",))
        c.execute("UPDATE mock_feed SET edit_at=replace(datetime(edit_at, ?), ' ', 'T') || '+00:00' WHERE edit_at IS NOT NULL", (f"-{minutes} minutes",))
        c.execute("UPDATE meta SET value=replace(datetime(value, ?), ' ', 'T') || '+00:00' WHERE key='epoch'", (f"-{minutes} minutes",))
        c.execute("UPDATE source_watermark SET last_seen=replace(datetime(last_seen, ?), ' ', 'T') || '+00:00'", (f"-{minutes} minutes",))


def case_of(platform, ext):
    return db.q1("""SELECT c.* FROM complaint_post p JOIN complaint_case c ON c.case_id=p.case_id
                    WHERE p.platform=? AND p.external_post_id=?""", (platform, ext))


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.seed(reset=True)
        pipeline.collect_all()

    def test_1_initial_ingest(self):
        posts = db.q1("SELECT COUNT(*) n FROM complaint_post")["n"]
        self.assertGreaterEqual(posts, 10)
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM ignored_post")["n"], 1, "the 5-star review is not a case")
        a, b = case_of("trustpilot", "tp-1002"), case_of("trustpilot", "tp-1003")
        self.assertEqual(a["case_id"], b["case_id"], "same account + same problem = one case")
        self.assertEqual(a["theme"], "B4")
        neha = case_of("playstore", "pl-4001")
        self.assertEqual(neha["theme"], "S1")
        self.assertEqual(neha["booking_ref"], "APPT-61873")
        self.assertEqual(neha["identity_status"], "candidate", "an ID in the text proposes the customer")
        rocky = case_of("trustpilot", "tp-1001")
        self.assertEqual(rocky["theme"], "S3")
        self.assertEqual(rocky["priority"], 1, "legal threat on an RC case is critical")
        self.assertIn("Legal", rocky["owner_team"])
        sug = db.q1("SELECT * FROM identity_match WHERE method='cross_channel' AND case_id=?", (case_of("trustpilot", "tp-1006")["case_id"],))
        self.assertIsNotNone(sug, "email ticket and Trustpilot post look like the same seller")

    def test_2_one_link_per_person_per_case(self):
        a = case_of("trustpilot", "tp-1002")
        n = db.q1("SELECT COUNT(*) n FROM tracked_link WHERE case_id=?", (a["case_id"],))["n"]
        self.assertEqual(n, 1)
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM reply WHERE case_id=? AND status='draft'", (a["case_id"],))["n"], 2)

    def test_3_case_link_verification_and_cross_platform_merge(self):
        rocky = case_of("trustpilot", "tp-1001")
        token = db.q1("SELECT token FROM tracked_link WHERE case_id=?", (rocky["case_id"],))["token"]
        links.record_click(token)
        code = links.request_otp(token, "98110 00001")
        phone, err = links.check_otp(token, "000000" if code != "000000" else "111111")
        self.assertIsNone(phone)
        phone, err = links.check_otp(token, code)
        self.assertEqual(phone, "+919811000001")
        self.assertEqual(len(links.bookings_for(phone)), 2)
        self.assertTrue(links.confirm(token, phone, "APPT-50112"))
        rocky = case_of("trustpilot", "tp-1001")
        self.assertEqual(rocky["identity_status"], "confirmed")
        self.assertEqual(rocky["vehicle_reg_no"], "DL3CAB4521")
        release_future(60)
        pipeline.collect_all()
        x = case_of("x", "x-2001")
        self.assertEqual(x["case_id"], rocky["case_id"], "the X post with the reg no lands on the Trustpilot case")
        v = db.q1("SELECT version FROM complaint_post WHERE external_post_id='tp-1001'")["version"]
        self.assertEqual(v, 2, "the edited review is versioned")
        self.assertEqual(case_of("trustpilot", "tp-1004")["case_id"], case_of("trustpilot", "tp-1002")["case_id"])

    def test_4_sla_escalation(self):
        time.sleep(1.5)
        n = sla.run()
        self.assertGreater(n, 0)
        self.assertGreater(db.q1("SELECT MAX(escalation_level) m FROM complaint_case")["m"], 1)

    def test_5_resolve_needs_proof(self):
        neha = case_of("playstore", "pl-4001")
        ok, _ = actions.resolve(neha["case_ref"])
        self.assertFalse(ok, "no refund reference in records yet")
        self.assertTrue(actions.simulate_fix(neha["case_ref"]))
        ok, _ = actions.resolve(neha["case_ref"])
        self.assertTrue(ok)
        r = db.q1("SELECT * FROM reply WHERE case_id=? AND kind='resolved'", (neha["case_id"],))
        self.assertTrue(replies.approve(r["reply_id"]))

    def test_6_pages_render(self):
        from app.web import create_app
        app = create_app(start_scheduler=False)
        cl = app.test_client()
        self.assertEqual(cl.get("/").status_code, 200)
        rocky = case_of("trustpilot", "tp-1001")
        self.assertEqual(cl.get(f"/cases/{rocky['case_ref']}").status_code, 200)
        token = db.q1("SELECT token FROM tracked_link WHERE case_id=?", (case_of("google", "gg-3001")["case_id"],))["token"]
        self.assertEqual(cl.get(f"/c/{token}").status_code, 200)
        r = cl.post(f"/c/{token}/otp", data={"phone": "9811000002"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(cl.get("/platforms/trustpilot").status_code, 200)
        r = cl.post("/actions/simulate", data={"platform": "x", "username": "@test_user", "rating": "",
                                               "body": "@CARS24 RC of DL3CAB4521 still pending, please fix"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/cases/", r.headers["Location"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
