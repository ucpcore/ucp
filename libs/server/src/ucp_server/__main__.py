"""Entry point: ``ucp-server`` (or ``python -m ucp_server``).

All configuration comes from the environment; see README for the full table.
Uvicorn handles SIGINT/SIGTERM for a graceful shutdown.
"""
from __future__ import annotations

import logging
import sys

from .config import ConfigError, load_settings
from .logging_setup import configure_logging


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"ucp-server: {exc}", file=sys.stderr)
        return 2

    configure_logging(json_logs=settings.log_json, level=settings.log_level)
    logger = logging.getLogger("ucp_server")
    logger.info(
        "ucp-server starting on %s:%s (role=%s, multi_tenant=%s)",
        settings.host,
        settings.port,
        settings.server_role,
        settings.multi_tenant,
    )
    from .auth import auth_required
    from .token_store import get_token_store

    token_store = get_token_store(settings)
    if auth_required(settings, token_store):
        modes = []
        if settings.api_key:
            modes.append("service API key")
        if token_store.has_active_tokens():
            modes.append("personal tokens")
        logger.info("authentication: enabled (%s)", ", ".join(modes))
    else:
        logger.warning(
            "authentication: DISABLED — set UCP_SERVER_API_KEY or create personal "
            "tokens before exposing this server beyond localhost"
        )
    if settings.cache_ttl > 0:
        logger.info("cache: %s (ttl %ss)", settings.cache_dir, settings.cache_ttl)
    else:
        logger.info("cache: disabled (UCP_CACHE_TTL=0)")

    import uvicorn

    from .app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,  # keep our logging configuration
        timeout_graceful_shutdown=10,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
