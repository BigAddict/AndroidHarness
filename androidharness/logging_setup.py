from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 5  # 1 active + 5 rolled = ~60 MB ceiling on logs/

LOGGER_NAME = "androidharness"


def setup_logging(logs_dir: Path) -> Path:
    """Attach a rotating file handler AND a stderr stream handler to the
    'androidharness' logger.

    The file is the durable record (~60 MB cap); stderr is the live feed so
    the user can watch the agent work without `tail -f`'ing the file.

    Idempotent: re-invoking in the same process won't double-attach either
    handler.

    Returns the path to the active log file.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "androidharness.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(_LOG_FORMAT)

    file_attached = any(
        isinstance(h, RotatingFileHandler)
        and getattr(h, "baseFilename", None) == str(log_path)
        for h in logger.handlers
    )
    if not file_attached:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Stream live to stderr so the terminal shows the agent's work as it
    # happens — the structured stdout summary (run dir / status / success /
    # reason / turns) stays uncluttered.
    stream_attached = any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, RotatingFileHandler)
        and getattr(h, "stream", None) is sys.stderr
        for h in logger.handlers
    )
    if not stream_attached:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return log_path


# Back-compat alias for callers that still import the old name. Remove once
# every internal caller has migrated.
setup_file_logging = setup_logging
