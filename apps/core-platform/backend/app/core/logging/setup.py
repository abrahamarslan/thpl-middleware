"""Apply the resolved LoggingConfig to structlog + stdlib logging.

Pipeline: structlog -> stdlib root handler -> stdout.
  - JSON renderer in staging/production (Loki-friendly), console in dev.
  - request_id / trace_id arrive via contextvars (middleware) on every line.
  - per-module enable/level is enforced through the stdlib logger HIERARCHY:
    setting 'app.zoho' to DEBUG (or disabling it) governs every 'app.zoho.*'
    child automatically — the idiomatic, zero-overhead mechanism.

Containers log to stdout only; Alloy tails Docker logs into Loki. Never write
log files inside containers.
"""

import logging
import sys

import structlog

from app.core.logging.loader import get_logging_config
from app.core.logging.redaction import make_redaction_processor
from app.core.logging.schema import LoggingConfig

# Effectively "off": above CRITICAL so nothing is ever emitted.
_LOG_OFF = logging.CRITICAL + 10


def _shared_processors(config: LoggingConfig) -> list:
    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=config.utc),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        make_redaction_processor(config.redact_keys),
    ]
    if config.include_caller:
        processors.append(
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                }
            )
        )
    return processors


def _apply_logger_rules(config: LoggingConfig) -> None:
    """Enforce per-namespace rules via the stdlib logger hierarchy."""
    for name, rule in config.loggers.items():
        lg = logging.getLogger(name)
        lg.propagate = rule.propagate
        if not rule.enabled:
            # Hard off: clear handlers, stop propagation, raise level beyond CRITICAL.
            lg.handlers = []
            lg.propagate = False
            lg.setLevel(_LOG_OFF)
            lg.disabled = True
        else:
            lg.disabled = False
            if rule.level is not None:
                lg.setLevel(getattr(logging, rule.level))


def configure_logging() -> None:
    """Idempotent; safe to call from both the API factory and Celery signal."""
    config = get_logging_config()

    # Master switch: silence everything but keep a valid logging stack.
    if not config.enabled:
        root = logging.getLogger()
        root.handlers = [logging.NullHandler()]
        root.setLevel(_LOG_OFF)
        # Route structlog through stdlib (NOT the default PrintLogger, which
        # would write to stdout and bypass this) so the disable below gates it.
        structlog.configure(
            processors=[structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        # Drop all stdlib records up to and including CRITICAL → nothing emits.
        logging.disable(logging.CRITICAL)
        return

    logging.disable(logging.NOTSET)  # undo any previous master-off
    shared = _shared_processors(config)

    structlog.configure(
        processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.dev.ConsoleRenderer()
        if config.format == "console"
        else structlog.processors.JSONRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        foreign_pre_chain=shared,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, config.level))

    _apply_logger_rules(config)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
