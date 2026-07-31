"""Enterprise logging package.

Layered, config-driven logging for the whole platform (API + Celery workers).

Configuration precedence (lowest -> highest):
  1. Code defaults                         (LoggingConfig model)
  2. config/logging/logging.yaml           (application-level base)
  3. config/logging/environments/<env>.yaml(per-environment profile)
  4. config/logging/modules/*.yaml         (per-module / per-namespace rules)
  5. Environment variables                 (LOG_ENABLED / LOG_LEVEL / LOG_FORMAT)

The active environment (development | staging | production) selects the
profile in step 3, which is how "log differently in prod vs dev" is driven.

Public API:
  configure_logging()  — call once at process start (API factory + Celery signal)
  get_logger(name)     — obtain a bound structlog logger
  get_logging_config() — the resolved LoggingConfig (for diagnostics / tests)
"""

from app.core.logging.loader import get_logging_config
from app.core.logging.schema import LoggingConfig, LoggerRule
from app.core.logging.setup import configure_logging, get_logger

__all__ = [
    "configure_logging",
    "get_logger",
    "get_logging_config",
    "LoggingConfig",
    "LoggerRule",
]
