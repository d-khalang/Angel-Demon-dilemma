"""Small Streamlit scroll helpers."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from angel_demon.ui import session_state as ui_state


def scroll_to_bottom_if_requested() -> None:
    if not ui_state.consume_scroll_to_bottom():
        return

    # Streamlit button clicks rerun the whole script. The retry loop waits for the
    # post-rerun verdict/actions DOM to mount before moving the viewport.
    st.markdown('<div id="round-bottom-anchor"></div>', unsafe_allow_html=True)
    components.html(
        """
        <script>
        const scroll = () => {
            const doc = window.parent.document;
            const anchor = doc.getElementById("round-bottom-anchor");
            if (anchor) {
                anchor.scrollIntoView({ behavior: "smooth", block: "end" });
                return;
            }
            const root = doc.scrollingElement || doc.documentElement || doc.body;
            root.scrollTo({ top: root.scrollHeight, behavior: "smooth" });
        };
        [50, 150, 350, 700, 1200].forEach((delay) => window.setTimeout(scroll, delay));
        </script>
        """,
        height=0,
    )
