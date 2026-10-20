"""
Stage 1 agent: one collector per platform. Pulls posts that are new or edited since the platform's watermark.
In the POC the "platform API" is the mock_feed table; in production each fetch_* calls the owner API
(Trustpilot Business, Google Business Profile, Play/App Store, X) or the existing Konnect Insights export.
"""
from datetime import timedelta

from .. import db

PLATFORMS = ["trustpilot", "google", "playstore", "appstore", "x", "consumercomplaints", "email"]
OVERLAP = timedelta(minutes=5)     # re-read a little behind the watermark; ingest is idempotent


def fetch(platform: str) -> list[dict]:
    wm_row = db.q1("SELECT last_seen FROM source_watermark WHERE platform=?", (platform,))
    epoch = db.parse(db.q1("SELECT value FROM meta WHERE key='epoch'")["value"])
    since = db.parse(wm_row["last_seen"]) - OVERLAP if wm_row and wm_row["last_seen"] else epoch - timedelta(days=30)
    now = db.now()
    out = []
    for r in db.q("""SELECT * FROM mock_feed WHERE platform=? AND release_at>? AND release_at<=? ORDER BY release_at""",
                  (platform, db.iso(since), db.iso(now))):
        out.append({**dict(r), "kind": "post", "posted_at": r["release_at"]})
    for r in db.q("""SELECT * FROM mock_feed WHERE platform=? AND edit_at IS NOT NULL AND edit_at>? AND edit_at<=?""",
                  (platform, db.iso(since), db.iso(now))):
        out.append({**dict(r), "kind": "edit", "posted_at": r["release_at"], "body": r["edit_body"],
                    "rating": r["edit_rating"], "edited_at": r["edit_at"]})
    with db.tx() as c:
        c.execute("""INSERT INTO source_watermark (platform, last_seen, last_run_at, fetched_total) VALUES (?,?,?,?)
                     ON CONFLICT(platform) DO UPDATE SET last_seen=excluded.last_seen, last_run_at=excluded.last_run_at,
                     fetched_total=fetched_total+?""", (platform, db.iso(now), db.iso(now), len(out), len(out)))
    return out
