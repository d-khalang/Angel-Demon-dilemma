"""Pure transformations for rounds and session-derived state."""

from __future__ import annotations

from angel_demon.memory import rebuild_session_memory
from angel_demon.models import (
    AgentProfile,
    Character,
    ConversationSpeaker,
    Opening,
    Rebuttal,
    ResponseTarget,
    Round,
    SessionState,
)
from angel_demon.scoring import (
    calculate_choice_records,
    calculate_session_alignment,
)


def agent_profile_for(session: SessionState, character: Character) -> AgentProfile:
    return (
        session.sunny_profile
        if character == Character.SUNNY
        else session.crowley_profile
    )


def opponent_profile_for(session: SessionState, character: Character) -> AgentProfile:
    return (
        session.crowley_profile
        if character == Character.SUNNY
        else session.sunny_profile
    )


def speaker_for(character: Character) -> ConversationSpeaker:
    if character == Character.SUNNY:
        return ConversationSpeaker.SUNNY
    return ConversationSpeaker.CROWLEY


def characters_for_target(target: ResponseTarget) -> list[Character]:
    if target == ResponseTarget.SUNNY:
        return [Character.SUNNY]
    if target == ResponseTarget.CROWLEY:
        return [Character.CROWLEY]
    return [Character.SUNNY, Character.CROWLEY]


def replace_session_round(session: SessionState, round_data: Round) -> None:
    for index, existing in enumerate(session.rounds):
        if existing.round_number == round_data.round_number:
            session.rounds[index] = round_data
            return
    session.rounds.append(round_data)
    session.rounds.sort(key=lambda item: item.round_number)


def recent_history(session: SessionState, current_round_number: int) -> list[Round]:
    return [
        round_data
        for round_data in session.rounds
        if round_data.round_number != current_round_number
    ][-3:]


def derive_round_fields(round_data: Round) -> None:
    """Maintain legacy opening/rebuttal fields from the conversation transcript."""
    sunny_texts = _messages_for_speaker(round_data, ConversationSpeaker.SUNNY)
    crowley_texts = _messages_for_speaker(round_data, ConversationSpeaker.CROWLEY)
    if sunny_texts:
        round_data.sunny_opening = Opening(
            character=Character.SUNNY,
            argument=sunny_texts[0],
        )
        round_data.sunny_rebuttal = Rebuttal(
            character=Character.SUNNY,
            argument="\n\n".join(sunny_texts[1:]) or sunny_texts[0],
        )
    if crowley_texts:
        round_data.crowley_opening = Opening(
            character=Character.CROWLEY,
            argument=crowley_texts[0],
        )
        round_data.crowley_rebuttal = Rebuttal(
            character=Character.CROWLEY,
            argument="\n\n".join(crowley_texts[1:]) or crowley_texts[0],
        )


def _messages_for_speaker(
    round_data: Round,
    speaker: ConversationSpeaker,
) -> list[str]:
    return [
        message.content
        for message in round_data.conversation
        if message.speaker == speaker
    ]


def normalize_session_scores(session: SessionState) -> None:
    session.alignment_score = calculate_session_alignment(session.rounds)
    sunny_wins, sunny_losses, crowley_wins, crowley_losses = calculate_choice_records(
        session.rounds
    )
    session.sunny_profile.wins = sunny_wins
    session.sunny_profile.losses = sunny_losses
    session.crowley_profile.wins = crowley_wins
    session.crowley_profile.losses = crowley_losses
    session.user_profile.decision_history = [
        round_data.user_choice
        for round_data in session.rounds
        if round_data.user_choice is not None
    ]


def rebuild_adaptive_state(session: SessionState) -> None:
    session.user_profile, session.sunny_profile, session.crowley_profile = (
        rebuild_session_memory(session.rounds)
    )
    normalize_session_scores(session)
