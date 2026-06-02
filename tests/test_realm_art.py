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
