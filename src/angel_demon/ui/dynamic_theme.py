"""Dynamic Streamlit theme styles driven by alignment score."""

from __future__ import annotations

import streamlit as st

from angel_demon.models import AlignmentZone
from angel_demon.scoring import get_alignment_zone


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
        return "🌟"
    if score >= 21:
        return "👼"
    if score >= -20:
        return "⚖️"
    if score >= -60:
        return "😈"
    return "🔥"


def _theme_vars(zone: AlignmentZone) -> dict[str, str]:
    themes = {
        AlignmentZone.NEUTRAL: {
            "bg-gradient": (
                "linear-gradient(90deg, rgba(255, 244, 210, 0.58), "
                "rgba(255,255,255,0) 38%), "
                "linear-gradient(270deg, rgba(91, 19, 31, 0.10), "
                "rgba(255,255,255,0) 42%), #fbfaf7"
            ),
            "sidebar-bg": "#f4f0e8",
            "surface-bg": "rgba(255, 255, 255, 0.76)",
            "surface-border": "rgba(40, 35, 30, 0.12)",
            "text-color": "#26221d",
            "muted-color": "#6f665b",
            "accent": "#b6892d",
            "accent-strong": "#7f5d1f",
            "shadow": "0 12px 30px rgba(70, 54, 28, 0.10)",
        },
        AlignmentZone.HEAVEN: {
            "bg-gradient": (
                "radial-gradient(circle at 18% 12%, rgba(255, 222, 128, 0.42), "
                "transparent 30%), linear-gradient(140deg, #eef8ff 0%, "
                "#fff8dc 52%, #f9fbff 100%)"
            ),
            "sidebar-bg": "rgba(232, 246, 255, 0.94)",
            "surface-bg": "rgba(255, 255, 255, 0.78)",
            "surface-border": "rgba(65, 137, 189, 0.22)",
            "text-color": "#17293a",
            "muted-color": "#52697b",
            "accent": "#d9a72f",
            "accent-strong": "#1f84bd",
            "shadow": "0 14px 34px rgba(84, 149, 196, 0.16)",
        },
        AlignmentZone.DEEP_HEAVEN: {
            "bg-gradient": (
                "radial-gradient(circle at 20% 10%, rgba(255, 231, 117, 0.58), "
                "transparent 28%), radial-gradient(circle at 78% 18%, "
                "rgba(130, 202, 255, 0.45), transparent 30%), "
                "linear-gradient(135deg, #dff4ff 0%, #fff1b8 54%, #ffffff 100%)"
            ),
            "sidebar-bg": "rgba(220, 242, 255, 0.96)",
            "surface-bg": "rgba(255, 255, 255, 0.82)",
            "surface-border": "rgba(218, 169, 45, 0.38)",
            "text-color": "#102538",
            "muted-color": "#486174",
            "accent": "#e0aa24",
            "accent-strong": "#0d8ad1",
            "shadow": "0 16px 42px rgba(49, 139, 201, 0.22)",
        },
        AlignmentZone.HELL: {
            "bg-gradient": (
                "radial-gradient(circle at 85% 12%, rgba(190, 44, 36, 0.28), "
                "transparent 34%), linear-gradient(145deg, #1b1718 0%, "
                "#2b1115 52%, #161315 100%)"
            ),
            "sidebar-bg": "#211719",
            "surface-bg": "rgba(33, 23, 25, 0.88)",
            "surface-border": "rgba(238, 71, 54, 0.26)",
            "text-color": "#f5ece6",
            "muted-color": "#c5a9a2",
            "accent": "#e04b37",
            "accent-strong": "#ff8a45",
            "shadow": "0 16px 42px rgba(0, 0, 0, 0.28)",
        },
        AlignmentZone.DEEP_HELL: {
            "bg-gradient": (
                "radial-gradient(circle at 76% 16%, rgba(255, 72, 40, 0.34), "
                "transparent 30%), radial-gradient(circle at 18% 82%, "
                "rgba(126, 11, 30, 0.42), transparent 34%), "
                "linear-gradient(150deg, #0f0d0e 0%, #22090d 48%, #130f10 100%)"
            ),
            "sidebar-bg": "#170f11",
            "surface-bg": "rgba(22, 15, 17, 0.92)",
            "surface-border": "rgba(255, 66, 48, 0.34)",
            "text-color": "#fff2ec",
            "muted-color": "#d0a19a",
            "accent": "#ff4e38",
            "accent-strong": "#ffb15c",
            "shadow": "0 18px 48px rgba(0, 0, 0, 0.36)",
        },
    }
    return themes[zone]


def inject_dynamic_theme(score: int) -> None:
    vars_css = "\n".join(
        f"  --ad-{name}: {value};" for name, value in _theme_vars(get_alignment_zone(score)).items()
    )
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Outfit:wght@400;500;650;700&display=swap');
        :root {{
        {vars_css}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
