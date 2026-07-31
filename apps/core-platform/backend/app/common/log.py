"""Logging facade — kept for import stability.

The enterprise logging implementation lives in app.core.logging (layered,
config-driven: application-level + per-environment + per-module YAML).
This module simply re-exports the public API so existing imports
(`from app.common.log import configure_logging`) keep working.
"""

from app.core.logging import configure_logging, get_logger, get_logging_config

__all__ = ["configure_logging", "get_logger", "get_logging_config"]
