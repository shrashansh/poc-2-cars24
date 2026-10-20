"""
Stage 2b agent: decide which case a post belongs to.

Order of evidence:
  1. a hard ID (reg no, booking or appointment ID) that is already on an open case, from any platform
  2. the same platform account, same kind of problem, case still open
  3. the account was verified earlier: that customer's open case for the same kind of problem
Otherwise a new case. Cross-channel look-alikes are only suggested, never merged automatically.
"""
import json
import secrets

from .. import db
from . import enricher
from .normalizer import similarity

OPEN = ("new", "routed", "in_progress")


def group(theme: str) -> str:
    return "RC" if theme in ("S3", "B3") else theme


def _open_cases(c):
    return c.execute(f"SELECT * FROM complaint_case WHERE status IN {OPEN}").fetchall()


def find_case(c, identity_id: str, theme: str, ids: dict):
    g = group(theme)
    open_cases = [r for r in _open_cases(c) if group(r["theme"]) == g]
    # 1. hard IDs
    for r in open_cases:
        if ids.get("reg_no") and r["vehicle_reg_no"] == ids["reg_no"]:
            return r["case_id"], "same registration number"
        for k in ("booking_id", "appointment_id"):
            if ids.get(k) and r["booking_ref"] == ids[k]:
                return r["case_id"], "same booking ID"
    booking, _, _ = enricher.booking_by_ids(c, ids)
    if booking:
        for r in open_cases:
            if r["crm_ref"] == booking["crm_ref"]:
                return r["case_id"], "same customer in Cars24 records"
    # 2. same account
    row = c.execute(f"""SELECT DISTINCT c.case_id, c.theme FROM complaint_case c JOIN complaint_post p ON p.case_id=c.case_id
                        WHERE p.identity_id=? AND c.status IN {OPEN}""", (identity_id,)).fetchall()
    for r in row:
        if group(r["theme"]) == g:
            return r["case_id"], "same account, same problem"
    # 3. verified account -> customer
    ident = c.execute("SELECT customer_id FROM platform_identity WHERE identity_id=?", (identity_id,)).fetchone()
    if ident and ident["customer_id"]:
        for r in open_cases:
            if r["customer_id"] == ident["customer_id"]:
                return r["case_id"], "verified customer"
    return None, None


def new_case(c, theme: str, role: str, summary: str, legal: bool, amount, ids: dict, opened_at: str) -> str:
    case_id = secrets.token_hex(8)
    ref = "C24-" + secrets.token_hex(3).upper()
    c.execute("""INSERT INTO complaint_case (case_id, case_ref, theme, role, owner_team, summary, legal_risk, amount_at_risk,
                 vehicle_reg_no, booking_ref, opened_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              (case_id, ref, theme, role, "Unassigned", summary, int(legal), amount, ids.get("reg_no"),
               ids.get("booking_id") or ids.get("appointment_id"), opened_at))
    db.event(c, case_id, "case_opened", "resolver", theme=theme)
    return case_id


def suggest_cross_channel(c, case_id: str, text: str, theme: str):
    me = c.execute("SELECT identity_id FROM complaint_post WHERE case_id=?", (case_id,)).fetchall()
    mine = {r["identity_id"] for r in me}
    for r in _open_cases(c):
        if r["case_id"] == case_id or group(r["theme"]) != group(theme):
            continue
        posts = c.execute("SELECT body, identity_id, platform FROM complaint_post WHERE case_id=?", (r["case_id"],)).fetchall()
        if not posts or {p["identity_id"] for p in posts} & mine:
            continue
        best = max(similarity(text, p["body"]) for p in posts)
        if best >= 0.3 and not c.execute("SELECT 1 FROM identity_match WHERE case_id=? AND other_case_id=?", (case_id, r["case_id"])).fetchone():
            for a, b in ((case_id, r["case_id"]), (r["case_id"], case_id)):
                c.execute("""INSERT INTO identity_match (case_id, other_case_id, method, confidence, evidence, created_at)
                             VALUES (?,?,?,?,?,?)""", (a, b, "cross_channel", round(best, 2),
                                                       json.dumps({"platforms": sorted({p["platform"] for p in posts})}), db.iso(db.now())))
            db.event(c, case_id, "possible_duplicate", "resolver", other=r["case_ref"], similarity=round(best, 2))


def merge(c, keep_id: str, drop_id: str, reason: str):
    keep = c.execute("SELECT * FROM complaint_case WHERE case_id=?", (keep_id,)).fetchone()
    drop = c.execute("SELECT * FROM complaint_case WHERE case_id=?", (drop_id,)).fetchone()
    for t in ("complaint_post", "tracked_link", "reply"):
        c.execute(f"UPDATE {t} SET case_id=? WHERE case_id=?", (keep_id, drop_id))
    c.execute("""UPDATE complaint_case SET priority=MIN(priority, ?), escalation_level=MAX(escalation_level, ?),
                 legal_risk=MAX(legal_risk, ?), amount_at_risk=COALESCE(amount_at_risk, ?),
                 vehicle_reg_no=COALESCE(vehicle_reg_no, ?), booking_ref=COALESCE(booking_ref, ?),
                 first_action_due=MIN(COALESCE(first_action_due, ?), COALESCE(?, first_action_due)) WHERE case_id=?""",
              (drop["priority"], drop["escalation_level"], drop["legal_risk"], drop["amount_at_risk"], drop["vehicle_reg_no"],
               drop["booking_ref"], drop["first_action_due"], drop["first_action_due"], keep_id))
    c.execute("UPDATE complaint_case SET status='merged', merged_into=? WHERE case_id=?", (keep_id, drop_id))
    db.event(c, keep_id, "case_merged", "resolver", absorbed=drop["case_ref"], reason=reason)
    db.event(c, drop_id, "merged_into", "resolver", into=keep["case_ref"], reason=reason)


def merge_customer_cases(c, case_id: str):
    """After a verification: other open cases of the same customer about the same problem collapse into this one."""
    me = c.execute("SELECT * FROM complaint_case WHERE case_id=?", (case_id,)).fetchone()
    if not me["crm_ref"]:
        return
    for r in _open_cases(c):
        if r["case_id"] != case_id and r["crm_ref"] == me["crm_ref"] and group(r["theme"]) == group(me["theme"]):
            merge(c, case_id, r["case_id"], "same customer, same problem")
