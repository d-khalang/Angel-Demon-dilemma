"""Application logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from angel_demon.config import Settings

LOGGER_NAME = "angel_demon"


def setup_logging(settings: Settings) -> logging.Logger:
    """Configure terminal and file logging once per process."""
    logger = logging.getLogger(LOGGER_NAME)
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(level)
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.log_file,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning(
            "log_file_unavailable log_file=%s error=%s; continuing with terminal logging only",
            settings.log_file,
            exc,
        )
    else:
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.info(
        "logging_configured log_level=%s log_file=%s",
        settings.log_level.upper(),
        settings.log_file,
    )
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
