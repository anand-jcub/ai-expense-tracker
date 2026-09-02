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

    interval = int(os.environ.get("EXPENSE_MAIL_POLL_SECONDS", "900"))  # 15 min
    # First pass after a short delay so the HTTP server is up
    time.sleep(20)
    while True:
        try:
            users = get_all_usernames() or ["anand"]
            for user in users:
                reports = run_auto_import(user)
                for r in reports:
                    if r.get("ok") and r.get("inserted"):
                        logger.info(
                            "Auto-imported %s: +%s rows",
                            r.get("filename") or r.get("source"),
                            r.get("inserted"),
                        )
                    elif r.get("ok") is False:
                        logger.warning(
                            "Auto-import failed %s: %s",
                            r.get("filename"),
                            r.get("error"),
                        )
                    elif r.get("ok") and r.get("inserted") == 0:
                        logger.info(
                            "Mail poll: %s already imported (parsed=%s)",
                            r.get("filename"),
                            r.get("parsed"),
                        )
        except Exception:
            logger.exception("Mail poller error")
        time.sleep(max(60, interval))


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
