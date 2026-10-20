# Cars24 · Complaint Command Center

A working proof of concept of an agent layer that collects Cars24 customer complaints from every public channel,
merges each person's posts into one case, routes the case to the team that owns it with an SLA, escalates when
nobody acts, and refuses to close a case until Cars24's own records show the problem is fixed.

## The problem

Cars24 customers complain in many places at once: Trustpilot, Google reviews, Play Store, App Store, X,
ConsumerComplaints.in and email. Today those posts are handled one by one, and that causes four failures:

- **One customer becomes many tickets.** The same seller posts on X, Google and email. Each post gets a different
  owner, a different reply and its own clock, and nobody sees the full picture or the true number of people affected.
- **Serious cases look like every other case.** A seller whose RC still has not been transferred 6 months after the
  sale, and who is now receiving challans for a car they no longer own, waits in the same queue as a complaint about
  spam calls. Posts that mention a lawyer, a legal notice or consumer court get no special handling.
- **Nobody owns the clock.** Complaints sit in a shared queue with no first-action deadline and no escalation, so
  the oldest and angriest cases are often the ones nobody has touched.
- **Cases are closed without proof.** An agent marks a case resolved and posts "we have resolved this" while the
  refund was never paid or the RC was never transferred. The customer posts again, angrier, and other buyers and
  sellers read it before they decide to trust Cars24.

## The solution

A pipeline of small agents. Each step is plain code that Cars24 controls; the LLM only reads the text.

1. **Collect.** One collector per platform pulls new and edited posts, with a watermark so nothing is read twice.
2. **Normalize.** Clean the text and mask personal data (phone numbers, emails).
3. **Classify.** Tag each post with a theme (seller RC transfer, money held after handover, hidden defects,
   hidden charges, and so on), the amount at stake, legal risk and a one-line summary. An OpenAI model does this
   when a key is set; a keyword classifier runs otherwise. Hard IDs (reg no, booking, appointment, ticket) are
   always pulled by regex.
4. **Merge.** Join a post to an existing case when it shares a hard ID with an open case (on any platform), comes
   from the same account about the same problem, or comes from a customer who verified earlier. Look-alike posts
   across channels are suggested, never merged automatically.
5. **Route.** A rules table, not the LLM, sets the owner team, priority and SLA. Legal threats and RC cases older
   than 6 months (or with challans on the seller) become critical with a 4-hour first-action clock, and legal
   threats add the Legal team.
6. **Escalate.** An SLA watchdog moves untouched cases up the ladder: team queue, team lead, city or category head,
   weekly CXO digest. Taking the first action stops the escalation.
7. **Confirm the customer.** Each complainant gets a dedicated case link. They enter their phone number and an OTP
   and pick their car, which ties the public post to a real booking without a long form.
8. **Proof before closing.** A case cannot be resolved until Cars24's records confirm the fix (refund paid, RC
   transferred, challan cleared).
9. **Reply.** The system drafts the public reply. A person approves it before it is posted.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then edit .env (see below)
python run.py                     # http://localhost:8000
python -m unittest discover -s tests -v   # end-to-end tests on the mock data
```

Settings are read from `.env` in the project root; real environment variables take priority over it. To use the
LLM classifier, set `OPENAI_API_KEY` in `.env`. `OPENAI_MODEL` changes the model (default `gpt-4o-mini`) and
`OPENAI_BASE_URL` points it at any OpenAI-compatible endpoint. Without a key the keyword classifier runs, so the
app works offline. The tests always run without the LLM.

## Deploy

- **Render:** push this folder to GitHub, then New > Blueprint > pick the repo (`render.yaml`). Set `BASE_URL`
  to the service URL so case links point to it, and `OPENAI_API_KEY` if you want the LLM classifier.
- **Railway / Fly / any Docker host:** `docker build -t ccc . && docker run -p 8000:8000 -e BASE_URL=https://your-url ccc`
- **Celery mode** (web + workers + beat + Redis): `RUN_MODE=celery docker compose --profile celery up`

## Demo walkthrough

The mock platforms are timed from app start: 12 posts are already up (one is a 5-star review), and 7 more arrive
over the next ~18 minutes, plus one edited review (an X post with a reg no, a third post from a repeat reviewer,
a legal threat, a Hinglish complaint and more). Press **Reset demo** right before you start.

1. **Dashboard.** 11 complaints became 10 cases: the buyer who posted twice is one case, and their third post
   (about 2 minutes in) joins it too. Critical cases (legal threat, RC 6+ months) sit at the top with a 4-hour
   clock. The 5-star review was counted and left out.
2. **Escalation.** Wait a minute (1 SLA hour = 30 s in the demo). Untouched cases move from L1 Team queue to
   L2 Team lead and up. Open one and press **Take first action**: the escalation stops.
3. **Post one live.** In "Post a complaint", write something in Hinglish or mention a reg no like `DL3CAB4521`.
   It is collected, tagged, routed and given a case link while you watch.
4. **The case link.** Open the RC case from "Rocky Star" (Trustpilot) and click its case link. Enter
   `9811000001`; the OTP is filled in (no SMS in the POC); pick the Swift. The case is now confirmed. When the X
   post with `DL3CAB4521` arrives (about 4 minutes in), it lands on the same case.
5. **Proof before closing.** On the Selling Pro case (Play Store, `APPT-61873`), press **Resolve**: it refuses,
   because Cars24's records show no refund. Press **Demo: team fixes it**, then **Resolve**: it closes and drafts
   the public reply. **Approve and post**, then open the Play Store tab to see it as the public would.

Mock customer phones for the case link: `9811000001` to `9811000007` (see `app/mock_data.py`).

## Code map

| Agent | Code |
|---|---|
| Collector (per source), watermark | `app/agents/collector.py` |
| Normalizer + PII mask | `app/agents/normalizer.py` |
| Entity resolver, merge rules | `app/agents/resolver.py` |
| Classifier (LLM, rules fallback) | `app/agents/classifier.py` |
| Enricher, proof checks | `app/agents/enricher.py` |
| Router, SLA table, escalation ladder | `app/agents/router.py` |
| SLA watchdog | `app/agents/sla.py` |
| Reply drafter (human approves) | `app/agents/replies.py` |
| Dedicated case link + OTP | `app/agents/links.py`, `app/templates/link.html` |
| Celery jobs and beat schedule | `app/celery_app.py` |
| One post's full path | `app/pipeline.py` |

## What is mocked

| In the POC | In production |
|---|---|
| `mock_feed` table stands in for each platform's API | Trustpilot Business, Google Business Profile, Play/App Store, X APIs, or a Konnect Insights export |
| `crm_booking` table stands in for Cars24 records | Read-only booking, payment, RC (Form 29C/30) and challan lookups |
| OTP shown on screen | SMS gateway |
| Replies "posted" to the mock platform | Platform reply APIs or Konnect Insights |
| SQLite | PostgreSQL (same schema, `app/schema.sql`) |
| Demo clock (1 SLA hour = 30 s) | Real hours: set `SLA_SECONDS_PER_HOUR=3600` |

All names, numbers and registrations in the mock data are invented. The complaint patterns are modelled on
public Cars24 reviews from Oct 2025 to Oct 2026.
