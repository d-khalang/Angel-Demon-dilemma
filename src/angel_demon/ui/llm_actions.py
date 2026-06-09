"""Shared execution and error presentation for Streamlit LLM actions."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import streamlit as st

from angel_demon.llm import LLMError
from angel_demon.logging_config import get_logger


def run_llm_action[T](
    action: Coroutine[Any, Any, T],
    *,
    log_event: str,
    session_id: str,
    user_message: str,
) -> T | None:
    try:
        return asyncio.run(action)
    except LLMError as exc:
        get_logger("app").exception(
            "%s session_id=%s error=%s",
            log_event,
            session_id,
            exc,
        )
        st.error(user_message)
        st.caption(str(exc))
        return None
