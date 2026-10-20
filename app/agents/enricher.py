"""
Stage 5 agent: read-only lookups in Cars24's records (mocked here as crm_booking).
Attaches facts to the case, proposes identity matches, and checks proof before a case can close.
"""
import json

from .. import db

MODEL_WORDS = ["swift", "kwid", "creta", "venue", "baleno", "i20", "i10", "wagon r", "slavia", "nexon"]


def booking_by_ids(c, ids: dict):
    for key in ("booking_id", "appointment_id"):
        if ids.get(key):
            row = c.execute("SELECT * FROM crm_booking WHERE booking_ref=?", (ids[key],)).fetchone()
            if row:
                return row, "text_id", 0.97
    if ids.get("reg_no"):
        row = c.execute("SELECT * FROM crm_booking WHERE reg_no=?", (ids["reg_no"],)).fetchone()
        if row:
            return row, "text_id", 0.95
    return None, None, 0


def fuzzy_candidates(c, text: str, role: str):
    """Identity ladder step 2: car model + city/hub + kind. A person confirms before it counts."""
    t = text.lower()
    out = []
    for b in c.execute("SELECT * FROM crm_booking"):
        score, why = 0.0, []
        model = (b["model"] or "").lower()
        if any(w in t and w in model for w in MODEL_WORDS):
            score += 0.45; why.append("model")
        if b["city"] and b["city"].lower() in t or (b["hub"] and b["hub"].lower() in t):
            score += 0.3; why.append("city/hub")
        if (role == "seller" and b["kind"] == "sell") or (role == "buyer" and b["kind"] == "buy"):
            score += 0.1; why.append("deal type")
        if score >= 0.55:
            out.append((b, round(score, 2), why))
    return sorted(out, key=lambda x: -x[1])[:3]


def amount_at_risk(facts: dict) -> float | None:
    if "refund" in facts:
        return facts["refund"].get("deducted")
    if "plan" in facts:
        return facts["plan"].get("fee")
    if "holdback" in facts:
        return facts["holdback"].get("amount")
    if "challans" in facts:
        return sum(ch["amount"] for ch in facts["challans"] if ch.get("after_handover"))
    return None


def attach_booking(c, case_id: str, booking, method: str, confidence: float, confirmed_by: str | None = None):
    facts = json.loads(booking["facts"] or "{}")
    case = c.execute("SELECT * FROM complaint_case WHERE case_id=?", (case_id,)).fetchone()
    status = "confirmed" if confirmed_by else ("candidate" if case["identity_status"] != "confirmed" else "confirmed")
    c.execute("""UPDATE complaint_case SET crm_ref=?, booking_ref=COALESCE(booking_ref, ?), vehicle_reg_no=COALESCE(vehicle_reg_no, ?),
                 facts=?, amount_at_risk=COALESCE(?, amount_at_risk), identity_status=? WHERE case_id=?""",
              (booking["crm_ref"], booking["booking_ref"], booking["reg_no"], json.dumps(facts),
               amount_at_risk(facts), status, case_id))
    exists = c.execute("SELECT 1 FROM identity_match WHERE case_id=? AND booking_ref=? AND method=?",
                       (case_id, booking["booking_ref"], method)).fetchone()
    if not exists:
        c.execute("""INSERT INTO identity_match (case_id, crm_ref, booking_ref, method, confidence, evidence, confirmed_by,
                     confirmed_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                  (case_id, booking["crm_ref"], booking["booking_ref"], method, confidence,
                   json.dumps({"model": booking["model"], "city": booking["city"]}), confirmed_by,
                   db.iso(db.now()) if confirmed_by else None, db.iso(db.now())))
    db.event(c, case_id, "facts_attached", "enricher", booking=booking["booking_ref"], method=method,
             confidence=confidence, facts=list(facts.keys()))


def enrich(c, case_id: str, ids: dict, text: str, role: str):
    booking, method, conf = booking_by_ids(c, ids)
    if booking:
        attach_booking(c, case_id, booking, method, conf)
        return
    case = c.execute("SELECT identity_status FROM complaint_case WHERE case_id=?", (case_id,)).fetchone()
    if case["identity_status"] == "confirmed":
        return
    for b, score, why in fuzzy_candidates(c, text, role):
        if not c.execute("SELECT 1 FROM identity_match WHERE case_id=? AND booking_ref=?", (case_id, b["booking_ref"])).fetchone():
            c.execute("""INSERT INTO identity_match (case_id, crm_ref, booking_ref, method, confidence, evidence, created_at)
                         VALUES (?,?,?,?,?,?,?)""",
                      (case_id, b["crm_ref"], b["booking_ref"], "fuzzy_record", score, json.dumps({"matched_on": why}),
                       db.iso(db.now())))
            db.event(c, case_id, "candidate_match", "enricher", booking=b["booking_ref"], score=score, matched_on=why)
            c.execute("UPDATE complaint_case SET identity_status='candidate' WHERE case_id=? AND identity_status='unlinked'", (case_id,))


# ---- proof checks: a case can only be resolved when Cars24's own records show the fix ----
def proof_for(case) -> dict | None:
    if not case["booking_ref"]:
        return None
    c = db.conn()
    b = c.execute("SELECT facts FROM crm_booking WHERE booking_ref=?", (case["booking_ref"],)).fetchone()
    if not b:
        return None
    f = json.loads(b["facts"] or "{}")
    if f.get("rc", {}).get("status") == "transferred":
        return {"type": "rc_transferred", "rto_ack": f["rc"].get("rto_ack")}
    if f.get("refund", {}).get("status") == "refunded":
        return {"type": "refund", "bank_ref": f["refund"].get("bank_ref_final")}
    if f.get("plan", {}).get("refund_status") == "refunded":
        return {"type": "plan_refund", "bank_ref": f["plan"].get("bank_ref")}
    if f.get("holdback", {}).get("status") == "released":
        return {"type": "holdback_released", "bank_ref": f["holdback"].get("bank_ref")}
    if f.get("warranty", {}).get("status") == "fixed":
        return {"type": "warranty_fixed", "job_card": f["warranty"].get("job_card")}
    return None


def simulate_ops_fix(booking_ref: str):
    """Demo only: pretend the owning team did the work in Cars24's systems."""
    import secrets
    with db.tx() as c:
        b = c.execute("SELECT facts FROM crm_booking WHERE booking_ref=?", (booking_ref,)).fetchone()
        if not b:
            return False
        f = json.loads(b["facts"] or "{}")
        ref = "UTR" + secrets.token_hex(5).upper()
        if "rc" in f:
            f["rc"].update(status="transferred", rto_ack="RTO-ACK-" + secrets.token_hex(3).upper())
            for ch in f.get("challans", []):
                ch["moved_to"] = "Cars24"
        if "refund" in f:
            f["refund"].update(status="refunded", bank_ref_final=ref)
        if "plan" in f:
            f["plan"].update(refund_status="refunded", bank_ref=ref)
        if "holdback" in f:
            f["holdback"].update(status="released", bank_ref=ref)
        if "warranty" in f:
            f["warranty"].update(status="fixed", job_card="JC-" + secrets.token_hex(3).upper())
        c.execute("UPDATE crm_booking SET facts=? WHERE booking_ref=?", (json.dumps(f), booking_ref))
        return True
