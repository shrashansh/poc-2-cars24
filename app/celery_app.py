"""
Celery mode (RUN_MODE=celery). Same functions as simple mode, run by Celery workers and scheduled by Celery beat.

  celery -A ccc.celery_app worker -Q ingest,nlp,sla -l info
  celery -A ccc.celery_app beat -l info

Queues: ingest (one fetch task per platform), nlp (process each post), sla (watchdog).
"""
from celery import Celery

from . import config

app = Celery("ccc", broker=config.REDIS_URL, backend=config.REDIS_URL)
app.conf.update(
    task_acks_late=True,                 # a crashed worker's task is re-delivered
    task_default_retry_delay=10,
    worker_prefetch_multiplier=1,
    task_routes={"ccc.fetch_platform": {"queue": "ingest"},
                 "ccc.process_payload": {"queue": "nlp"},
                 "ccc.sla_watchdog": {"queue": "sla"}},
    beat_schedule={
        **{f"fetch-{p}": {"task": "ccc.fetch_platform", "schedule": float(config.COLLECT_EVERY), "args": (p,)}
           for p in ["trustpilot", "google", "playstore", "appstore", "x", "consumercomplaints", "email"]},
        "sla-watchdog": {"task": "ccc.sla_watchdog", "schedule": float(config.SLA_EVERY)},
    },
)


@app.task(name="ccc.fetch_platform", bind=True, max_retries=3)
def fetch_platform_task(self, platform: str):
    from .agents.collector import fetch
    try:
        payloads = fetch(platform)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)
    for p in payloads:
        process_payload_task.delay(p)
    return len(payloads)


@app.task(name="ccc.process_payload", bind=True, max_retries=3)
def process_payload_task(self, payload: dict):
    from .pipeline import process_payload
    try:
        return process_payload(payload)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)


@app.task(name="ccc.sla_watchdog")
def sla_watchdog_task():
    from .agents.sla import run
    return run()
