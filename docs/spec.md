# Angel vs Demon - Technical Specification

> Version: 2.0
> Updated: 2026-06-08
> Status: Implemented prototype

## 1. Purpose

Angel vs Demon is a conversational moral-dilemma game in which Sunny, an angel,
and Crowley, a demon, compete to persuade the user. A session contains multiple
debate rounds. Each round supports a live conversation, an AI judge verdict, a
user decision, alignment progression, and persistent strategy memory.

This document describes the current implementation. Architectural rationale is
covered in [design-decisions.md](design-decisions.md), implementation lessons in
[implementation-challenges.md](implementation-challenges.md), and the migration
plan in [production-strategy.md](production-strategy.md).

## 2. Product Requirements

The implementation addresses the assignment requirements as follows:

| Requirement | Implemented behavior |
|---|---|
| Two competing characters | Sunny and Crowley use separate persona, value, voice, and strategy instructions |
| Independent conversation | Each character generates an independent streamed response and receives the shared transcript |
| Character evolution | Compact user and agent profiles are updated after decided rounds and injected into later prompts |
| User alignment | Decisions and judge outcomes move a score between `-100` and `100` |
| Promotion competition | User conversions determine promotion wins; judge victories are tracked separately as laurels |
| Winner per interaction | The judge must select Sunny or Crowley and return structured scores and rationale |
| Conversation history | Full round transcripts and state transitions are persisted in SQLite |
| Basic UI | Streamlit provides chat, history, alignment, scores, sessions, users, decisions, reopening, and revoting |

The canonical demon name is `Crowley`.

## 3. Technology

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| UI | Streamlit |
| LLM API | OpenAI Responses API |
| Validation | Pydantic v2 |
| Persistence | SQLite using the Python standard library |
| Tests | pytest and pytest-asyncio |
| Static quality | Ruff and mypy |
| Packaging | `pyproject.toml` with a `src` layout |

The LLM provider is abstracted behind `LLMProvider`. The production
implementation is `OpenAIProvider`; tests use `MockLLMProvider`.

## 4. System Architecture

```text
Streamlit UI
  app.py
  src/angel_demon/ui/*
        |
        v
Round orchestration
  flow.py
        |
        +------------------+------------------+
        v                  v                  v
  agents.py / prompts.py  judge.py          memory.py
        |                  |                  |
        +------------------+------------------+
                           |
                           v
                     LLMProvider
                       llm.py

Round orchestration ---> scoring.py
Round orchestration ---> SessionStore ---> SQLite
Domain boundaries -----> models.py
Configuration ---------> config.py
```

### 4.1 Responsibility Boundaries

- `app.py` initializes configuration, logging, persistence, the LLM provider,
  and the top-level Streamlit view.
- `ui/` owns rendering, user actions, Streamlit session state, scrolling, and
  visual alignment state.
- `flow.py` owns round transitions, generation sequencing, persistence
  coordination, scoring normalization, judging, and memory-update orchestration.
- `agents.py` builds character requests and exposes generation helpers.
- `prompts.py` contains persona, judge, memory, and conversation prompt
  contracts.
- `judge.py` requests and validates structured verdicts and supplies a fallback.
- `memory.py` updates compact user and character strategy profiles.
- `scoring.py` contains pure deterministic scoring functions.
- `state.py` owns SQLite schema management and persistence.
- `models.py` defines validated domain and structured-output models.
- `llm.py` isolates OpenAI API calls, streaming, retries, usage extraction, and
  strict JSON-schema conversion.

## 5. Domain Model

### 5.1 Session

`SessionState` contains:

- A session and user identifier.
- All persisted rounds for that session.
- Current alignment.
- A compact `UserProfile`.
- A compact `AgentProfile` for Sunny.
- A compact `AgentProfile` for Crowley.
- Creation and update timestamps.

### 5.2 Round

A `Round` is the canonical durable conversation thread. It contains:

- Round number and original dilemma.
- Status: `active`, `judged`, or `decided`.
- Chronological `ConversationMessage` entries.
- Optional derived opening/rebuttal compatibility fields.
- Optional structured verdict.
- Optional user choice.
- Alignment delta.
- Timestamp.

The `conversation` list is authoritative. Opening and rebuttal fields are
derived from character messages for compatibility with older persisted data and
tests.

### 5.3 Conversation Message

Each message has:

- A speaker: user, system, Sunny, Crowley, or judge.
- Text content.
- An optional response target: both, Sunny, or Crowley.
- A timestamp.

System messages are persisted inside a round when the application asks the
characters to continue the debate.

