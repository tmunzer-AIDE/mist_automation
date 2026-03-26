"""
Structured logging configuration using structlog.
"""

import logging
import sys
from datetime import datetime, timezone
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.config import settings


def add_app_context(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add application context to log events."""
    event_dict["app"] = settings.app_name
    event_dict["version"] = settings.app_version
    event_dict["environment"] = settings.environment
    return event_dict


def censor_sensitive_data(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Censor sensitive data in log events."""
    sensitive_keys = [
        "password",
        "token",
        "secret",
        "api_key",
        "authorization",
        "totp_secret",
        "backup_codes",
    ]

    for key in list(event_dict.keys()):
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            event_dict[key] = "***REDACTED***"

    return event_dict


class BroadcastHandler(logging.Handler):
    """Logging handler that broadcasts ALL log entries to the admin WS log viewer.

    Installed on the root logger so it captures both structlog-bound loggers
    and stdlib loggers (uvicorn, motor, third-party libs).
    """

    _SKIP_LOGGERS = {"app.core.websocket", "app.core.log_broadcaster"}

    # Keys from the structlog event_dict that are metadata, not extra fields
    _INTERNAL_KEYS = {
        "timestamp", "level", "event", "logger",
        "_record", "_from_structlog", "app", "version", "environment",
    }

    def emit(self, record: logging.LogRecord) -> None:
        if record.name in self._SKIP_LOGGERS:
            return

        try:
            import asyncio

            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No event loop (startup)

        try:
            from app.core.log_broadcaster import broadcast_log_entry

            # Build structured entry
            entry: dict[str, Any] = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname.lower(),
                "logger": record.name,
                "event": "",
                "extra": {},
            }

            # Structlog loggers store the event_dict in record.msg as a dict
            if isinstance(record.msg, dict):
                event_dict = record.msg
                entry["event"] = str(event_dict.get("event", ""))
                entry["timestamp"] = event_dict.get("timestamp", entry["timestamp"])
                for k, v in event_dict.items():
                    if k not in self._INTERNAL_KEYS:
                        try:
                            entry["extra"][k] = str(v)
                        except Exception:
                            entry["extra"][k] = "<unserializable>"
            else:
                # Stdlib logger — use the formatted message
                entry["event"] = record.getMessage()

            loop.create_task(broadcast_log_entry(entry))
        except Exception:
            pass  # Never break the logging chain


def configure_logging():
    """Configure structured logging for the application."""

    # Determine log rendering based on environment
    if settings.log_format == "json" or settings.is_production:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            add_app_context,
            censor_sensitive_data,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper()),
    )

    # Configure handler for stdout (console output)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=[
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
            ],
        )
    )

    # Get root logger and configure
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.addHandler(BroadcastHandler())
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Reduce noise from third-party libraries
    logging.getLogger("multipart").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str = __name__):
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)
