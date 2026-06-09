# Angel vs Demon

Angel vs Demon is a moral dilemma debate app. The user submits a dilemma, then Sunny the angel and Crowley the demon compete to persuade them. Each round has streamed character arguments, a structured judge verdict, an alignment score, and a promotion race.

## Features

- Sunny and Crowley have distinct prompts, personalities, and goals.
- Character responses stream as natural text.
- The judge uses structured JSON output to choose a winner, score the debate, and extract persuasion tactics.
- The user chooses which side to follow, shifting alignment toward Heaven or Hell.
- Agent memory adapts future arguments based on what worked.
- Local user profiles keep sessions, rounds, messages, and model-run metadata separated.

## Run Locally

Requirements:

- Python 3.12+
- An OpenAI API key for live AI responses

### Windows PowerShell

Run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Open `.env` and replace `sk-your-key-here` with your OpenAI API key. The other
values can remain unchanged.

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### macOS or Linux

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install -e .
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, then run:

```bash
./.venv/bin/python -m streamlit run app.py
```

Streamlit prints the local URL, normally `http://localhost:8501`. The database
and log directories are created automatically.

To explore the UI without API calls, set `LLM_PROVIDER=mock` in `.env`.

## Architecture

The app is split into clear layers while keeping stable top-level entry points:

- `app.py`: Streamlit application setup and dependency wiring.
- `src/angel_demon/ui/`: Streamlit rendering, session context, and user actions.
- `src/angel_demon/flow.py`: Round lifecycle and workflow orchestration.
- `src/angel_demon/domain/`: Pure round-state and deterministic memory rules.
- `src/angel_demon/agents.py`: Sunny and Crowley prompt construction.
- `src/angel_demon/judge.py`: Structured verdict generation and fallback scoring.
- `src/angel_demon/memory.py`: LLM-backed adaptive memory orchestration.
- `src/angel_demon/llm/`: Provider contracts, OpenAI adapter, deterministic mock, and streaming utilities.
- `src/angel_demon/state.py`: Transaction ownership and the public SQLite store API.
- `src/angel_demon/persistence/`: SQLite schema, record conversion, and write helpers.
- `src/angel_demon/models.py`: Validated domain and structured-output models.
- `src/angel_demon/scoring.py`: Alignment and promotion scoring.

Character calls produce streamed plain text only. Structured data is created in separate judge and memory calls. This avoids brittle mixed text/JSON parsing while still demonstrating streaming UX and structured-output reliability.

The package boundaries keep UI, external providers, persistence, and pure domain
rules independently reviewable. Existing imports such as
`from angel_demon.llm import OpenAIProvider` remain stable through the package
facade.

A full explanation of the reasoning behind each architectural and engineering choice is in [docs/design-decisions.md](docs/design-decisions.md).

## Engineering Notes

The repo includes reusable project skills under `docs/skills/`:

- `python-sqlite-modern`: current Python `sqlite3` best practices used in this project, including Python 3.12+ `autocommit` behavior, explicit connection closing, foreign-key enforcement, WAL mode, and busy timeouts.
- `openai-responses-streaming`: OpenAI Responses API streaming guidance, including how to read final streamed usage from `response.completed` without using Chat Completions-only `stream_options.include_usage`.

## Database

SQLite is used for the prototype:

- `users`: local user profiles for separating sessions without requiring auth.
- `sessions`: per-user alignment and compact user/agent profiles.
- `rounds`: full structured round snapshots.
- `messages`: flat transcript history for replay/debugging.
- `model_runs`: model, latency, token estimates, streaming flag, and error metadata.
- `memory_jobs`: durable pending/completed memory work so a rerun or restart does not lose it.

The current user model is deliberately local and unauthenticated, which is appropriate for this Streamlit prototype. It gives the database the same ownership shape a production system would need, while keeping login/session security out of scope. For production, this would move to PostgreSQL with JSONB columns, migrations, real authentication, authorization checks, and retention/deletion controls.

## Scoring

Alignment ranges from `-100` to `100`.

- Follow Sunny: `+15`
- Follow Crowley: `-15`
- Undecided: `0`
- Judge winner bonus: `+3` for Sunny or `-3` for Crowley

The promotion race counts user decisions, not just judge verdicts.

## Testing

Install the development dependencies first:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app.py src tests scripts
.\.venv\Scripts\python.exe -m mypy src app.py
```

The tests cover deterministic logic plus stateful workflow integration, stale-client
round allocation, transactional persistence, interrupted streams, OpenAI adapter
contracts, audit-log reconciliation, and a complete Streamlit user journey. The LLM
provider is mocked in the default test suite, so normal CI does not spend tokens.

Three live AI evaluations are available as an explicit, token-spending smoke test:

```powershell
$env:RUN_LIVE_EVALS=1
.\.venv\Scripts\python.exe -m pytest -q tests/evals
```

They require a configured OpenAI API key and are skipped by default.

## Logging And Debugging

The app logs to both the terminal and a rotating local log file:

```env
LOG_LEVEL=INFO
LOG_FILE=logs/angel_demon.log
LOG_LLM_PAYLOADS=false
```

Use `LOG_LEVEL=DEBUG` for more detailed connection and request tracing. Set `LOG_LLM_PAYLOADS=true` only when you intentionally want prompts and model outputs in the log file; leave it off for normal use because dilemmas may contain sensitive text.

Useful checks:

```powershell
.\.venv\Scripts\python.exe scripts/check_openai_key.py
```

The SQLite database also records transcripts and model-run metadata in `messages` and `model_runs`, so you can inspect both the application log and durable round history.

## Production Plan

To take this beyond a prototype:

- Replace Streamlit with a React/Next.js frontend and FastAPI backend.
- Use resumable server-sent events for debate streaming.
- Store users, sessions, profiles, and traces in PostgreSQL with migrations.
- Add authentication, authorization, rate limits, cost ceilings, and per-user deletion.
- Add OpenTelemetry traces and dashboard metrics for latency, cost, and failures.
- Build eval sets for character consistency, judge stability, safety, and prompt regressions.
- Add content moderation before and after model calls for high-risk dilemmas.

## Challenges And Tradeoffs

- Streaming and structured output are separated intentionally: streamed character prose is better UX, while judge/memory JSON is more reliable for state.
- Streamlit parallel streaming is fragile, so the prototype streams sequentially.
- Memory is compact and profile-based instead of storing every past token in prompt context.
- SQLite is enough for a local prototype, but production needs proper user isolation and migrations.