### 5.4 Verdict

The judge returns:

- A required winner with no tie.
- A reason.
- Scores from 1 to 10 for both characters.
- Persuasion tactics detected for each character.
- A key debate moment.
- Optional safety notes.
- A flag indicating whether deterministic fallback judging was used.

### 5.5 Memory Profiles

`UserProfile` stores:

- Cautiously inferred values.
- Decision history.
- Estimated susceptibility to Sunny and Crowley.
- Recent themes.
- Compact notes.

Each `AgentProfile` stores:

- Successful tactics.
- Failed tactics.
- Opponent tactics to counter.
- Adaptation notes.
- Conversion wins and losses.

Tactical and value lists are deduplicated and capped. Conversion records are
derived from persisted user decisions rather than trusted as increment-only
counters.

## 6. Round Lifecycle

```text
New dilemma
    |
    v
ACTIVE
  user dilemma
  Sunny opening
  Crowley opening
  system requests first clash
  Sunny response
  Crowley response
    |
    +--> optional user follow-ups
    |      target both / Sunny / Crowley
    |
    +--> optional automatic continuation
    |
    v
JUDGED
  structured verdict
  scores and winner
    |
    +--> reopen -> ACTIVE
    |
    v
DECIDED
  user follows Sunny / Crowley / remains undecided
  alignment and promotion totals recomputed
  compact memory update runs
    |
    +--> revote -> DECIDED with recomputed totals
    +--> reopen -> ACTIVE with verdict and choice cleared
    +--> start next dilemma
```

### 6.1 Start

Starting a round:

1. Validates the dilemma.
2. Creates and immediately persists an active `Round`.
3. Adds the user's dilemma to the transcript.
4. Streams Sunny's response.
5. Streams Crowley's response.
6. Adds a system instruction requesting a direct first clash.
7. Streams a second response from Sunny and Crowley.

Sequential generation is intentional because Streamlit cannot reliably render
two simultaneous token streams in the same rerun model.

### 6.2 Continue

During an active round, the user can:

- Address both characters.
- Address Sunny only.
- Address Crowley only.
- Ask the agents to continue without additional user text.

Each responding character receives the live transcript and is instructed to
answer the latest context while challenging the opponent's relevant point.

### 6.3 Judge

Finalizing sends the full active-round transcript to the judge. The judge
evaluates rhetorical effectiveness using:

- Persuasiveness: 35%.
- Character consistency: 25%.
- Rebuttal quality: 20%.
- Engagement: 20%.

The judge must select a winner. The output is validated against `Verdict` using
strict structured output. Equal scores are adjusted so that the declared winner
has the higher score.

If judging fails after provider retries, a deterministic fallback alternates the
winner by round number and marks the verdict as a fallback.

### 6.4 Decide

The user chooses one of:

- Follow Sunny.
- Follow Crowley.
- Undecided.

The choice is persisted before the slower memory update. This makes the decision
feel immediate and protects deterministic state if the memory call fails.

### 6.5 Reopen and Revote

Reopening preserves the transcript but clears the verdict, decision, and round
alignment delta. Revoting replaces the previous choice.

After either operation, alignment and promotion records are recalculated from
all persisted rounds. This prevents double-counting and makes the operations
idempotent.

## 7. Prompt and AI Design

### 7.1 Character Prompts

Both characters receive:

- A stable identity, worldview, and recruitment objective.
- Voice and humor guidance.
- Safety instructions.
- The compact user profile.
- Their own tactical profile.
- Relevant opponent tactics.
- Up to three recent round summaries.
- The current round transcript.

Sunny argues from conscience, empathy, sacrifice, accountability, protection,
and moral repair. Crowley argues from appetite, self-preservation, ambition,
leverage, status, and immediate advantage.

The prompts prohibit persona drift, generic AI self-reference, and structured
metadata in character prose. Both characters are required to challenge the
opponent rather than produce unrelated parallel monologues.

### 7.2 Separation of Prose and Structured Output

Character calls stream plain prose. Judge and memory calls are non-streamed
structured requests.

This prevents partial JSON from leaking into the UI and keeps schema validation
out of the token-streaming path.

### 7.3 Judge Prompt

The judge evaluates rhetoric rather than moral correctness. This is necessary
for a meaningful competition: judging morality alone would structurally favor
Sunny regardless of debate quality.

### 7.4 Memory Prompt

After a decided round, one structured call produces:

- A user-profile update.
- A Sunny strategy update.
- A Crowley strategy update.

