"""Theme bridge between Streamlit and the custom CSS design tokens."""

from __future__ import annotations

import streamlit as st


def inject_theme_mode() -> None:
    st.iframe(
        """
        <script>
        (function() {
          const parentWindow = window.parent;
          const doc = window.parent.document;
          const root = doc.documentElement;
          const existing = parentWindow.__angelDemonThemeBridge;
          if (existing) {
            existing.observer && existing.observer.disconnect();
            existing.intervalId && parentWindow.clearInterval(existing.intervalId);
            existing.mediaQuery &&
              existing.listener &&
              existing.mediaQuery.removeEventListener("change", existing.listener);
          }

          function modeFromCheckedMenu() {
            const checked = doc.querySelector(
              '[data-testid^="stMainMenuItem-theme-"][aria-checked="true"]'
            );
            const testId = checked && checked.getAttribute("data-testid");
            if (!testId) {
              return null;
            }
            if (testId.endsWith("-Dark")) {
              return "dark";
            }
            if (testId.endsWith("-Light")) {
              return "light";
            }
            return null;
          }

          function modeFromBodyBackground() {
            const color = window.parent.getComputedStyle(doc.body).backgroundColor;
            const match = color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
            if (!match) {
              return "light";
            }
            const red = Number(match[1]) / 255;
            const green = Number(match[2]) / 255;
            const blue = Number(match[3]) / 255;
            const luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
            return luminance < 0.5 ? "dark" : "light";
          }

          function applyThemeMode() {
            root.setAttribute("data-ad-theme", modeFromCheckedMenu() || modeFromBodyBackground());
          }

          applyThemeMode();
          const observer = new MutationObserver(applyThemeMode);
          observer.observe(doc.body, {
            attributes: true,
            attributeFilter: ["aria-checked", "class", "style"],
            childList: true,
            subtree: true
          });
          const intervalId = parentWindow.setInterval(applyThemeMode, 250);
          const mediaQuery = parentWindow.matchMedia("(prefers-color-scheme: dark)");
          mediaQuery.addEventListener("change", applyThemeMode);
          parentWindow.__angelDemonThemeBridge = {
            observer,
            intervalId,
            mediaQuery,
            listener: applyThemeMode
          };
        })();
        </script>
        """,
        height=1,
        width=1,
        tab_index=-1,
    )
