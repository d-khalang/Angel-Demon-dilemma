from __future__ import annotations

import asyncio

from angel_demon.config import load_settings
from angel_demon.diagnostics import check_openai_key


async def main() -> None:
    result = await check_openai_key(load_settings())
    print(f"ok: {result.ok}")
    print(f"status_code: {result.status_code}")
    print(f"error_type: {result.error_type}")
    print(f"message: {result.message}")


if __name__ == "__main__":
    asyncio.run(main())