The memory prompt receives current compact profiles and a bounded round payload.
It is instructed to infer cautiously, avoid private-fact invention, and keep
tactics short and useful.

If validation or generation fails, deterministic heuristics update preferences
and tactics from the user's decision and judge-extracted tactics.

## 8. Context and Memory Management

### 8.1 Current Context Boundaries

The implementation does **not** resend every conversation from every previous
round to each character.

For a character turn, context currently contains:

| Context source | Current bound |
|---|---|
| Character system instructions | Fixed |
| User profile | Compact current profile |
| Own and opponent strategy profiles | Lists deduplicated and capped at 8 items |
| Cross-round history | Summaries of the latest 3 other rounds |
| Active round | Full transcript, currently unbounded |

For a memory update:

| Context source | Current bound |
|---|---|
| Existing agent profiles | Compact current profiles with capped tactic lists |
| Existing user profile | Values/themes are capped, but `decision_history` is currently unbounded |
| Transcript | Last 8 messages |
| Message content | Each excerpt truncated to 600 characters |
| Structured round facts | Dilemma, decision, alignment delta, verdict, tactics, key moment |

All complete rounds and messages remain stored in SQLite for history and
debugging, but storage history is not automatically equivalent to prompt
context.

### 8.2 Current Scaling Weakness

The main prompt-scaling risk is the **active round transcript**:

- A user can continue one round repeatedly.
- Every later agent turn receives that round's complete transcript.
- Final judging also receives the complete transcript.
- Input-token cost and latency therefore grow approximately linearly with the
  number and length of turns in that round.
- Very long rounds can eventually exceed the model context window or cause the
  oldest and most important instructions to receive less effective attention.

Additional, smaller risks are:

- Compact profile notes are replaced but have no explicit character limit.
- LLM-generated profile summaries can accumulate interpretation drift over many
  rounds.
- Full decision history is stored in the user profile and serialized into each
  memory-update prompt even though round choices are already persisted. Memory
  input therefore also grows linearly with the number of decided rounds.
- `MAX_ROUNDS_PER_SESSION` is configured but is not currently enforced.
- Database size grows with complete transcripts and model-run records, although
  this does not directly increase prompt size.

For the expected assignment demo, these are acceptable prototype tradeoffs.
They should be addressed before supporting long-running production accounts.

### 8.3 Production Context Strategy

A production implementation should build each prompt through a token-budgeted
context assembler:

```text
fixed persona and safety instructions
        +
compact durable user/agent profiles
        +
rolling summary of earlier active-round turns
        +
latest N verbatim active-round messages
        +
latest user message
        <= configured input-token budget
```

Recommended behavior:

1. Reserve fixed token budgets for persona instructions, output, and safety.
2. Keep the latest 6-10 active-round messages verbatim.
3. When earlier messages exceed the remaining budget, summarize them into a
   structured `RoundConversationSummary`.
4. Update that summary incrementally instead of repeatedly summarizing the whole
   transcript.
5. Preserve explicit user decisions, unresolved claims, concessions, and major
   arguments as structured summary fields.
6. Use the same compacted context for agents and judging so the judge evaluates
   the same relevant debate state.
7. Keep full transcripts in storage for audit/history, independently of what is
   selected for model context.
8. Record input token counts and trigger compaction before the provider limit,
   not only after an API failure.
9. Replace prompt-level decision history with derived aggregates such as total
   Sunny/Crowley/undecided choices, recent choices, streak, and trend. The full
   history remains queryable from persisted rounds.

An example summary model:

```python
class RoundConversationSummary(BaseModel):
    user_constraints: list[str]
    sunny_claims: list[str]
    crowley_claims: list[str]
    sunny_concessions: list[str]
    crowley_concessions: list[str]
    unresolved_questions: list[str]
    turning_points: list[str]
    summary_through_message: int
```

This is preferable to simply truncating the oldest messages because blind
truncation can remove the original dilemma, important user constraints, or the
argument that a later rebuttal references.

Semantic retrieval or embeddings are not necessary for this prototype. They
become useful only if memory must span many sessions and selectively retrieve
specific past dilemmas. Compact profiles plus rolling summaries are simpler and
more predictable for the current product.

## 9. Scoring

Alignment is clamped to `[-100, 100]`.

| Event | Delta |
|---|---:|
| Follow Sunny | `+15` |
| Follow Crowley | `-15` |
| Undecided | `0` |
| Judge selects Sunny | `+3` |
| Judge selects Crowley | `-3` |

The judge bonus applies regardless of the user's decision. Therefore:

