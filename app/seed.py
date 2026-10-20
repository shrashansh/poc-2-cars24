"""Create tables and load the mock platforms + mock Cars24 records, timed relative to app start."""
from datetime import timedelta

from . import db
from .mock_data import POSTS, crm_rows


def seed(reset: bool = False):
    db.init_schema()
    if reset:
        with db.tx() as c:
            for t in ["mock_feed", "crm_booking", "customer", "platform_identity", "complaint_case", "complaint_post",
                      "post_version", "identity_match", "tracked_link", "otp_challenge", "reply", "case_event",
                      "source_watermark", "ignored_post", "meta"]:
                c.execute(f"DELETE FROM {t}")
    if db.q1("SELECT value FROM meta WHERE key='epoch'"):
        return False
    epoch = db.now()
    with db.tx() as c:
        c.execute("INSERT INTO meta VALUES ('epoch', ?)", (db.iso(epoch),))
        for p in POSTS:
            edit_at = db.iso(epoch + timedelta(minutes=p["edit_min"])) if p.get("edit_min") is not None else None
            c.execute("""INSERT INTO mock_feed (platform, external_post_id, user_id, handle, display_name, title, body,
                         rating, release_at, edit_body, edit_rating, edit_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (p["platform"], p["external_post_id"], p["user_id"], p.get("handle"), p.get("display_name"),
                       p.get("title"), p["body"], p.get("rating"), db.iso(epoch + timedelta(minutes=p["release_min"])),
                       p.get("edit_body"), p.get("edit_rating"), edit_at))
        for b in crm_rows():
            c.execute("""INSERT INTO crm_booking (booking_ref, crm_ref, phone, name, kind, model, reg_no, city, hub,
                         booking_date, facts) VALUES (:booking_ref,:crm_ref,:phone,:name,:kind,:model,:reg_no,:city,
                         :hub,:booking_date,:facts)""", b)
    return True


def inject_post(platform: str, user_id: str, display_name: str, body: str, rating: int | None, title: str | None = None) -> str:
    """'Simulate a complaint': the post appears on the mock platform now; the next collector run picks it up."""
    import secrets
    ext = f"{platform[:2]}-live-{secrets.token_hex(3)}"
    with db.tx() as c:
        c.execute("""INSERT INTO mock_feed (platform, external_post_id, user_id, handle, display_name, title, body, rating,
                     release_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                  (platform, ext, user_id, user_id if platform == "x" else None, display_name, title, body, rating,
                   db.iso(db.now())))
    return ext
