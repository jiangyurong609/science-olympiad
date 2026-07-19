from __future__ import annotations
import sys
import time
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.jobs import run_next_job


def drain() -> int:
    """Process queued jobs until the queue is empty, then exit.

    Used by scheduled runners (for example a Cloud Run Job) that invoke the
    worker periodically instead of keeping a poller alive.
    """
    processed = 0
    while True:
        with SessionLocal() as db:
            job = run_next_job(db)
        if job is None:
            return processed
        processed += 1


def main() -> None:
    settings = get_settings()
    while True:
        with SessionLocal() as db:
            job = run_next_job(db)
        if job is None:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    if "--drain" in sys.argv:
        print(f"Drained {drain()} job(s)")
    else:
        main()
