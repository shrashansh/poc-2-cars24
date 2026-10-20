"""What the owning team does from the dashboard."""
import json

from . import db
from .agents import enricher, replies


def case_by_ref(ref: str):
    return db.q1("SELECT * FROM complaint_case WHERE case_ref=?", (ref,))


def first_action(ref: str, agent: str = "team-member"):
    with db.tx() as c:
        case = c.execute("SELECT * FROM complaint_case WHERE case_ref=?", (ref,)).fetchone()
        if not case or case["status"] not in ("routed", "new"):
            return False
        c.execute("UPDATE complaint_case SET status='in_progress', first_action_at=? WHERE case_id=?", (db.iso(db.now()), case["case_id"]))
        db.event(c, case["case_id"], "first_action", agent, team=case["owner_team"])
        return True


def resolve(ref: str, agent: str = "team-member") -> tuple[bool, str]:
    case = case_by_ref(ref)
    if not case:
        return False, "Case not found."
    proof = enricher.proof_for(case)
    if not proof:
        return False, ("Cars24's records don't show the fix yet (no refund reference, RTO acknowledgement or job card), "
                       "so the case stays open.")
    with db.tx() as c:
        c.execute("UPDATE complaint_case SET status='resolved', resolved_at=?, resolution_proof=?, first_action_at=COALESCE(first_action_at, ?) WHERE case_id=?",
                  (db.iso(db.now()), json.dumps(proof), db.iso(db.now()), case["case_id"]))
        db.event(c, case["case_id"], "resolved", agent, proof=proof)
        replies.draft_resolution(c, case["case_id"], proof)
    return True, "Resolved with proof from Cars24's records. A closing reply is drafted for approval."


def confirm_match(match_id: int, agent: str = "team-member"):
    from .agents.resolver import merge_customer_cases
    with db.tx() as c:
        m = c.execute("SELECT * FROM identity_match WHERE match_id=?", (match_id,)).fetchone()
        if not m:
            return False
        if m["method"] == "cross_channel":
            from .agents.resolver import merge
            keep, drop = sorted([m["case_id"], m["other_case_id"]],
                                key=lambda cid: c.execute("SELECT opened_at FROM complaint_case WHERE case_id=?", (cid,)).fetchone()["opened_at"])
            merge(c, keep, drop, "confirmed by agent as the same customer")
            c.execute("UPDATE identity_match SET confirmed_by=?, confirmed_at=? WHERE match_id=?", (agent, db.iso(db.now()), match_id))
            return True
        b = c.execute("SELECT * FROM crm_booking WHERE booking_ref=?", (m["booking_ref"],)).fetchone()
        enricher.attach_booking(c, m["case_id"], b, m["method"], m["confidence"], confirmed_by=agent)
        c.execute("UPDATE identity_match SET confirmed_by=?, confirmed_at=? WHERE match_id=?", (agent, db.iso(db.now()), match_id))
        c.execute("UPDATE complaint_case SET identity_status='confirmed' WHERE case_id=?", (m["case_id"],))
        db.event(c, m["case_id"], "identity_confirmed", agent, method=m["method"], booking=m["booking_ref"])
        merge_customer_cases(c, m["case_id"])
        return True


def simulate_fix(ref: str) -> bool:
    case = case_by_ref(ref)
    if not case or not case["booking_ref"]:
        return False
    ok = enricher.simulate_ops_fix(case["booking_ref"])
    if ok:
        with db.tx() as c:
            db.event(c, case["case_id"], "ops_updated_records", "demo")
    return ok
