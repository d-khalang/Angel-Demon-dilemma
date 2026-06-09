from angel_demon.config import load_settings, normalize_llm_provider


def test_load_settings_normalizes_quoted_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", '"mock"')

    settings = load_settings()

    assert settings.llm_provider == "mock"


def test_provider_normalization_handles_whitespace_and_case() -> None:
    assert normalize_llm_provider("  'OpenAI'  ") == "openai"
