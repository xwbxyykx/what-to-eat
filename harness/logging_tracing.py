"""structlog 结构化日志 + 可选 LangSmith tracing。"""
from __future__ import annotations

import logging

import structlog


def setup_logging(level: str = "INFO", langsmith: bool = False) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    if langsmith:
        try:
            from langsmith import Client  # noqa: F401
        except ImportError:
            structlog.get_logger("harness").warning(
                "langsmith requested but not installed (pip install langsmith)"
            )
        else:
            structlog.get_logger("harness").info("langsmith_enabled")
