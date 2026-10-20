"""
process_payload: what happens to one post, in one transaction.
  normalize -> classify -> identity -> case (merge or open) -> enrich -> route -> dedicated link -> draft reply
Edited posts get a new version, are re-read, and can raise the case's priority.
"""
import json
import secrets

from . import db
from .agents import classifier, enricher, links, normalizer, replies, resolver, router
from .agents.collector import PLATFORMS, fetch


def _identity(c, p) -> str:
    row = c.execute("SELECT identity_id FROM platform_identity WHERE platform=? AND platform_user_id=?",
                    (p["platform"], p["user_id"])).fetchone()
    now = db.iso(db.now())
    if row:
        c.execute("UPDATE platform_identity SET display_name=?, handle=?, last_seen_at=? WHERE identity_id=?",
                  (p.get("display_name"), p.get("handle"), now, row["identity_id"]))
        return row["identity_id"]
    iid = secrets.token_hex(8)
    c.execute("""INSERT INTO platform_identity (identity_id, platform, platform_user_id, handle, display_name, first_seen_at, last_seen_at)
                 VALUES (?,?,?,?,?,?,?)""", (iid, p["platform"], p["user_id"], p.get("handle"), p.get("display_name"), now, now))
    return iid


def process_payload(p: dict) -> dict:
    title, body, rating = p.get("title"), p["body"], p.get("rating")
    chash = normalizer.content_hash(title, body, rating)
    existing = db.q1("SELECT * FROM complaint_post WHERE platform=? AND external_post_id=?", (p["platform"], p["external_post_id"]))
    if existing and existing["content_hash"] == chash:
        return {"status": "unchanged"}
    if db.q1("SELECT 1 FROM ignored_post WHERE platform=? AND external_post_id=?", (p["platform"], p["external_post_id"])) and not existing:
        return {"status": "ignored"}

    cls = classifier.classify(title, body, rating)       # network call stays outside the write lock
    cls["_body"] = body

    with db.tx() as c:
        if existing:                                       # ---- edited post
            v = existing["version"] + 1
            c.execute("INSERT OR IGNORE INTO post_version VALUES (?,?,?,?,?)",
                      (existing["post_id"], existing["version"], existing["body"], existing["rating"], db.iso(db.now())))
            c.execute("""UPDATE complaint_post SET body=?, body_masked=?, rating=?, content_hash=?, version=?, edited_at=?,
                         legal_risk=MAX(legal_risk, ?) WHERE post_id=?""",
                      (body, normalizer.mask(body), rating, chash, v, p.get("edited_at") or db.iso(db.now()),
                       int(cls["legal_risk"]), existing["post_id"]))
            case_id = existing["case_id"]
            db.event(c, case_id, "post_edited", "collector", platform=p["platform"], version=v,
                     rating_before=existing["rating"], rating_after=rating)
            if cls["legal_risk"]:
                c.execute("UPDATE complaint_case SET legal_risk=1 WHERE case_id=?", (case_id,))
            router.route(c, case_id, cls, actor="router")
            return {"status": "edited", "case_id": case_id}

        identity_id = _identity(c, p)
        if cls["theme"] == "P":
            c.execute("INSERT OR IGNORE INTO ignored_post VALUES (?,?,?,?)",
                      (p["platform"], p["external_post_id"], "positive", db.iso(db.now())))
            return {"status": "ignored"}

        case_id, reason = resolver.find_case(c, identity_id, cls["theme"], cls["ids"])
        if not case_id:
            case_id = resolver.new_case(c, cls["theme"], cls.get("role"), cls.get("summary"), cls["legal_risk"],
                                        cls.get("amount_inr"), cls["ids"], p["posted_at"])
            reason = "new case"
        elif cls["legal_risk"]:
            c.execute("UPDATE complaint_case SET legal_risk=1 WHERE case_id=?", (case_id,))

        post_id = secrets.token_hex(8)
        c.execute("""INSERT INTO complaint_post (post_id, platform, external_post_id, identity_id, case_id, title, body, body_masked,
                     rating, language, posted_at, content_hash, theme, role, amount_inr, extracted_ids, legal_risk, sentiment,
                     classifier, classifier_conf, fetched_at, processed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (post_id, p["platform"], p["external_post_id"], identity_id, case_id, title, body, normalizer.mask(body), rating,
                   cls["language"], p["posted_at"], chash, cls["theme"], cls.get("role"), cls.get("amount_inr"),
                   json.dumps(cls["ids"]), int(cls["legal_risk"]), cls.get("sentiment"), cls.get("classifier"),
                   cls.get("confidence"), db.iso(db.now()), db.iso(db.now())))
        db.event(c, case_id, "post_linked", "resolver", platform=p["platform"], reason=reason,
                 classifier=cls.get("classifier"), theme=cls["theme"])

        enricher.enrich(c, case_id, cls["ids"], f"{title or ''} {body}", cls.get("role") or "")
        router.route(c, case_id, cls)
        token = links.get_or_issue(c, case_id, post_id, identity_id, p["platform"])
        replies.draft_ack(c, case_id, post_id, token, p["platform"], p.get("display_name"))
        resolver.suggest_cross_channel(c, case_id, body, cls["theme"])
        return {"status": "new", "case_id": case_id, "reason": reason}


# ---- dispatch: simple mode runs inline; celery mode enqueues ----
def dispatch(payload: dict):
    from . import config
    if config.RUN_MODE == "celery":
        from .celery_app import process_payload_task
        process_payload_task.delay(payload)
        return {"status": "queued"}
    return process_payload(payload)


def collect(platform: str) -> list[dict]:
    return [dispatch(p) for p in fetch(platform)]


def collect_all() -> dict:
    return {pl: collect(pl) for pl in PLATFORMS}
