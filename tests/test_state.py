from angel_demon.models import Character, Opening, Rebuttal, Round, Verdict
from angel_demon.state import SessionStore


def sample_round() -> Round:
    return Round(
        round_number=1,
        dilemma="Save one loved one or 100 strangers?",
        sunny_opening=Opening(character=Character.SUNNY, argument="Choose sacrifice."),
        crowley_opening=Opening(character=Character.CROWLEY, argument="Choose your person."),
        sunny_rebuttal=Rebuttal(character=Character.SUNNY, argument="Every stranger matters."),
        crowley_rebuttal=Rebuttal(
            character=Character.CROWLEY,
            argument="Love is not a spreadsheet.",
        ),
        verdict=Verdict(
            winner=Character.CROWLEY,
            reason="More personally persuasive.",
            sunny_score=5,
            crowley_score=6,
            persuasion_tactics_sunny=["universal empathy"],
            persuasion_tactics_crowley=["family loyalty"],
            key_moment="Crowley reframed love as loyalty.",
        ),
    )


def test_session_round_trip(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    round_data = sample_round()
    session.rounds.append(round_data)
    session.alignment_score = -3

    store.save_round(session.session_id, round_data)
    store.save_session(session)

    loaded = store.load_session(session.session_id)

    assert loaded is not None
    assert loaded.session_id == session.session_id
    assert loaded.alignment_score == -3
    assert loaded.rounds[0].verdict.winner == Character.CROWLEY


def test_messages_and_model_runs_are_recorded(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()

    store.save_message(session.session_id, 1, "sunny_opening", "Be kind.")
    store.log_model_run(
        session.session_id,
        1,
        "opening",
        "gpt-5.4",
        input_tokens=10,
        output_tokens=20,
        latency_ms=500,
        was_streamed=True,
    )

    messages = store.list_messages(session.session_id)
    sessions = store.list_sessions()

    assert messages[0]["role"] == "sunny_opening"
    assert sessions[0]["session_id"] == session.session_id


def test_sessions_are_scoped_by_user(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    sunny_user = store.create_user("Sunny Tester")
    crowley_user = store.create_user("Crowley Tester")

    sunny_session = store.create_session(sunny_user.user_id)
    crowley_session = store.create_session(crowley_user.user_id)

    sunny_sessions = store.list_sessions(sunny_user.user_id)
    crowley_sessions = store.list_sessions(crowley_user.user_id)

    loaded = store.load_session(sunny_session.session_id)

    assert [row["session_id"] for row in sunny_sessions] == [sunny_session.session_id]
    assert [row["session_id"] for row in crowley_sessions] == [crowley_session.session_id]
    assert loaded is not None
    assert loaded.user_id == sunny_user.user_id


def test_default_user_is_stable(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    default_user = store.get_or_create_default_user()
    store.create_user("Named User")

    assert store.get_or_create_default_user().user_id == default_user.user_id


def test_transfer_session_moves_existing_rounds_to_new_user(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    anonymous_session = store.create_session()
    new_user = store.create_user("Noor")
    round_data = sample_round()
    store.save_round(anonymous_session.session_id, round_data)
    store.save_message(anonymous_session.session_id, 1, "sunny_opening", "Be kind.")
    store.log_model_run(anonymous_session.session_id, 1, "opening", "gpt-5.4")

    transferred = store.transfer_session(anonymous_session.session_id, new_user.user_id)

    assert transferred is not None
    assert transferred.user_id == new_user.user_id
    assert transferred.rounds[0].dilemma == round_data.dilemma
    assert store.list_sessions(new_user.user_id)[0]["session_id"] == anonymous_session.session_id
    assert store.list_messages(anonymous_session.session_id)[0]["role"] == "sunny_opening"


def test_delete_session_cascades_related_rows(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    round_data = sample_round()
    store.save_round(session.session_id, round_data)
    store.save_message(session.session_id, 1, "sunny_opening", "Be kind.")
    store.log_model_run(session.session_id, 1, "opening", "gpt-5.4")

    store.delete_session(session.session_id)

    assert store.load_session(session.session_id) is None
    assert store.list_messages(session.session_id) == []


def test_delete_user_cascades_sessions_and_related_rows(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    user = store.create_user("Disposable User")
    session = store.create_session(user.user_id)
    round_data = sample_round()
    store.save_round(session.session_id, round_data)
    store.save_message(session.session_id, 1, "sunny_opening", "Be kind.")
    store.log_model_run(session.session_id, 1, "opening", "gpt-5.4")

    store.delete_user(user.user_id)

    assert store.load_user(user.user_id) is None
    assert store.load_session(session.session_id) is None
    assert store.list_sessions(user.user_id) == []
    assert store.list_messages(session.session_id) == []
