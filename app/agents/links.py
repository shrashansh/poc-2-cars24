"""
Dedicated case links. One link per person per case: the same Trustpilot account posting three times about the
same problem gets the same link back. The URL carries only an opaque token; platform, account, post and case
are looked up server-side, so nothing personal sits in the link and nobody can edit it to reach another case.
"""
import hashlib
import json
import secrets
from datetime import timedelta

from .. import config, db
from . import enricher


def link_url(token: str) -> str:
    return f"{config.BASE_URL}/c/{token}"


def get_or_issue(c, case_id: str, post_id: str, identity_id: str, platform: str) -> str:
    row = c.execute("""SELECT token FROM tracked_link WHERE case_id=? AND identity_id=? AND status!='expired'
                       ORDER BY issued_at DESC LIMIT 1""", (case_id, identity_id)).fetchone()
    if row:
        return row["token"]
    token = secrets.token_urlsafe(16)
    now = db.now()
    c.execute("""INSERT INTO tracked_link (token, case_id, post_id, identity_id, platform, issued_at, expires_at)
                 VALUES (?,?,?,?,?,?,?)""",
              (token, case_id, post_id, identity_id, platform, db.iso(now), db.iso(now + timedelta(days=config.LINK_TTL_DAYS))))
    db.event(c, case_id, "link_issued", "links", platform=platform)
    return token


def context(token: str):
    return db.q1("""SELECT l.*, i.display_name, i.handle, i.status AS identity_state, c.case_ref, c.theme, c.status AS case_status,
                           c.owner_team, c.first_action_due, c.resolve_due, c.identity_status, c.priority, c.facts,
                           c.booking_ref, p.body, p.posted_at
                    FROM tracked_link l JOIN platform_identity i ON i.identity_id=l.identity_id
                    JOIN complaint_case c ON c.case_id=l.case_id JOIN complaint_post p ON p.post_id=l.post_id
                    WHERE l.token=?""", (token,))


def record_click(token: str):
    with db.tx() as c:
        row = c.execute("SELECT case_id, platform, first_click_at FROM tracked_link WHERE token=?", (token,)).fetchone()
        if not row:
            return
        c.execute("""UPDATE tracked_link SET click_count=click_count+1, first_click_at=COALESCE(first_click_at, ?),
                     status=CASE WHEN status='issued' THEN 'clicked' ELSE status END WHERE token=?""", (db.iso(db.now()), token))
        if not row["first_click_at"]:
            db.event(c, row["case_id"], "link_opened", "customer", platform=row["platform"])


def normalise_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    return "+91" + digits[-10:] if len(digits) >= 10 else raw


def phone_hash(phone: str) -> str:
    return hashlib.sha256((config.PHONE_SALT + phone).encode()).hexdigest()


def request_otp(token: str, raw_phone: str) -> str:
    """Send an OTP to the number (shown on screen in the POC; an SMS gateway in production).
    The answer is the same whether or not the number has bookings, so the page can't be used to probe numbers."""
    phone = normalise_phone(raw_phone)
    code = f"{secrets.randbelow(1_000_000):06d}"
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO otp_challenge (token, phone, code, expires_at, attempts) VALUES (?,?,?,?,0)",
                  (token, phone, code, db.iso(db.now() + timedelta(minutes=10))))
        c.execute("UPDATE tracked_link SET submitted_at=COALESCE(submitted_at, ?), status=CASE WHEN status IN ('issued','clicked') THEN 'submitted' ELSE status END WHERE token=?",
                  (db.iso(db.now()), token))
    return code


def check_otp(token: str, code: str):
    with db.tx() as c:
        ch = c.execute("SELECT * FROM otp_challenge WHERE token=?", (token,)).fetchone()
        if not ch or db.parse(ch["expires_at"]) < db.now() or ch["attempts"] >= 5:
            return None, "The code has expired. Ask for a new one."
        if ch["code"] != code.strip():
            c.execute("UPDATE otp_challenge SET attempts=attempts+1 WHERE token=?", (token,))
            return None, "That code doesn't match. Check the SMS and try again."
        return ch["phone"], None


def bookings_for(phone: str):
    return db.q("SELECT * FROM crm_booking WHERE phone=? ORDER BY booking_date DESC", (phone,))


def confirm(token: str, phone: str, booking_ref: str):
    """The customer picked their car. Identity is now confirmed for this case and for every open case of this account."""
    from .resolver import merge_customer_cases
    with db.tx() as c:
        link = c.execute("SELECT * FROM tracked_link WHERE token=?", (token,)).fetchone()
        booking = c.execute("SELECT * FROM crm_booking WHERE booking_ref=? AND phone=?", (booking_ref, phone)).fetchone()
        if not link or not booking:
            return False
        ph = phone_hash(phone)
        cust = c.execute("SELECT customer_id FROM customer WHERE crm_ref=?", (booking["crm_ref"],)).fetchone()
        customer_id = cust["customer_id"] if cust else secrets.token_hex(8)
        if not cust:
            c.execute("INSERT INTO customer VALUES (?,?,?,?)", (customer_id, booking["crm_ref"], ph, db.iso(db.now())))
        c.execute("UPDATE platform_identity SET customer_id=?, status='confirmed' WHERE identity_id=?", (customer_id, link["identity_id"]))
        c.execute("UPDATE complaint_case SET customer_id=?, identity_status='confirmed' WHERE case_id=?", (customer_id, link["case_id"]))
        enricher.attach_booking(c, link["case_id"], booking, "otp_link", 1.0, confirmed_by="otp")
        c.execute("UPDATE tracked_link SET verified_at=?, status='verified' WHERE token=?", (db.iso(db.now()), token))
        db.event(c, link["case_id"], "identity_confirmed", "customer", method="otp_link", booking=booking_ref)
        # every other open case from this platform account inherits the customer
        for row in c.execute("""SELECT DISTINCT case_id FROM complaint_post WHERE identity_id=? AND case_id!=?""",
                             (link["identity_id"], link["case_id"])).fetchall():
            c.execute("UPDATE complaint_case SET customer_id=?, identity_status='confirmed' WHERE case_id=? AND customer_id IS NULL",
                      (customer_id, row["case_id"]))
        merge_customer_cases(c, link["case_id"])
        return True
