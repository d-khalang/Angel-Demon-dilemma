from pathlib import Path

from streamlit.testing.v1 import AppTest


def button_with_label(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_streamlit_complete_user_journey(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "app.log"))

    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception

    app.text_area[0].input("Should I tell the truth or protect my friend?")
    button_with_label(app, "Start debate").click()
    app.run()

    assert not app.exception
    assert button_with_label(app, "Finalize")

    button_with_label(app, "Finalize").click()
    app.run()
    assert not app.exception
    assert button_with_label(app, "Follow Sunny")

    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    button_with_label(app, "Follow Sunny").click()
    app.run()
    assert not app.exception
    assert any(
        metric.label == "Sunny souls" and str(metric.value) == "1"
        for metric in app.metric
    )

    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    assert any(
        metric.label == "Sunny souls" and str(metric.value) == "1"
        for metric in app.metric
    )

    button_with_label(app, "Follow Crowley").click()
    app.run()
    assert not app.exception
    assert any(
        metric.label == "Crowley souls" and str(metric.value) == "1"
        for metric in app.metric
    )
