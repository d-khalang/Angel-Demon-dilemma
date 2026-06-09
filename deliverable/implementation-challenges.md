# Implementation Challenges

- **Prioritizing the available time:** The first challenge was deciding what to
  implement for the assignment, what to investigate, and what to leave for
  production. I focused on the complete debate loop, persistence, failure
  handling, and tests. Authentication, moderation, distributed workers, and a
  production frontend remain part of the production strategy.

- **Understanding the product direction:** It was not immediately clear whether
  the product should behave mainly as a chatbot or as a game. The final design
  combines a conversational debate thread with game elements such as alignment,
  scores, character progression, and promotion.

- **Defining how the characters disagree:** Forcing the characters to always
  choose opposite answers could make their reasoning artificial. They may reach
  the same conclusion, but Sunny argues from empathy and responsibility while
  Crowley argues from self-interest and personal gain. They still challenge
  each other's reasoning.

- **Working within Streamlit's limitations:** Every interaction reruns the
  script, which affects active state, scrolling, streaming, and component
  lifecycle. State transitions are persisted, generation runs in the main chat
  surface, and small UI hooks restore scrolling and theme behavior after reruns.

- **Making debate threads durable:** An unfinished debate originally existed
  only in Streamlit session state. `Round` became the durable thread model, with
  `active`, `judged`, and `decided` states persisted after every transition.

- **Supporting reopening and revoting:** Changing an earlier decision can affect
  scores and adaptive memory. Scores are recalculated from persisted rounds, and
  the profile is rebuilt from decided rounds instead of trying to reverse an
  LLM-generated update field by field.

- **Protecting consistency during failures and concurrency:** Related round,
  session, audit, model-run, and memory-job changes commit in one transaction.
  SQLite write locks prevent stale tabs from allocating the same round number,
  and incomplete initial streams are removed for a clean retry.

- **Making memory work recoverable:** A decision is saved together with a
  durable memory job before the slower LLM update runs. The work can resume
  after a refresh or process restart without delaying the visible decision.

- **Controlling LLM latency and prompt size:** Sending the full transcript into
  every memory call was slow and expensive. Memory prompts now use compact round
  facts and a limited transcript excerpt, while character output remains
  streamed for immediate feedback.
