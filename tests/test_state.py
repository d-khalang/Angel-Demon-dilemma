from datetime import UTC, datetime

from angel_demon.models import (
    AgentProfile,
    Character,
    Opening,
    Rebuttal,
    Round,
    UserProfile,
    Verdict,
)
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


def store_session_payload() -> tuple[str, int, str, str, str, str, str]:
    now = datetime.now(UTC).isoformat()
    return (
        "legacy-session",
        7,
        UserProfile().model_dump_json(),
        AgentProfile(character=Character.SUNNY).model_dump_json(),
        AgentProfile(character=Character.CROWLEY).model_dump_json(),
        now,
        now,
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


def test_claim_anonymous_session_moves_existing_rounds_to_new_user(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    anonymous_session = store.create_session()
    new_user = store.create_user("Noor")
    round_data = sample_round()
    store.save_round(anonymous_session.session_id, round_data)
    store.save_message(anonymous_session.session_id, 1, "sunny_opening", "Be kind.")
    store.log_model_run(anonymous_session.session_id, 1, "opening", "gpt-5.4")

    transferred = store.claim_anonymous_session(anonymous_session.session_id, new_user.user_id)

    assert transferred is not None
    assert transferred.user_id == new_user.user_id
    assert transferred.rounds[0].dilemma == round_data.dilemma
    assert store.list_sessions(new_user.user_id)[0]["session_id"] == anonymous_session.session_id
    assert store.list_messages(anonymous_session.session_id)[0]["role"] == "sunny_opening"


def test_claim_anonymous_session_rejects_named_user_session(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    first_user = store.create_user("First User")
    second_user = store.create_user("Second User")
    session = store.create_session(first_user.user_id)

    claimed = store.claim_anonymous_session(session.session_id, second_user.user_id)

    assert claimed is not None
    assert claimed.user_id == first_user.user_id


def test_legacy_sessions_schema_is_migrated_without_dropping_data(tmp_path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id      TEXT PRIMARY KEY,
            alignment       INTEGER NOT NULL DEFAULT 0,
            user_profile    TEXT NOT NULL,
            sunny_profile   TEXT NOT NULL,
            crowley_profile TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        """
    )
    session = store_session_payload()
    conn.execute(
        """
        INSERT INTO sessions (
            session_id, alignment, user_profile, sunny_profile, crowley_profile,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        session,
    )
    conn.commit()
    conn.close()

    store = SessionStore(db_path)
    sessions = store.list_sessions()
    users = store.list_users()

    assert len(users) == 1
    assert sessions[0]["session_id"] == session[0]
    assert sessions[0]["user_id"] == users[0].user_id


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
