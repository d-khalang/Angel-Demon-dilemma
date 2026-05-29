"""Small diagnostics for local setup checks."""

from __future__ import annotations

from dataclasses import dataclass

from angel_demon.config import Settings


@dataclass(frozen=True)
class ApiKeyDiagnostic:
    ok: bool
    message: str
    status_code: int | None = None
    error_type: str | None = None


async def check_openai_key(settings: Settings) -> ApiKeyDiagnostic:
    """Make a tiny authenticated request to distinguish auth vs quota errors."""
    if not settings.openai_api_key:
        return ApiKeyDiagnostic(
            ok=False,
            message="OPENAI_API_KEY is missing.",
            error_type="missing_api_key",
        )

    try:
        from openai import APIStatusError, AsyncOpenAI, AuthenticationError
    except ImportError:
        return ApiKeyDiagnostic(
            ok=False,
            message="The openai package is not installed in this environment.",
            error_type="missing_package",
        )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        await client.models.list()
    except AuthenticationError as exc:
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
        return ApiKeyDiagnostic(
            ok=False,
            message=str(exc),
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )
    except Exception as exc:
        return ApiKeyDiagnostic(
            ok=False,
            message=str(exc),
            error_type=type(exc).__name__,
        )

    return ApiKeyDiagnostic(ok=True, message="The API key authenticated successfully.")
