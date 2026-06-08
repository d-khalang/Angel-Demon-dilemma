# Implementation Challenges

This file is a running note of the main challenges encountered while implementing
the debate-thread, promotion-race, and UI theming changes.

## Persistent Debate Threads

- The original app treated an in-progress conversation as a transient `ConversationDraft`
  in Streamlit session state, then converted it into a persisted `Round` only after the
  judge verdict. That made ChatGPT/Gemini-style history difficult because unfinished,
  judged, and decided rounds had different lifecycles.
- The fix was to make `Round` itself the durable thread object, add explicit statuses
  (`active`, `judged`, `decided`), and persist every state transition.
- Compatibility was tricky because older code and tests expected `sunny_opening`,
  `crowley_opening`, rebuttals, and `verdict` to always exist. Those fields now need to
  be treated as derived or nullable while `conversation` is the canonical transcript.

## Full Transcript History

- The database already stored enough transcript data in round JSON, but the sidebar UI
  intentionally collapsed history to winner/verdict summaries.
- Moving history selection into the sidebar required separating "which round is selected"
  from the older "current draft/current round" state keys.
- The sidebar should identify a thread, not duplicate the full transcript, so the final
  approach uses compact round buttons with status and metadata while the main panel renders
  the transcript.

## Reopen, Rejudge, And Revote

- Reopening a judged round is not just a UI action. It must clear verdict, choice, and
  alignment delta while preserving the transcript.
- Revoting is deterministic, but prior implementation incremented wins/losses directly.
  That would double-count if a user changed their choice.
- The safer approach is to recalculate alignment and promotion totals from all persisted
  round choices whenever a round is reopened or revoted.
- LLM-derived profiles also combine multiple rounds and cannot be reversed field by field.
  Reopening or revoting now rebuilds a conservative profile from durable decided rounds,
  then queues a new durable memory update when appropriate.

## Persistence And Restart Safety

- Stale Streamlit tabs can hold the same in-memory session snapshot. Round numbers are now
  allocated under a SQLite write lock so two clients cannot upsert the same round.
- A workflow transition writes its round snapshot, session, audit messages, model-run
  metadata, and memory-job state in one transaction.
- Pending memory work is stored in `memory_jobs`, not only `st.session_state`, so a browser
  refresh or process restart can resume it.
- An interrupted initial stream discards the incomplete round and audit rows, allowing a
  clean retry with the same round number.

## Streaming Regression

- Streaming initially regressed after the UI refactor because generation was triggered
  inside collapsed `st.status` blocks and bottom containers. Streamlit only showed the
  completed rerender, so the user saw a spinner followed by full messages.
- Another issue was placeholder reuse: the automatic first clash reused Sunny/Crowley
  placeholders from the opening, which could merge multiple turns into the same bubble.
- The fix was to execute streaming in the main chat surface and create a fresh placeholder
  per generated turn.

## Streamlit Rerun And Scroll Behavior

- Button clicks trigger full Streamlit reruns. After continuing a debate, the page could
  jump back to the top of the transcript, which felt broken for long chats.
- Moving the work out of `st.bottom` helped, but reruns still reset scroll position.
- A small scroll-to-bottom hook after thread rendering keeps the user near the newest
  messages. This is a pragmatic Streamlit workaround, not a perfect frontend solution.

## Latency Sources

- SQLite writes were not the meaningful bottleneck.
- Judge finalization is a non-streamed structured LLM call over the full transcript, so it
  will always feel less immediate than character responses.
- The largest unexpected latency came after choosing a side: memory updates sent the full
  round JSON, including transcript, into three profile-update calls. One local run showed
  about 7,900 input tokens and roughly 4.6 seconds for `memory_updates`.
- The mitigation was to send compact round facts plus a transcript excerpt to memory
  updates instead of the full round JSON.

## Tests And Tooling

- The new automatic first clash changed the number and order of mocked LLM calls, so flow
  tests had to be updated to include four initial agent responses instead of two.
- Nullable verdicts required adding guards in memory and prompt summary code.
- Full repo-wide `ruff check` is currently affected by unrelated untracked local files, so
  checks were run against `app.py`, `src`, and `tests` for the changed implementation.

## Follow-Up Refactor

- Splitting `app.py` required keeping Streamlit rerun behavior centralized. The main risk
  was moving action handlers without losing the post-action scroll request flags.
- Removing `ConversationDraft` was simpler after `Round` became the only active thread
  model, but it required deleting compatibility branches in flow code rather than leaving
  dead fallback paths.
- Making decisions feel immediate required separating deterministic persistence from LLM
  memory updates. The round now closes first, then memory updates run after the decided
  view is rendered.
- Wiping local data while the Streamlit process was running required stopping the process
  first so SQLite sidecar files would not remain locked.

## Streamlit Theme Bridging

- Light mode looked dark because the custom CSS used `prefers-color-scheme: dark` as a
  fallback token switch. That follows the OS/browser preference, not Streamlit's explicit
  Light/Dark/System menu choice, so Streamlit could show "Light" while the app used dark
  design tokens.
- The first attempted fix relied on a `<script>` inside `st.markdown`, but Streamlit inserts
  that markup in a way that leaves the script inert. Even if it had run, the heuristic looked
  for `--text-color` on `:root`, which Streamlit 1.58 does not expose there.
- `st.context.theme.type` was not a reliable replacement because Streamlit infers it from
  app background state and documents that it can be stale during first load and theme changes.
  Our injected CSS also changes the app background, so using that Python-side value created a
  feedback loop.
- The durable workaround is a tiny iframe bridge that watches Streamlit's own
  theme menu/body background and writes `data-ad-theme` on the parent document. The bridge
  now uses `st.iframe` because `components.html` was removed after June 1, 2026. The CSS now
  treats light as the default and only activates dark tokens through that explicit attribute.
- Streamlit reruns can create multiple component instances, so the bridge must be idempotent:
  it disconnects the previous observer, clears the previous polling interval, and then starts
  a fresh observer. The polling fallback is intentionally small because theme changes do not
  always produce a mutation visible to the component script.
