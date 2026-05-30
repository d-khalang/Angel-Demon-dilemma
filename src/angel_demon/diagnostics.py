"""Small diagnostics for local setup checks."""

from __future__ import annotations

from dataclasses import dataclass

from angel_demon.config import Settings
from angel_demon.logging_config import get_logger

logger = get_logger("diagnostics")


@dataclass(frozen=True)
class ApiKeyDiagnostic:
    ok: bool
    message: str
    status_code: int | None = None
    error_type: str | None = None


async def check_openai_key(settings: Settings) -> ApiKeyDiagnostic:
    """Make a tiny authenticated request to distinguish auth vs quota errors."""
    if not settings.openai_api_key:
        logger.warning("openai_key_check_missing_key")
        return ApiKeyDiagnostic(
            ok=False,
            message="OPENAI_API_KEY is missing.",
            error_type="missing_api_key",
        )

    try:
        from openai import APIStatusError, AsyncOpenAI, AuthenticationError
    except ImportError:
        logger.exception("openai_key_check_missing_package")
        return ApiKeyDiagnostic(
            ok=False,
            message="The openai package is not installed in this environment.",
            error_type="missing_package",
        )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        await client.models.list()
    except AuthenticationError as exc:
        logger.warning("openai_key_check_auth_failed status_code=%s", exc.status_code)
        return ApiKeyDiagnostic(
            ok=False,
            message=(
                "The key was rejected as invalid, expired, revoked, or not authorized. "
                "Check for copied spaces, quotes, line breaks, or missing characters."
            ),
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )
    except APIStatusError as exc:
        logger.warning(
            "openai_key_check_api_status_error status_code=%s error_type=%s",
            exc.status_code,
            type(exc).__name__,
        )
        return ApiKeyDiagnostic(
            ok=False,
            message=str(exc),
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )
    except Exception as exc:
        logger.exception("openai_key_check_failed error=%s", exc)
        return ApiKeyDiagnostic(
            ok=False,
            message=str(exc),
            error_type=type(exc).__name__,
        )

    logger.info("openai_key_check_success model=%s", settings.openai_model)
    return ApiKeyDiagnostic(ok=True, message="The API key authenticated successfully.")
