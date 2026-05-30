"""Configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    llm_provider: str
    db_path: Path
    log_level: str
    log_file: Path
    log_llm_payloads: bool
    max_rounds_per_session: int
    agent_temperature: float
    judge_temperature: float
    memory_temperature: float


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4"),
        llm_provider=os.getenv("LLM_PROVIDER", "openai"),
        db_path=Path(os.getenv("DB_PATH", "data/state.db")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=Path(os.getenv("LOG_FILE", "logs/angel_demon.log")),
        log_llm_payloads=os.getenv("LOG_LLM_PAYLOADS", "false").lower()
        in {"1", "true", "yes", "on"},
        max_rounds_per_session=int(os.getenv("MAX_ROUNDS_PER_SESSION", "20")),
        agent_temperature=float(os.getenv("LLM_TEMPERATURE_AGENTS", "0.85")),
        judge_temperature=float(os.getenv("LLM_TEMPERATURE_JUDGE", "0.3")),
        memory_temperature=float(os.getenv("LLM_TEMPERATURE_MEMORY", "0.3")),
    )
