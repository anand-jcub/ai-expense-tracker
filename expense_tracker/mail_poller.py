"""Background: check Gmail / inbox for statement PDFs and import them."""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_started = False


def _loop() -> None:
    from .auth import get_all_usernames
    from .mail_import import run_auto_import

    interval = int(os.environ.get("EXPENSE_MAIL_POLL_SECONDS", "300"))  # 5 min
    failures = 0
    time.sleep(20)
    while True:
        failed_this_pass = False
        try:
            users = get_all_usernames() or ["anand"]
            for user in users:
                reports = run_auto_import(user)
                try:
                    from .mail_bills import categorize_pending_from_mail

                    for hit in categorize_pending_from_mail(user):
                        if hit.get("ok") and hit.get("category"):
                            logger.info(
                                "From mail: %s -> %s",
                                hit.get("merchant"),
                                hit.get("category"),
                            )
                except Exception:
                    logger.exception("Bill mail categorise failed")
                for r in reports:
                    if r.get("ok") and r.get("inserted"):
                        logger.info(
                            "Auto-imported %s: +%s rows",
                            r.get("filename") or r.get("source"),
                            r.get("inserted"),
                        )
                    elif r.get("ok") is False:
                        failed_this_pass = True
                        logger.warning(
                            "Auto-import failed %s: %s",
                            r.get("filename"),
                            r.get("error"),
                        )
        except Exception:
            failed_this_pass = True
            logger.exception("Mail poller error")
        if failed_this_pass:
            failures = min(failures + 1, 6)
        else:
            failures = 0
        # Back off when Gmail/DNS is down so we do not hammer a dead network.
        wait = interval * (2 ** failures) if failures else interval
        time.sleep(max(60, min(wait, 1800)))


def start_mail_poller() -> None:
    global _started
    if _started:
        return
    if os.environ.get("EXPENSE_MAIL_POLL", "1").strip() in {"0", "false", "off"}:
        return
    _started = True
    t = threading.Thread(target=_loop, name="mail-poller", daemon=True)
    t.start()
    logger.info("Mail poller started (checks Gmail / inbox for statements)")
