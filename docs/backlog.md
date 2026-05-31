# Backlog

## Deferred Test Coverage

- Add UI-level integration tests after the user/session sidebar and debate UX settle. The current backend tests cover ownership, cascade deletion, and anonymous-session claiming, but Streamlit interaction tests should wait until the UI surface is less volatile.

## Conversation Improvements

- Done: replace the fixed four-step debate UI with a unified Streamlit chat thread where users can add follow-ups before judging the round.
- Done: allow the user to address both agents, Sunny only, or Crowley only during an active debate.
- Done: stop forcing Sunny to use a dad joke in every response; humor is now conditional on the dilemma's emotional stakes.
- Remaining: make agent evolution more visible in the UI and in generated arguments. The database updates profiles, but the product should show why the agents changed strategy and make that adaptation noticeable to the user.
