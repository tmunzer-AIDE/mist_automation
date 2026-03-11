"""
Helpers for safe background task creation.
"""

import asyncio
from collections.abc import Coroutine

import structlog

logger = structlog.get_logger(__name__)


def create_background_task(coro: Coroutine, name: str | None = None) -> asyncio.Task:
    """Wrap asyncio.create_task with error logging on failure."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_task_exception)
    return task


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(
            "background_task_failed",
            task_name=task.get_name(),
            error=str(exc),
            exc_info=exc,
        )
