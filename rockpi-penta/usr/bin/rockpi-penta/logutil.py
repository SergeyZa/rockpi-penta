#!/usr/bin/env python3
import logging


APP_LOGGER_NAME = 'rockpi-penta'


def _normalize_level(level):
    if isinstance(level, str):
        level = level.strip().upper()
    if level in ('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'):
        return level
    return 'INFO'


def setup_logging(level='INFO'):
    level_name = _normalize_level(level)
    app_logger = logging.getLogger(APP_LOGGER_NAME)

    if not app_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt='%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        app_logger.addHandler(handler)
        app_logger.propagate = False

    app_logger.setLevel(getattr(logging, level_name))
    return app_logger


def get_logger(name=None):
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    if not app_logger.handlers:
        setup_logging()  # first call only: add handler with default INFO level
    if not name:
        return app_logger
    return logging.getLogger(f'{APP_LOGGER_NAME}.{name}')
