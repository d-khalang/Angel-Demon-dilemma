# Design Decisions

## Overall Architecture

- `ui/` contains Streamlit-specific code.
- `flow.py` controls the round lifecycle.
- `domain/` and `scoring.py` contain deterministic rules.
- `agents.py`, `judge.py`, and `memory.py` contain the AI use cases.
- `llm/` contains the provider abstraction and OpenAI implementation.
- `state.py` and `persistence/` handle SQLite.
- `app.py` creates dependencies such as the store and LLM provider and passes
  them explicitly, making the workflow testable without a dependency injection
  framework.

## Streaming and Structured Output

- Agent responses are streamed as plain text for immediate UI feedback.
- Judge and memory responses use structured calls and must match a schema before
  changing application state.
- JSON is not streamed because partial JSON is difficult to display, validate,
  and retry safely.

## Character Prompt Design

- Character prompts define values and goals, not only tone.
- Sunny argues from empathy, responsibility, conscience, and protection of
  others.
- Crowley argues from self-interest, survival, status, freedom, and personal
  gain.
- Both characters use the shared transcript and challenge each other directly.
- Anti-drift rules stop them from becoming neutral assistants. If their
  conclusions overlap, they still challenge each other's reasoning.

## Judge Design

- The judge evaluates rhetorical performance rather than moral correctness.
- The criteria are persuasiveness, character consistency, rebuttal quality, and
  engagement.
- The judge returns a Pydantic `Verdict` using strict structured output.
- Semantic checks run after schema validation because valid JSON can still
  contain contradictions. If the declared winner has the lower score, the
  scores are corrected.

## Adaptive Memory

One structured call updates the memory after the user chooses a side:

- The user's likely values and recent themes.
- Tactics that worked or failed for each character.
- Notes for adapting the next argument.

- Compact profiles, round facts, and a limited transcript excerpt control prompt
  size and token usage.
- The user's actual choice determines successful tactics. A character can win
  the judge verdict but still fail to convince the user.

## User Choice and Scoring

- Follow Sunny: `+15`
- Follow Crowley: `-15`
- Undecided: `0`
- Judge result: `+3` for Sunny or `-3` for Crowley
- The user's choice has more weight than the judge result.
- Alignment and promotion scores are recalculated from persisted rounds instead
  of incrementing counters, preventing double counting after revotes or reruns.

## Persistence

- SQLite stores important state instead of relying only on `st.session_state`.
- The database stores users, sessions, rounds, messages, model runs, and memory
  jobs, with foreign keys, cascading deletes, WAL mode, busy timeouts, and
  schema versioning.
- Round, session, audit, model, and job updates are written in one transaction
  and roll back together.
- Round numbers are allocated under a write lock so stale browser tabs cannot
  create the same round number.

## Durable Memory Jobs

- The user decision and a pending memory job are persisted before the slower
  memory call runs.
- The app claims the job before processing it and marks it complete afterward.
- Jobs left in `processing` after a restart return to `pending`.

## Revoting and Reopening

- Users can change a vote or reopen a debate. Reopening keeps the transcript but
  removes the verdict, choice, and score effect.
- An old decision cannot be safely subtracted from an LLM-generated profile
  that combines several rounds.
- Profiles are rebuilt from durable decided rounds using deterministic rules.
- Rebuilding can replace detailed generated notes with simpler ones.

## Fallbacks and Failures

- The OpenAI provider retries transient errors with exponential backoff.
- Structured judging and memory have deterministic fallbacks.
- If the initial character stream fails, the incomplete round is removed so the
  user can retry cleanly.
- `model_runs` records model, token, latency, streaming, and error information.

## Tests

- Full round lifecycle across database reloads.
- Interrupted stream cleanup.
- Concurrent and stale-client round creation.
- Transaction rollback.
- Durable memory job recovery.
- Revoting and reopening memory correction.
- OpenAI request and structured-output contracts.
- Complete Streamlit user journey.
- Default tests use `MockLLMProvider`; live-model checks run separately.

## Main Tradeoffs

- Streamlit reruns the whole script after interactions.
- Character calls are sequential; parallel Streamlit rendering is fragile.
- SQLite is used for the local prototype; a multi-instance service requires a
  production database.
- The local user system is not real authentication.
- Prompt safety rules are included; production still requires moderation.
