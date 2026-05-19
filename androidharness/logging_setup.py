from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 5  # 1 active + 5 rolled = ~60 MB ceiling on logs/

LOGGER_NAME = "androidharness"


def setup_file_logging(logs_dir: Path) -> Path:
    """Attach a rotating file handler to the 'androidharness' logger.

    Idempotent: re-invoking in the same process won't double-attach.
    Returns the path to the active log file.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "androidharness.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)

    already_attached = any(
        isinstance(h, RotatingFileHandler)
        and getattr(h, "baseFilename", None) == str(log_path)
        for h in logger.handlers
    )
    if not already_attached:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)

    return log_path
