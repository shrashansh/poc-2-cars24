"""Stage 4 agent: a rules table Cars24 controls decides owner, priority and SLA. The LLM never routes."""
from .. import db

# code: (label, owner team, first-action SLA hours, resolve SLA hours, priority 1..4)
THEMES = {
    "S1": ("Seller · paid plan, no result or refund", "Seller pricing & plans", 48, 120, 3),
    "S2": ("Seller · valuation drop after inspection", "Seller pricing & plans", 48, 120, 3),
    "S3": ("Seller · RC transfer / challans after sale", "RTO / RC desk", 24, 168, 2),
    "S4": ("Seller · money held after handover", "Payments & refunds", 24, 72, 2),
    "B1": ("Buyer · hidden defects / accident", "Warranty & service", 24, 120, 2),
    "B2": ("Buyer · warranty and after-sales repair", "Warranty & service", 24, 120, 2),
    "B3": ("Buyer · RC transfer delay", "RTO / RC desk", 24, 168, 2),
    "B4": ("Buyer · charges, booking refund", "Payments & refunds", 24, 72, 2),
    "C": ("Challan-payment service", "Challan desk", 24, 72, 3),
    "X1": ("No response · spam calls · staff", "CX", 48, 72, 4),
    "O": ("Other / unclear", "CX triage", 48, 72, 4),
}
CRITICAL = (4, 72)   # first action, resolve (hours)
LADDER = {1: "Team queue", 2: "Team lead", 3: "City / category head", 4: "Weekly CXO digest"}


def label(theme: str) -> str:
    return THEMES.get(theme, THEMES["O"])[0]


def decide(theme: str, legal_risk: bool, months_waiting: int, has_challan_on_seller: bool):
    lbl, team, first_h, resolve_h, prio = THEMES.get(theme, THEMES["O"])
    critical = legal_risk or (theme in ("S3", "B3") and (months_waiting >= 6 or has_challan_on_seller))
    if critical:
        prio, (first_h, resolve_h) = 1, CRITICAL
        if legal_risk:
            team = f"{team} + Legal"
    return {"owner_team": team, "priority": prio, "first_h": first_h, "resolve_h": resolve_h, "critical": critical}


def route(c, case_id: str, cls: dict, actor="router"):
    """Set owner, priority and SLA clocks on a new case (or upgrade an existing one)."""
    case = c.execute("SELECT * FROM complaint_case WHERE case_id=?", (case_id,)).fetchone()
    challan = "challan" in (cls.get("summary", "") + " " + cls.get("_body", "")).lower() and cls["theme"] == "S3"
    d = decide(case["theme"], bool(cls.get("legal_risk")) or bool(case["legal_risk"]), int(cls.get("months_waiting") or 0), challan)
    now = db.now()
    if case["status"] == "new":
        c.execute("""UPDATE complaint_case SET owner_team=?, priority=?, status='routed', first_action_due=?, resolve_due=?
                     WHERE case_id=?""",
                  (d["owner_team"], d["priority"], db.iso(now + db.sla_delta(d["first_h"])),
                   db.iso(now + db.sla_delta(d["resolve_h"])), case_id))
        db.event(c, case_id, "routed", actor, team=d["owner_team"], priority=d["priority"],
                 first_action_sla_h=d["first_h"], critical=d["critical"])
    elif d["priority"] < case["priority"]:
        # a new post made the case more serious (legal threat, more months): upgrade and tighten the clock
        due = now + db.sla_delta(d["first_h"])
        c.execute("""UPDATE complaint_case SET owner_team=?, priority=?, first_action_due=MIN(COALESCE(first_action_due, ?), ?)
                     WHERE case_id=?""", (d["owner_team"], d["priority"], db.iso(due), db.iso(due), case_id))
        db.event(c, case_id, "priority_raised", actor, priority=d["priority"], team=d["owner_team"])
