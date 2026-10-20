"""Stage 5b agent: the SLA watchdog. Untouched cases move up the escalation ladder."""
from .. import db
from .router import CRITICAL, LADDER, THEMES


def run() -> int:
    escalated = 0
    now = db.now()
    with db.tx() as c:
        rows = c.execute("""SELECT * FROM complaint_case WHERE status='routed' AND first_action_at IS NULL
                            AND first_action_due IS NOT NULL AND first_action_due < ? AND escalation_level < 4""",
                         (db.iso(now),)).fetchall()
        for r in rows:
            level = r["escalation_level"] + 1
            first_h = CRITICAL[0] if r["priority"] == 1 else THEMES.get(r["theme"], THEMES["O"])[2]
            c.execute("UPDATE complaint_case SET escalation_level=?, first_action_due=? WHERE case_id=?",
                      (level, db.iso(now + db.sla_delta(first_h)), r["case_id"]))
            db.event(c, r["case_id"], "escalated", "sla_watchdog", to=LADDER[level], level=level)
            escalated += 1
        for r in c.execute("""SELECT * FROM complaint_case WHERE status IN ('routed','in_progress') AND resolve_due < ?""",
                           (db.iso(now),)).fetchall():
            if not c.execute("SELECT 1 FROM case_event WHERE case_id=? AND event_type='resolve_overdue'", (r["case_id"],)).fetchone():
                db.event(c, r["case_id"], "resolve_overdue", "sla_watchdog")
    return escalated
