from __future__ import annotations

import logging
import sys

from utils import normalize_log_level


def setup_logger(log_level: str, debug: bool) -> logging.Logger:
    logger = logging.getLogger("udp_relay")
    logger.propagate = False

    level_name = normalize_log_level(log_level, debug)
    logger.setLevel(getattr(logging, level_name))

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(getattr(logging, level_name))
        return logger

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(getattr(logging, level_name))
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
