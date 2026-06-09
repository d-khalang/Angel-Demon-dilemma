# Production Strategy

## What needs to Change

The Streamlit and SQLite prototype demonstrates the product loop, but a public
service needs:

- A frontend that does not rerun the full application after each interaction.
- An API that does not block the UI during slow LLM calls.
- Authentication and authorization.
- A database shared by multiple application instances.
- Rate limits, spending limits, and moderation.

## Target Architecture

- React with TypeScript for the frontend.
- FastAPI for the backend.
- PostgreSQL for durable data.
- A separate worker for memory jobs.
- Redis for rate limits and short-lived caching.
- Server-sent events for streamed character responses.

Most of the current Python logic can stay. `flow.py`, the domain rules, prompts,
judge, memory code, scoring, and LLM provider do not depend directly on
Streamlit.

## API and Concurrency

- Endpoints create users and sessions, run each round phase, record decisions,
  and load history.
- Mutations accept an idempotency key so retries do not duplicate messages.
- Mutations include the expected session or round version so stale clients
  cannot overwrite newer state.

## Streaming

The current application sends OpenAI chunks through Streamlit placeholders.
Production separates this into a browser client and an API stream:

- I would use server-sent events because character output is mainly
  server-to-client. User actions remain normal POST requests.
- Events include a durable ID, their phase, and enough data to append them once.
- After a disconnect, `Last-Event-ID` lets the server resume from persisted
  events or return the completed round without duplicating messages.

## Database and Transactions

- The current users, sessions, rounds, messages, model runs, and memory jobs map
  to PostgreSQL.
- Round and profile JSON use JSONB, with Alembic for migrations.
- A round snapshot, session state, audit messages, model metadata, and job state
  for one workflow event commit in one transaction.

## Memory Worker

- FastAPI `BackgroundTasks` can lose work when a web process restarts.
- The API commits the decision and a job/outbox row in the same transaction.
- A separate worker claims jobs with row locks and supports retries and
  idempotent processing because execution is at least once.
- The job remains durable if either the API or worker restarts.

## Authentication and Data Access

- Replace the local user selector with real authentication, such as JWT.
- Scope every session query to the authenticated user.
- Treat user, session, and round IDs from the client as untrusted input.
- Add data deletion, retention rules, and a grace period before permanent
  account deletion.

## Safety

- Moderate dilemmas and follow-ups before LLM calls, and generated responses
  before display.
- Replace blocked output with a safe response and record only the category and
  decision by default. Prompt rules remain an additional layer.

## Cost and Abuse Controls

- Per-user request and round limits.
- A maximum number of follow-ups per round.
- Output-token limits for each call type.
- Daily token or cost budgets per user.
- Separate model choices for character generation, judge, and memory.

Memory and judge calls can usually use cheaper or faster models than the
characters.

## Observability

- JSON logs with request IDs.
- OpenTelemetry spans around each round phase and LLM call.
- Metrics for latency, token use, estimated cost, errors, fallbacks, moderation,
  memory job age, retries, stale-write conflicts, and SSE reconnections.
- Dashboards for slow and expensive calls, fallback rates, stuck jobs, and
  repeated reconnections or retries.

## Testing and Evals

- Run the current integration and contract tests against PostgreSQL and the
  real worker.
- Keep deterministic tests in normal CI.
- Run live evaluations separately and store the model, prompt, output, and
  scores.

Versioned evaluation sets cover:

- Sunny and Crowley persona consistency.
- Prompt-injection resistance.
- Judge stability.
- Memory quality over several rounds.
- Safety and moderation.

## Migration Order

1. Put the existing workflow behind FastAPI.
2. Move SQLite to PostgreSQL and add row versions.
3. Add the durable memory worker.
4. Add resumable SSE.
5. Add authentication and authorization.
6. Add input and output moderation.
7. Add rate limits, cost budgets, and observability.
8. Replace Streamlit with the React UI.
9. Expand eval datasets before wider release.