- Follow Sunny and Sunny wins: `+18`.
- Follow Sunny and Crowley wins: `+12`.
- Follow Crowley and Sunny wins: `-12`.
- Follow Crowley and Crowley wins: `-18`.
- Undecided: `+3` or `-3` based on the judge.

Promotion wins count user conversions only:

- A Sunny choice adds one Sunny conversion.
- A Crowley choice adds one Crowley conversion.
- Undecided adds neither.

Judge victories are displayed separately as laurels. The UI also derives the
current consecutive conversion streak.

## 10. Persistence

SQLite schema version: `4`.

### 10.1 Tables

- `users`: local profiles used to separate ownership.
- `sessions`: alignment and compact memory profiles.
- `rounds`: canonical serialized round snapshots.
- `messages`: append-only transcript/audit entries.
- `model_runs`: model, call type, token usage, latency, streaming flag, and error
  metadata.
- `memory_jobs`: durable pending/completed memory updates keyed by session and round.

Foreign keys and cascading deletes are enabled. Connections use:

- Foreign-key enforcement.
- WAL journal mode for file databases.
- A busy timeout.
- Explicit transaction commit and rollback.
- Explicit connection closing.

The local user system is not authentication. It gives the prototype an
ownership-shaped data model while avoiding production identity scope.

### 10.2 State Consistency

The application persists active rounds during generation rather than only after
judging. Each completed character turn is saved to the round snapshot and
message log.

Scoring state can be reconstructed from rounds. Memory profiles are persisted
snapshots and can fall back to deterministic updates if the LLM call fails.
Round transitions write the snapshot, session state, audit messages, model-run
metadata, and memory-job status in one SQLite transaction.

Round numbers are allocated while holding a SQLite write lock, preventing stale
browser tabs from overwriting the same `(session_id, round_number)` row.

When a vote is changed or a round is reopened, adaptive profiles are rebuilt
from durable decided rounds before any new memory update runs. This removes
tactics and inferred preferences derived from an invalidated decision.

## 11. UI Specification

### 11.1 Main Conversation Surface

The main area provides:

- Chronological user, Sunny, Crowley, and system messages.
- Streamed character responses.
- Character avatars that reflect who is winning.
- Verdict winner, scores, rationale, and key moment.
- Follow-up input.
- A segmented target control for both, Sunny, or Crowley.
- Continue and finalize actions.
- User decision actions.
- Reopen and revote actions.
- New-dilemma composition.

### 11.2 Sidebar

The sidebar provides:

- Local user creation, selection, and deletion.
- Session creation, selection, and deletion.
- Alignment meter and moral nickname.
- Sunny and Crowley conversion totals.
- Judge laurels and conversion streak.
- Up to eight recent round-history entries.
- Selection of a prior round for full transcript display.

### 11.3 Streamlit Constraints

Streamlit reruns the script after interactions. The implementation centralizes
session-state transitions and uses a small scroll bridge to keep the viewport
near new content.

Memory updates execute after the decision view renders, but still run inside the
Streamlit process. A production frontend/backend split should move this work to
a background task.

## 12. Error Handling and Resilience

### 12.1 Provider Calls

- Provider calls retry up to three times with exponential backoff.
- Streaming failures are normalized to `LLMError`.
- Judge failure produces a marked deterministic fallback verdict.
- Memory failure produces deterministic heuristic profile updates.
- Missing API configuration displays a setup error before the app starts.

### 12.2 Structured Output

Pydantic models are converted to strict JSON schemas for OpenAI structured
output. Returned data is validated again before entering domain logic.

### 12.3 Logging and Diagnostics

Logs include:

- Call type and model.
- Estimated or reported input/output tokens.
- Latency.
- Streaming status.
- Errors and fallback use.

Prompt and response payload logging is disabled by default because dilemmas can
contain sensitive personal information.

