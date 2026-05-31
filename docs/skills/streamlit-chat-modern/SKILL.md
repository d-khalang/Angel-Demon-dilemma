---
name: streamlit-chat-modern
description: Streamlit chat UI guidance for building conversational apps with st.chat_message, st.chat_input, st.write_stream, bottom-pinned controls, and modern container behavior.
---

# Streamlit Chat UI

Use this skill when building or refactoring Streamlit conversational interfaces.

## Current Docs Check

Checked official Streamlit docs on 2026-05-30.

- Official 2026 release notes list Streamlit 1.57.0 as released on 2026-04-29.
- The local project environment currently has Streamlit 1.58.0 installed.
- Project code should require at least Streamlit 1.57.0 when relying on the modern chat/container behavior below.

## Core Rules

- Use `st.chat_message` for a unified conversation thread. Do not duplicate the same transcript in separate expanders unless the duplicate view adds real value.
- Do not nest `st.chat_message` containers. Streamlit documents this as a design and responsive-layout best practice.
- Use `st.chat_input` for free-form user follow-ups. It can be pinned at the page bottom when used in the main body, and it can also be used inline inside other containers.
- Use stable widget keys for chat controls because Streamlit widgets increasingly identify primarily by key.
- Use `st.write_stream` when a generator can be streamed directly. If the async source has cached async references or needs custom event parsing, wrap it manually and stream into a placeholder.
- Use `st.container(..., autoscroll=True)` for chat history when available, so new messages stay visible.
- Use `st.bottom` for persistent controls or toolbars when requiring Streamlit 1.57.0+.
- Prefer `st.status` for long-running LLM operations that are not directly represented by streamed text.

## Product Pattern For This Repo

- Render one chronological thread with user, Sunny, Crowley, and judge messages.
- Let the user target a follow-up to both agents, Sunny only, or Crowley only.
- Stream each agent response in its own chat bubble.
- Keep the judge as an explicit action after the user is done adding context.
- Store raw messages in SQLite immediately, and store the final structured round once judged.

## Official References

- Chat elements overview: https://docs.streamlit.io/develop/api-reference/chat
- `st.chat_message`: https://docs.streamlit.io/develop/api-reference/chat/st.chat_message
- `st.chat_input`: https://docs.streamlit.io/develop/api-reference/chat/st.chat_input
- `st.write_stream`: https://docs.streamlit.io/develop/api-reference/write-magic/st.write_stream
- 2026 release notes: https://docs.streamlit.io/develop/quick-reference/release-notes/2026
