"""Alignment labels and decorative realm art."""

from __future__ import annotations

import streamlit as st


def moral_nickname(score: int) -> str:
    if score >= 61:
        return "Divine Paragon"
    if score >= 21:
        return "Righteous Pilgrim"
    if score >= -20:
        return "Undecided Mortal"
    if score >= -60:
        return "Tempted Sinner"
    return "Hellbound Overlord"


def moral_icon(score: int) -> str:
    if score >= 61:
        return "\U0001f31f"
    if score >= 21:
        return "\U0001f47c"
    if score >= -20:
        return "\u2696\ufe0f"
    if score >= -60:
        return "\U0001f608"
    return "\U0001f525"


def inject_realm_art(score: int) -> None:
    # Normalize score to the range [-100, 100]
    score = max(-100, min(100, score))
    intensity = abs(score) / 100.0

    # Dynamic variables
    glow_color_1 = "transparent"
    glow_color_2 = "transparent"
    glow_color_3 = "transparent"
    dots_color = "transparent"
    dots_size = "0px"

    if score > 0:
        # Heaven: Golden bubble gradients and starfield dots
        glow_color_1 = f"rgba(var(--ad-heaven-glow-1), {intensity * 0.12:.3f})"
        glow_color_2 = f"rgba(var(--ad-heaven-glow-2), {intensity * 0.08:.3f})"
        glow_color_3 = f"rgba(var(--ad-heaven-glow-3), {intensity * 0.15:.3f})"
        dots_color = f"rgba(var(--ad-heaven-dots), {intensity * 0.30:.3f})"
        dots_size = f"{1.0 + intensity * 0.8:.1f}px"
    elif score < 0:
        # Hell: Crimson bubble gradients and red glowing embers
        glow_color_1 = f"rgba(var(--ad-hell-glow-1), {intensity * 0.10:.3f})"
        glow_color_2 = f"rgba(var(--ad-hell-glow-2), {intensity * 0.08:.3f})"
        glow_color_3 = f"rgba(var(--ad-hell-glow-3), {intensity * 0.12:.3f})"
        dots_color = f"rgba(var(--ad-hell-dots), {intensity * 0.25:.3f})"
        dots_size = f"{1.0 + intensity * 0.8:.1f}px"

    st.markdown(
        f"""
        <style>
        :root {{
          --ad-glow-color-1: {glow_color_1};
          --ad-glow-color-2: {glow_color_2};
          --ad-glow-color-3: {glow_color_3};
          --ad-dots-color: {dots_color};
          --ad-dots-size: {dots_size};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