## 13. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | none | Required for the OpenAI provider |
| `OPENAI_MODEL` | `gpt-5.4` | Model used for character, judge, and memory calls |
| `LLM_PROVIDER` | `openai` | `openai` or test-oriented `mock` |
| `DB_PATH` | `data/state.db` | SQLite path |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LOG_FILE` | `logs/angel_demon.log` | Rotating log path |
| `LOG_LLM_PAYLOADS` | `false` | Opt-in sensitive payload logging |
| `MAX_ROUNDS_PER_SESSION` | `20` | Configured prototype limit; currently not enforced |
| `LLM_TEMPERATURE_AGENTS` | `0.85` | Character creativity |
| `LLM_TEMPERATURE_JUDGE` | `0.3` | Judge consistency |
| `LLM_TEMPERATURE_MEMORY` | `0.3` | Memory consistency |

## 14. Testing

The test suite uses the mock provider and temporary SQLite databases. It covers:

- Alignment, promotion, laurels, and streak scoring.
- SQLite users, sessions, migrations, rounds, messages, and deletion behavior.
- Targeted and untargeted conversation flow.
- Automatic first-clash generation.
- Judging, fallback behavior, reopening, and rejudging.
- Decisions, revoting, and total recomputation.
- Structured and heuristic memory updates.
- Prompt rendering and adaptation context.
- Sidebar labels and history behavior.
- Avatar, realm-art, and theme behavior.

Quality commands:

```bash
pytest -q
ruff check app.py src tests
mypy src
```

The suite intentionally mocks model output. Before delivery or deployment, one
real-provider smoke test should exercise streaming, judging, decision
persistence, memory update, and a subsequent adapted round.

## 15. Security and Safety

Current controls:

- API keys are read from environment variables.
- `.env` is ignored by Git.
- Character prompts prohibit actionable violence and illegal instructions.
- The judge can return safety notes.
- Payload logging is opt-in.
- Dilemmas have basic length and format validation.
- Users can delete local users and sessions.

Prototype limitations:

- Character context contains user-supplied transcript text, so prompt-injection
  attempts remain possible.
- There is no moderation API integration.
- There is no authentication or authorization.
- Local profile inference can contain sensitive conclusions.
- There are no rate limits or cost ceilings.

Production should add input/output moderation, explicit instruction hierarchy,
prompt-injection evaluation, authentication, authorization, deletion and
retention policies, rate limits, and per-user cost budgets.

## 16. Production Evolution

The intended production architecture is:

- React/TypeScript frontend.
- FastAPI backend.
- Server-sent events for character streaming.
- PostgreSQL with migrations and JSONB where appropriate.
- Authentication and ownership enforcement.
- Background jobs for memory compaction and profile updates.
- Redis only where caching, locks, or queues justify it.
- OpenTelemetry traces and metrics.
- Token-budgeted context assembly and rolling summaries.
- Automated prompt and behavior evaluations.
- Moderation, rate limits, and cost controls.

See [production-strategy.md](production-strategy.md) for migration phases.

## 17. Known Limitations

- Active-round transcripts are not yet compacted or token-budgeted.
- The configured maximum round count is not enforced.
- Memory updates block the Streamlit process even though the choice is persisted
  first.
- Judge output can vary between identical runs.
- Character quality is validated through prompt contracts and manual use rather
  than a formal LLM evaluation suite.
- The mock test suite cannot verify real provider availability, latency, or
  qualitative output.
- SQLite and local users are appropriate only for the prototype.
- Streamlit requires rerun and scroll workarounds.

## 18. Project Structure

```text
.
|-- app.py
|-- pyproject.toml
|-- README.md
|-- assets/
|   |-- avatars/
|   `-- style.css
|-- docs/
|   |-- assignment.md
|   |-- design-decisions.md
|   |-- implementation-challenges.md
|   |-- production-strategy.md
|   `-- spec.md
|-- scripts/
|-- src/
|   `-- angel_demon/
|       |-- agents.py
|       |-- config.py
|       |-- diagnostics.py
|       |-- dilemmas.py
|       |-- flow.py
|       |-- judge.py
|       |-- llm.py
|       |-- logging_config.py
|       |-- memory.py
|       |-- models.py
|       |-- prompts.py
|       |-- scoring.py
|       |-- state.py
|       `-- ui/
|           |-- debate.py
|           |-- realm_art.py
|           |-- round_actions.py
|           |-- round_view.py
|           |-- scroll.py
|           |-- session_controller.py
|           |-- session_state.py
|           |-- sidebar.py
|           `-- theme.py
`-- tests/
```

## 19. Definition of Done

- A reviewer can install and run the application from the README.
- Sunny and Crowley produce distinct, competitive responses.
- The user can hold a multi-turn conversation with either or both characters.
- Every finalized round produces a validated winner or marked fallback.
- User decisions update alignment and promotion totals.
- Decided rounds update compact memory used by later prompts.
- Conversations and model metadata persist across reruns.
- Previous rounds can be viewed, reopened, rejudged, and revoted.
- The UI displays history, alignment, promotion state, and verdict details.
- Automated tests, linting, and type checking pass.
- Production strategy, design decisions, and implementation challenges are
  documented.
