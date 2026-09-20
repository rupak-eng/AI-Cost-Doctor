"""Background worker entrypoint: `python -m app.worker`.

Runs an in-process APScheduler. Phase 1 ships a heartbeat only; real jobs
(provider sync, anomaly scan, alert dispatch) land in Phases 4-6 and plug in
as additional scheduled functions here.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ai-cost-doctor.worker")


def heartbeat() -> None:
    log.info("worker heartbeat — scheduler alive (no jobs scheduled yet)")


def main() -> None:
    scheduler = BlockingScheduler()
    scheduler.add_job(heartbeat, "interval", seconds=60, id="heartbeat")
    log.info("starting worker scheduler")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("worker shutting down")


if __name__ == "__main__":
    main()
