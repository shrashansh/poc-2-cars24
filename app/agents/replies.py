"""
Stage 6 agent: draft public replies. Rules it never breaks:
  - every fact comes from the case record or Cars24's records, not from the model
  - no phone numbers, IDs or addresses in public
  - never says "refunded" or "transferred" without proof on the case
  - nothing is posted until a person approves it
"""
import json

from .. import config, db
from .links import link_url
from .router import label

CHANNEL_NAME = {"trustpilot": "Trustpilot", "google": "Google", "playstore": "Play Store", "appstore": "App Store",
                "x": "X", "consumercomplaints": "ConsumerComplaints.in", "email": "email"}


def _due(case) -> str:
    """Promise in business hours, from the same rules table the router used."""
    from .router import CRITICAL, THEMES
    hours = CRITICAL[0] if case["priority"] == 1 else THEMES.get(case["theme"], THEMES["O"])[2]
    return f"within {hours} hours"


def draft_ack(c, case_id: str, post_id: str, token: str, platform: str, name: str | None):
    case = c.execute("SELECT * FROM complaint_case WHERE case_id=?", (case_id,)).fetchone()
    if c.execute("SELECT 1 FROM reply WHERE post_id=?", (post_id,)).fetchone():
        return
    facts = json.loads(case["facts"] or "{}")
    lines = [f"Hi {name.split()[0]}," if name and name[0].isalpha() and "@" not in name else "Hi,"]
    known = []
    if facts.get("rc", {}).get("form29c_ack"):
        known.append("your handover is on record with the RTO, so liability since then sits with Cars24")
    if facts.get("refund"):
        known.append("we can see the booking refund and the deduction on our side")
    if facts.get("plan"):
        known.append(f"we can see the {facts['plan'].get('name', 'plan')} on your car and that no auction ran")
    if facts.get("holdback"):
        known.append("we can see the amount held for challans")
    body = (f"this is now case {case['case_ref']} with our {case['owner_team']} team "
            f"({label(case['theme']).split(' · ')[-1]}).")
    if known:
        body += " " + "; ".join(known).capitalize() + "."
    body += f" The team will update you {_due(case)}. Track it and confirm your car here: {link_url(token)}"
    text = lines[0] + " " + body
    c.execute("""INSERT INTO reply (case_id, post_id, token, platform, body, kind, status, drafted_by, created_at)
                 VALUES (?,?,?,?,?,?,?,?,?)""", (case_id, post_id, token, platform, text, "acknowledge", "draft", "agent", db.iso(db.now())))
    db.event(c, case_id, "reply_drafted", "replies", platform=platform, kind="acknowledge")


def draft_resolution(c, case_id: str, proof: dict):
    case = c.execute("SELECT * FROM complaint_case WHERE case_id=?", (case_id,)).fetchone()
    what = {"rc_transferred": "the RC transfer is complete and challans dated after handover have moved to Cars24",
            "refund": "the remaining refund has been sent to your bank account",
            "plan_refund": "the plan fee has been refunded to your bank account",
            "holdback_released": "the held amount has been released to your bank account",
            "warranty_fixed": "the repair is complete under warranty"}.get(proof["type"], "the issue is fixed")
    for p in c.execute("SELECT DISTINCT platform, post_id FROM complaint_post WHERE case_id=? GROUP BY platform", (case_id,)).fetchall():
        c.execute("""INSERT INTO reply (case_id, post_id, platform, body, kind, status, drafted_by, created_at)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (case_id, p["post_id"], p["platform"],
                   f"Update on case {case['case_ref']}: {what}. The reference is in your email and on your case page. "
                   f"Thank you for your patience.", "resolved", "draft", "agent", db.iso(db.now())))
    db.event(c, case_id, "reply_drafted", "replies", kind="resolved")


def approve(reply_id: int, approver: str = "cx-agent"):
    with db.tx() as c:
        r = c.execute("SELECT * FROM reply WHERE reply_id=?", (reply_id,)).fetchone()
        if not r or r["status"] != "draft":
            return False
        c.execute("UPDATE reply SET status='posted', approved_by=?, posted_at=? WHERE reply_id=?", (approver, db.iso(db.now()), reply_id))
        db.event(c, r["case_id"], "reply_posted", approver, platform=CHANNEL_NAME.get(r["platform"], r["platform"]), kind=r["kind"])
        return True
