# Angel vs Demon

Angel vs Demon is a moral dilemma debate app built for the Luxia AI Engineer assignment. The user submits a dilemma, then Sunny the angel and Crowley the demon compete to persuade them. Each round has streamed character arguments, a structured judge verdict, an alignment score, and a promotion race.

## Features

- Sunny and Crowley have distinct prompts, personalities, and goals.
- Character responses stream as natural text.
- The judge uses structured JSON output to choose a winner, score the debate, and extract persuasion tactics.
- The user chooses which side to follow, shifting alignment toward Heaven or Hell.
- Agent memory adapts future arguments based on what worked.
- Local user profiles keep sessions, rounds, messages, and model-run metadata separated.

## Setup

Requires Python 3.12+.

```bash
uv venv
uv pip install -e ".[dev]"
```

Create a local `.env` file:

```bash
cp .env.example .env
```

Then set:

```env
OPENAI_API_KEY=your_assignment_key
OPENAI_MODEL=gpt-5.4
```

Run the app:

```bash
streamlit run app.py
```

## Architecture

The app is intentionally small but split by responsibility:

- `app.py`: Streamlit UI and user interactions.
- `src/angel_demon/llm.py`: OpenAI Responses API provider with streaming and structured JSON helpers.
- `src/angel_demon/agents.py`: Sunny and Crowley prompt construction and streamed generation.
- `src/angel_demon/judge.py`: Structured debate verdict and fallback scoring.
- `src/angel_demon/memory.py`: User and agent adaptation profiles.
- `src/angel_demon/scoring.py`: Alignment and promotion scoring.
- `src/angel_demon/state.py`: SQLite persistence.
- `src/angel_demon/flow.py`: Round orchestration.

Character calls produce streamed plain text only. Structured data is created in separate judge and memory calls. This avoids brittle mixed text/JSON parsing while still demonstrating streaming UX and structured-output reliability.

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

```bash
pytest
ruff check
mypy src
```

The tests cover deterministic logic plus stateful workflow integration, stale-client
round allocation, transactional persistence, interrupted streams, OpenAI adapter
contracts, audit-log reconciliation, and a complete Streamlit user journey. The LLM
provider is mocked in tests so they do not spend tokens.

## Logging And Debugging

The app logs to both the terminal and a rotating local log file:

```env
LOG_LEVEL=INFO
LOG_FILE=logs/angel_demon.log
LOG_LLM_PAYLOADS=false
```

Use `LOG_LEVEL=DEBUG` for more detailed connection and request tracing. Set `LOG_LLM_PAYLOADS=true` only when you intentionally want prompts and model outputs in the log file; leave it off for normal use because dilemmas may contain sensitive text.

Useful checks:

```bash
python scripts/check_openai_key.py
```

The SQLite database also records transcripts and model-run metadata in `messages` and `model_runs`, so you can inspect both the application log and durable round history.

## Production Plan

To take this beyond a prototype:

- Replace Streamlit with a React/Next.js frontend and FastAPI backend.
- Use WebSockets or server-sent events for debate streaming.
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
