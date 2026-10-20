"""Simple mode: run the collectors and the SLA watchdog on background threads inside the web process."""
import logging
import threading
import time

from . import config, pipeline
from .agents import sla

log = logging.getLogger("ccc.scheduler")
_started = False


def _loop(name, every, fn):
    while True:
        try:
            fn()
        except Exception:
            log.exception("%s failed", name)
        time.sleep(every)


def start():
    global _started
    if _started or config.RUN_MODE != "simple":
        return
    _started = True
    threading.Thread(target=_loop, args=("collectors", config.COLLECT_EVERY, pipeline.collect_all), daemon=True).start()
    threading.Thread(target=_loop, args=("sla_watchdog", config.SLA_EVERY, sla.run), daemon=True).start()
    log.info("scheduler started: collect every %ss, SLA every %ss", config.COLLECT_EVERY, config.SLA_EVERY)
