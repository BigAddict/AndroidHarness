from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import pytest

from androidharness.logging_setup import LOGGER_NAME, setup_logging


@pytest.fixture(autouse=True)
def _isolate_androidharness_logger():
    """Each test gets a clean androidharness logger. Otherwise handlers
    attached by one test leak into the next, breaking the idempotency check
    among other things."""
    logger = logging.getLogger(LOGGER_NAME)
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    logger.handlers.clear()
    yield
    logger.handlers.clear()
    for h in saved_handlers:
        logger.addHandler(h)
    logger.setLevel(saved_level)


def test_setup_logging_attaches_rotating_file_handler(tmp_path):
    log_path = setup_logging(tmp_path)
    logger = logging.getLogger(LOGGER_NAME)
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str(log_path)


def test_setup_logging_attaches_stderr_stream_handler(tmp_path):
    """The terminal-live-feed handler — what makes the agent's work visible
    while it's happening, without tail -f on the log file."""
    setup_logging(tmp_path)
    logger = logging.getLogger(LOGGER_NAME)
    stream_handlers = [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, RotatingFileHandler)
        and getattr(h, "stream", None) is sys.stderr
    ]
    assert len(stream_handlers) == 1


def test_setup_logging_is_idempotent(tmp_path):
    """Re-invoking in the same process must not double-attach either handler.
    The runner / pytest can call setup_logging multiple times in a single
    session; duplicate handlers would print every line N times."""
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    setup_logging(tmp_path)

    logger = logging.getLogger(LOGGER_NAME)
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    stream_handlers = [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, RotatingFileHandler)
        and getattr(h, "stream", None) is sys.stderr
    ]
    assert len(file_handlers) == 1
    assert len(stream_handlers) == 1


def test_setup_logging_streams_log_records_to_stderr(tmp_path, capsys):
    """A live `_log.info(...)` call must land on stderr, where the user is
    watching, while the run is still in progress."""
    setup_logging(tmp_path)
    logging.getLogger("androidharness.test").info("hello from the agent")
    captured = capsys.readouterr()
    assert "hello from the agent" in captured.err
