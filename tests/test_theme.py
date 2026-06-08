from angel_demon.ui import theme


def test_theme_bridge_injects_idempotent_streamlit_theme_script(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_iframe(
        markup: str,
        *,
        height: int,
        width: int,
        tab_index: int,
    ) -> None:
        calls.append(
            {
                "markup": markup,
                "height": height,
                "width": width,
                "tab_index": tab_index,
            }
        )

    monkeypatch.setattr(theme.st, "iframe", fake_iframe)

    theme.inject_theme_mode()

    assert calls == [
        {
            "markup": calls[0]["markup"],
            "height": 1,
            "width": 1,
            "tab_index": -1,
        }
    ]
    markup = str(calls[0]["markup"])
    assert 'root.setAttribute("data-ad-theme"' in markup
    assert "data-user-theme" not in markup
    assert "__angelDemonThemeBridge" in markup
    assert "clearInterval" in markup
    assert "disconnect()" in markup
