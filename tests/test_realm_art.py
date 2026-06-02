import re

from angel_demon.ui import realm_art
from angel_demon.ui.realm_art import moral_icon, moral_nickname


def test_moral_nickname_boundaries() -> None:
    assert moral_nickname(61) == "Divine Paragon"
    assert moral_nickname(21) == "Righteous Pilgrim"
    assert moral_nickname(-20) == "Undecided Mortal"
    assert moral_nickname(-21) == "Tempted Sinner"
    assert moral_nickname(-61) == "Hellbound Overlord"


def test_moral_icon_boundaries() -> None:
    assert moral_icon(61) == "\U0001f31f"
    assert moral_icon(21) == "\U0001f47c"
    assert moral_icon(0) == "\u2696\ufe0f"
    assert moral_icon(-21) == "\U0001f608"
    assert moral_icon(-61) == "\U0001f525"


def test_realm_art_uses_gradient_variables_instead_of_dots(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_markdown(markup: str, *, unsafe_allow_html: bool) -> None:
        calls.append({"markup": markup, "unsafe_allow_html": unsafe_allow_html})

    monkeypatch.setattr(realm_art.st, "markdown", fake_markdown)

    realm_art.inject_realm_art(100)

    assert calls == [
        {
            "markup": calls[0]["markup"],
            "unsafe_allow_html": True,
        }
    ]
    markup = str(calls[0]["markup"])
    assert "--ad-realm-corner-1" in markup
    assert "--ad-realm-corner-2" in markup
    assert "--ad-realm-edge-left" in markup
    assert "--ad-realm-edge-right" in markup
    assert "--ad-realm-bottom" in markup
    assert "--ad-dots" not in markup


def test_realm_art_caps_gradient_alpha_for_readability(monkeypatch) -> None:
    calls: list[str] = []

    def fake_markdown(markup: str, *, unsafe_allow_html: bool) -> None:
        assert unsafe_allow_html is True
        calls.append(markup)

    monkeypatch.setattr(realm_art.st, "markdown", fake_markdown)

    realm_art.inject_realm_art(-100)

    alphas = [float(value) for value in re.findall(r", (0\.\d+)\)", calls[0])]
    assert alphas
    assert max(alphas) <= 0.213
