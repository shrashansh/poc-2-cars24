"""Flask app: team dashboard, case pages, the customer's dedicated case link, and a mock platform view."""
import json
import logging
import os

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

from . import actions, config, db, pipeline, scheduler, seed
from .agents import links, replies, sla
from .agents.router import LADDER, THEMES, label

PLATFORM_NAMES = {"trustpilot": "Trustpilot", "google": "Google", "playstore": "Play Store", "appstore": "App Store",
                  "x": "X", "consumercomplaints": "ConsumerComplaints.in", "email": "Email"}
STATUS_TEXT = {"new": "New", "routed": "Waiting for team", "in_progress": "In progress", "resolved": "Resolved", "merged": "Merged"}


def create_app(start_scheduler: bool = True) -> Flask:
    logging.basicConfig(level=logging.INFO)
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = config.SECRET_KEY
    seed.seed()
    if start_scheduler and os.environ.get("WERKZEUG_RUN_MAIN") != "false":
        scheduler.start()

    # ---------- template helpers ----------
    @app.template_filter("platform")
    def _platform(p):
        return PLATFORM_NAMES.get(p, p)

    @app.template_filter("theme_label")
    def _label(t):
        return label(t)

    @app.template_filter("ago")
    def _ago(ts):
        dt = db.parse(ts)
        if not dt:
            return ""
        s = (db.now() - dt).total_seconds()
        if s < 0:
            return "just now"
        for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
            if s >= n:
                return f"{int(s // n)}{unit} ago"
        return f"{int(s)}s ago"

    @app.template_filter("sla")
    def _sla(case):
        """Remaining first-action time in business hours (the demo clock compresses an hour into a few seconds)."""
        if case["status"] in ("resolved", "merged"):
            return ("done", "")
        if case["first_action_at"]:
            return ("ok", "First action taken")
        due = db.parse(case["first_action_due"])
        if not due:
            return ("ok", "")
        h = (due - db.now()).total_seconds() / config.SLA_SECONDS_PER_HOUR
        return ("late", f"Overdue {abs(h):.0f} h") if h < 0 else ("warn" if h < 4 else "ok", f"Due in {h:.0f} h")

    @app.template_filter("fromjson")
    def _fromjson(s):
        try:
            return json.loads(s or "{}")
        except ValueError:
            return {}

    @app.context_processor
    def _ctx():
        return {"STATUS_TEXT": STATUS_TEXT, "LADDER": LADDER, "config": config, "PLATFORM_NAMES": PLATFORM_NAMES}

    # ---------- team dashboard ----------
    def state_version():
        r = db.q1("SELECT COALESCE(MAX(event_id),0) AS v FROM case_event")
        return r["v"]

    @app.get("/")
    def dashboard():
        cases = db.q("""SELECT c.*, COUNT(p.post_id) AS posts, GROUP_CONCAT(DISTINCT p.platform) AS platforms,
                               MAX(p.posted_at) AS last_post
                        FROM complaint_case c LEFT JOIN complaint_post p ON p.case_id=c.case_id
                        WHERE c.status!='merged' GROUP BY c.case_id
                        ORDER BY CASE c.status WHEN 'resolved' THEN 1 ELSE 0 END, c.priority, c.first_action_due""")
        open_cases = [c for c in cases if c["status"] in ("new", "routed", "in_progress")]
        now = db.iso(db.now())
        posts_total = db.q1("SELECT COUNT(*) n FROM complaint_post")["n"]
        k = {
            "open": len(open_cases),
            "critical": sum(1 for c in open_cases if c["priority"] == 1),
            "overdue": sum(1 for c in open_cases if not c["first_action_at"] and c["first_action_due"] and c["first_action_due"] < now),
            "escalated": sum(1 for c in open_cases if c["escalation_level"] > 1),
            "posts": posts_total,
            "merged": posts_total - len([c for c in cases]),
            "confirmed": sum(1 for c in cases if c["identity_status"] == "confirmed"),
            "candidate": sum(1 for c in cases if c["identity_status"] == "candidate"),
            "cases": len(cases),
            "drafts": db.q1("SELECT COUNT(*) n FROM reply WHERE status='draft'")["n"],
            "ignored": db.q1("SELECT COUNT(*) n FROM ignored_post")["n"],
            "at_risk": sum((c["amount_at_risk"] or 0) for c in open_cases),
        }
        funnel = db.q1("""SELECT COUNT(*) issued, SUM(first_click_at IS NOT NULL) opened, SUM(submitted_at IS NOT NULL) submitted,
                                 SUM(verified_at IS NOT NULL) verified FROM tracked_link""")
        feed = db.q("""SELECT p.*, i.display_name, i.handle, c.case_ref FROM complaint_post p
                       JOIN platform_identity i ON i.identity_id=p.identity_id LEFT JOIN complaint_case c ON c.case_id=p.case_id
                       ORDER BY p.fetched_at DESC, p.posted_at DESC LIMIT 12""")
        teams = db.q("""SELECT owner_team, COUNT(*) n, SUM(priority=1) crit FROM complaint_case
                        WHERE status IN ('new','routed','in_progress') GROUP BY owner_team ORDER BY n DESC""")
        wm = db.q("SELECT * FROM source_watermark ORDER BY platform")
        pending_feed = db.q1("SELECT COUNT(*) n FROM mock_feed WHERE release_at > ?", (now,))["n"]
        return render_template("dashboard.html", cases=cases, k=k, funnel=funnel, feed=feed, teams=teams, wm=wm,
                               pending_feed=pending_feed, version=state_version(), themes=THEMES)

    @app.get("/api/state")
    def api_state():
        return jsonify(version=state_version())

    @app.post("/actions/collect")
    def act_collect():
        res = pipeline.collect_all()
        n = sum(1 for v in res.values() for r in v if r.get("status") in ("new", "edited", "queued"))
        flash(f"Collectors ran on all platforms: {n} new or edited posts processed.")
        return redirect(url_for("dashboard"))

    @app.post("/actions/sla")
    def act_sla():
        n = sla.run()
        flash(f"SLA watchdog ran: {n} case(s) escalated.")
        return redirect(url_for("dashboard"))

    @app.post("/actions/simulate")
    def act_simulate():
        platform = request.form.get("platform", "trustpilot")
        body = (request.form.get("body") or "").strip()
        if len(body) < 15:
            flash("Write at least a sentence for the complaint.")
            return redirect(url_for("dashboard") + "#simulate")
        user = (request.form.get("username") or "demo-user").strip()[:40]
        rating = request.form.get("rating")
        ext = seed.inject_post(platform, f"{platform}-u-{user.lower()}", user, body, int(rating) if rating else None)
        pipeline.collect(platform)
        post = db.q1("""SELECT c.case_ref FROM complaint_post p JOIN complaint_case c ON c.case_id=p.case_id
                        WHERE p.platform=? AND p.external_post_id=?""", (platform, ext))
        if post:
            flash(f"Collected from {PLATFORM_NAMES[platform]}, classified, routed and given a case link.")
            return redirect(url_for("case_page", ref=post["case_ref"]))
        flash("Collected. The post read as positive, so no case was opened." if config.RUN_MODE == "simple"
              else "Queued for the workers.")
        return redirect(url_for("dashboard"))

    @app.post("/actions/reset")
    def act_reset():
        seed.seed(reset=True)
        flash("Demo reset: mock platforms reloaded and the clock restarted.")
        return redirect(url_for("dashboard"))

    # ---------- case page (team view) ----------
    @app.get("/cases/<ref>")
    def case_page(ref):
        case = actions.case_by_ref(ref)
        if not case:
            abort(404)
        if case["status"] == "merged":
            into = db.q1("SELECT case_ref FROM complaint_case WHERE case_id=?", (case["merged_into"],))
            return redirect(url_for("case_page", ref=into["case_ref"]))
        posts = db.q("""SELECT p.*, i.display_name, i.handle, i.platform_user_id, i.status AS identity_state FROM complaint_post p
                        JOIN platform_identity i ON i.identity_id=p.identity_id WHERE p.case_id=? ORDER BY p.posted_at""", (case["case_id"],))
        versions = {p["post_id"]: db.q("SELECT * FROM post_version WHERE post_id=? ORDER BY version", (p["post_id"],)) for p in posts}
        events = db.q("SELECT * FROM case_event WHERE case_id=? ORDER BY event_id", (case["case_id"],))
        reps = db.q("SELECT * FROM reply WHERE case_id=? ORDER BY reply_id", (case["case_id"],))
        lk = db.q("SELECT * FROM tracked_link WHERE case_id=? ORDER BY issued_at", (case["case_id"],))
        matches = db.q("""SELECT m.*, b.name, b.model, b.city, b.kind, oc.case_ref AS other_ref FROM identity_match m
                          LEFT JOIN crm_booking b ON b.booking_ref=m.booking_ref
                          LEFT JOIN complaint_case oc ON oc.case_id=m.other_case_id
                          WHERE m.case_id=? AND (oc.status IS NULL OR oc.status!='merged') ORDER BY m.confidence DESC""", (case["case_id"],))
        booking = db.q1("SELECT * FROM crm_booking WHERE booking_ref=?", (case["booking_ref"],)) if case["booking_ref"] else None
        return render_template("case.html", case=case, posts=posts, versions=versions, events=events, replies=reps,
                               links=lk, matches=matches, booking=booking, link_url=links.link_url)

    @app.post("/cases/<ref>/first-action")
    def act_first(ref):
        flash("First action logged; the SLA clock stops escalating." if actions.first_action(ref) else "Already in progress.")
        return redirect(url_for("case_page", ref=ref))

    @app.post("/cases/<ref>/resolve")
    def act_resolve(ref):
        ok, msg = actions.resolve(ref)
        flash(msg)
        return redirect(url_for("case_page", ref=ref))

    @app.post("/cases/<ref>/simulate-fix")
    def act_fix(ref):
        flash("Demo: the team's fix is now recorded in Cars24's systems." if actions.simulate_fix(ref)
              else "No booking on this case yet. Confirm the customer first.")
        return redirect(url_for("case_page", ref=ref))

    @app.post("/replies/<int:rid>/approve")
    def act_approve(rid):
        r = db.q1("SELECT case_id FROM reply WHERE reply_id=?", (rid,))
        replies.approve(rid)
        ref = db.q1("SELECT case_ref FROM complaint_case WHERE case_id=?", (r["case_id"],))["case_ref"]
        flash("Reply approved and posted to the platform (mock).")
        return redirect(url_for("case_page", ref=ref))

    @app.post("/matches/<int:mid>/confirm")
    def act_match(mid):
        m = db.q1("SELECT case_id FROM identity_match WHERE match_id=?", (mid,))
        actions.confirm_match(mid)
        c = db.q1("SELECT case_ref, status, merged_into FROM complaint_case WHERE case_id=?", (m["case_id"],))
        if c["status"] == "merged":
            c = db.q1("SELECT case_ref FROM complaint_case WHERE case_id=?", (c["merged_into"],))
        flash("Match confirmed.")
        return redirect(url_for("case_page", ref=c["case_ref"]))

    # ---------- the customer's dedicated case link ----------
    @app.get("/c/<token>")
    def case_link(token):
        ctx = links.context(token)
        if not ctx:
            abort(404)
        links.record_click(token)
        verified_phone = session.get(f"v:{token}")
        bookings = links.bookings_for(verified_phone) if verified_phone else []
        timeline = db.q("""SELECT event_type, created_at, payload FROM case_event WHERE case_id=? AND event_type IN
                           ('case_opened','routed','first_action','escalated','identity_confirmed','resolved','reply_posted','case_merged')
                           ORDER BY event_id""", (ctx["case_id"],))
        return render_template("link.html", ctx=ctx, step=request.args.get("step", "start"), otp=request.args.get("otp"),
                               bookings=bookings, verified=ctx["status"] == "verified", timeline=timeline, err=request.args.get("err"))

    @app.post("/c/<token>/otp")
    def link_otp(token):
        if not links.context(token):
            abort(404)
        phone = request.form.get("phone", "")
        if sum(ch.isdigit() for ch in phone) < 10:
            return redirect(url_for("case_link", token=token, err="Enter the 10-digit mobile number you used with Cars24."))
        code = links.request_otp(token, phone)
        return redirect(url_for("case_link", token=token, step="otp", otp=code if config.DEMO_SHOW_OTP else None))

    @app.post("/c/<token>/verify")
    def link_verify(token):
        phone, err = links.check_otp(token, request.form.get("code", ""))
        if err:
            return redirect(url_for("case_link", token=token, step="otp", err=err))
        session[f"v:{token}"] = phone
        return redirect(url_for("case_link", token=token, step="pick"))

    @app.post("/c/<token>/confirm")
    def link_confirm(token):
        phone = session.get(f"v:{token}")
        if not phone:
            return redirect(url_for("case_link", token=token, err="Verify your number first."))
        links.confirm(token, phone, request.form.get("booking_ref", ""))
        return redirect(url_for("case_link", token=token, step="done"))

    # ---------- mock platform view (what the public sees) ----------
    @app.get("/platforms/<platform>")
    def platform_view(platform):
        if platform not in PLATFORM_NAMES:
            abort(404)
        now = db.iso(db.now())
        posts = db.q("""SELECT f.*, p.case_id FROM mock_feed f LEFT JOIN complaint_post p
                        ON p.platform=f.platform AND p.external_post_id=f.external_post_id
                        WHERE f.platform=? AND f.release_at<=? ORDER BY f.release_at DESC""", (platform, now))
        reps = {}
        for r in db.q("""SELECT r.*, p.external_post_id FROM reply r JOIN complaint_post p ON p.post_id=r.post_id
                         WHERE r.status='posted' AND r.platform=?""", (platform,)):
            reps.setdefault(r["external_post_id"], []).append(r)
        return render_template("platform.html", platform=platform, posts=posts, reps=reps, now=now)

    @app.get("/api/cases")
    def api_cases():
        rows = db.q("SELECT case_ref, theme, owner_team, priority, status, identity_status, escalation_level, first_action_due FROM complaint_case")
        return jsonify([dict(r) for r in rows])

    @app.get("/health")
    def health():
        return jsonify(ok=True, mode=config.RUN_MODE, llm=bool(config.OPENAI_API_KEY))

    return app


app = create_app(start_scheduler=os.environ.get("CCC_NO_SCHEDULER") != "1")
