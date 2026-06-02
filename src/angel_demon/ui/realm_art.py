"""Alignment labels and decorative realm art."""

from __future__ import annotations

import streamlit as st

MAX_REALM_INTENSITY = 0.85


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
    intensity = min(abs(score) / 100.0, MAX_REALM_INTENSITY)

    glow_color_1 = "transparent"
    glow_color_2 = "transparent"
    glow_color_3 = "transparent"
    realm_corner_1 = "transparent"
    realm_corner_2 = "transparent"
    realm_edge_left = "transparent"
    realm_edge_right = "transparent"
    realm_bottom = "transparent"

    if score > 0:
        # Heaven: warm gold edge aura with a small cool highlight.
        glow_color_1 = f"rgba(var(--ad-heaven-glow-1), {intensity * 0.14:.3f})"
        glow_color_2 = f"rgba(var(--ad-heaven-glow-2), {intensity * 0.10:.3f})"
        glow_color_3 = f"rgba(var(--ad-heaven-glow-3), {intensity * 0.16:.3f})"
        realm_corner_1 = f"rgba(var(--ad-heaven-glow-2), {intensity * 0.24:.3f})"
        realm_corner_2 = f"rgba(var(--ad-heaven-glow-3), {intensity * 0.26:.3f})"
        realm_edge_left = f"rgba(var(--ad-heaven-glow-1), {intensity * 0.16:.3f})"
        realm_edge_right = f"rgba(var(--ad-heaven-glow-2), {intensity * 0.14:.3f})"
        realm_bottom = f"rgba(var(--ad-heaven-glow-3), {intensity * 0.20:.3f})"
    elif score < 0:
        # Hell: crimson edge aura with deeper wine shadows.
        glow_color_1 = f"rgba(var(--ad-hell-glow-1), {intensity * 0.13:.3f})"
        glow_color_2 = f"rgba(var(--ad-hell-glow-2), {intensity * 0.10:.3f})"
        glow_color_3 = f"rgba(var(--ad-hell-glow-3), {intensity * 0.14:.3f})"
        realm_corner_1 = f"rgba(var(--ad-hell-glow-1), {intensity * 0.24:.3f})"
        realm_corner_2 = f"rgba(var(--ad-hell-glow-3), {intensity * 0.25:.3f})"
        realm_edge_left = f"rgba(var(--ad-hell-glow-2), {intensity * 0.16:.3f})"
        realm_edge_right = f"rgba(var(--ad-hell-glow-1), {intensity * 0.14:.3f})"
        realm_bottom = f"rgba(var(--ad-hell-glow-3), {intensity * 0.20:.3f})"

    st.markdown(
        f"""
        <style>
        :root {{
          --ad-glow-color-1: {glow_color_1};
          --ad-glow-color-2: {glow_color_2};
          --ad-glow-color-3: {glow_color_3};
          --ad-realm-corner-1: {realm_corner_1};
          --ad-realm-corner-2: {realm_corner_2};
          --ad-realm-edge-left: {realm_edge_left};
          --ad-realm-edge-right: {realm_edge_right};
          --ad-realm-bottom: {realm_bottom};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
