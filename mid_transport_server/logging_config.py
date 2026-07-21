from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import LoggingSettings


def configure_logging(settings: LoggingSettings) -> None:
    level_name = settings.level.upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if settings.file:
        log_file = Path(settings.file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
