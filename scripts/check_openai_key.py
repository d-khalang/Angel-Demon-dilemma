from __future__ import annotations

import asyncio

from angel_demon.config import load_settings
from angel_demon.diagnostics import check_openai_key
from angel_demon.logging_config import setup_logging


async def main() -> None:
    settings = load_settings()
    setup_logging(settings)
    result = await check_openai_key(settings)
    print(f"ok: {result.ok}")
    print(f"status_code: {result.status_code}")
    print(f"error_type: {result.error_type}")
    print(f"message: {result.message}")


if __name__ == "__main__":
    asyncio.run(main())
