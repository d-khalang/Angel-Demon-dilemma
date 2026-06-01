#!/usr/bin/env python3
import sys
import json
import sqlite3
import argparse
from pathlib import Path

# Add src/ to python path to import prompt builders from the codebase
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "src"))

from angel_demon.models import (
    Character,
    UserProfile,
    AgentProfile,
    ConversationMessage,
    ConversationSpeaker,
    ResponseTarget,
    Round,
    UserChoice,
)
from angel_demon.agents import build_conversation_turn_messages
from angel_demon.prompts import (
    character_instructions,
    conversation_turn_input,
    JUDGE_INSTRUCTIONS,
    judge_conversation_input,
    USER_MEMORY_INSTRUCTIONS,
    AGENT_MEMORY_INSTRUCTIONS,
)


def get_default_profiles():
    return (
        UserProfile(),
        AgentProfile(character=Character.SUNNY),
        AgentProfile(character=Character.CROWLEY),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Inspect a specific session and round's LLM inputs/outputs."
    )
    parser.add_argument("session_id", type=str, help="The session ID to inspect.")
    parser.add_argument("round_number", type=int, help="The round number to inspect.")
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(PROJECT_ROOT / "data" / "state.db"),
        help="Path to the database.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Load session
    session_row = c.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (args.session_id,)
    ).fetchone()
    if not session_row:
        print(f"Error: Session {args.session_id} not found in database.")
        sys.exit(1)

    # Load all rounds up to the target round to see if we have previous round history
    rounds_rows = c.execute(
        "SELECT * FROM rounds WHERE session_id = ? AND round_number <= ? ORDER BY round_number ASC",
        (args.session_id, args.round_number),
    ).fetchall()

    target_round_row = next(
        (r for r in rounds_rows if r["round_number"] == args.round_number), None
    )
    if not target_round_row:
        print(f"Error: Round {args.round_number} not found for session {args.session_id}.")
        print("Note: The round must be completed/judged and the user choice made to be present in the 'rounds' table.")
        sys.exit(1)

    target_round_data = json.loads(target_round_row["round_data"])
    round_obj = Round.model_validate(target_round_data)

    # Load previous rounds' histories
    history_rounds = []
    for r in rounds_rows:
        if r["round_number"] < args.round_number:
            history_rounds.append(Round.model_validate(json.loads(r["round_data"])))

    # Fetch all messages logged for this round in 'messages' table
    all_messages_rows = c.execute(
        "SELECT * FROM messages WHERE session_id = ? AND round_number = ? ORDER BY id ASC",
        (args.session_id, args.round_number),
    ).fetchall()

    # Fetch model runs metadata for this round
    model_runs_rows = c.execute(
        "SELECT * FROM model_runs WHERE session_id = ? AND round_number = ? ORDER BY id ASC",
        (args.session_id, args.round_number),
    ).fetchall()

    print("=" * 80)
    print(f"INSPECTING SESSION: {args.session_id}")
    print(f"ROUND: {args.round_number}")
    print("=" * 80)

    # 1. Reconstruct profiles at the START of this round.
    # If round is 1, they are default. If round > 1, they are not easily retrievable directly
    # because sessions table only holds the final profiles. Let's warn the user if round > 1.
    if args.round_number == 1:
        user_profile, sunny_profile, crowley_profile = get_default_profiles()
        print("\n[INFO] Round 1: Reconstructing exact starting profiles (defaults).")
    else:
        # Approximate using the final profiles or just note that they are loaded from current state.
        user_profile = UserProfile.model_validate_json(session_row["user_profile"])
        sunny_profile = AgentProfile.model_validate_json(session_row["sunny_profile"])
        crowley_profile = AgentProfile.model_validate_json(session_row["crowley_profile"])
        print("\n[WARNING] Round > 1: Reconstructing prompts using current session profiles as an approximation.")

    # 2. Map of messages in rounds vs all logged messages to detect orphaned/duplicated messages
    official_messages_content = [m.content for m in round_obj.conversation]
    
    print("\n" + "#" * 80)
    print("1. DETECTING CONVERSATION MESSAGES AND ORPHANED TURNS")
    print("#" * 80)
    
    official_db_messages = []
    orphaned_db_messages = []
    
    # We walk through all message rows, seeing which ones match the official round conversation
    # We match by index/content to handle duplicates carefully
    matched_indices = set()
    for row in all_messages_rows:
        content = row["content"]
        role = row["role"]
        
        # Check if it matches any message in official conversation
        found = False
        for idx, m in enumerate(round_obj.conversation):
            if idx not in matched_indices and m.content == content and m.speaker.value == role:
                matched_indices.add(idx)
                official_db_messages.append(row)
                found = True
                break
        if not found:
            if role not in ("judge_verdict", "user_choice"):
                orphaned_db_messages.append(row)

    if orphaned_db_messages:
        print(f"\n[ALERT] Found {len(orphaned_db_messages)} orphaned message(s) in database messages table!")
        print("These messages were generated/sent but discarded (e.g., due to a page refresh or debate restart):")
        for m in orphaned_db_messages:
            print(f"  - [{m['created_at']}] {m['role'].upper()}: {repr(m['content'][:100])}...")
    else:
        print("\nNo orphaned messages detected. All messages matched the final transcript.")

    # 3. Step-by-Step Prompt Reconstruction for official conversation turns
    print("\n" + "#" * 80)
    print("2. CHRONOLOGICAL MODEL INPUTS & OUTPUTS FOR CONVERSATION TURNS")
    print("#" * 80)

    # Reconstruct the transcript incrementally as the debate proceeds
    current_transcript = []
    
    # The first message must be the user's dilemma
    dilemma = round_obj.dilemma
    
    # We walk through official conversation messages
    # Each turn starts with a user message, followed by Sunny and/or Crowley responses
    for idx, msg in enumerate(round_obj.conversation):
        # We need to construct what the prompt would look like for this turn if it's an agent
        if msg.speaker == ConversationSpeaker.USER:
            # User input just appends to transcript
            current_transcript.append(msg)
            print(f"\n--- STEP {idx+1}: USER INPUT ---")
            print(f"Content: {msg.content}")
            print("-" * 50)
            continue
        
        # It's an agent speaker (Sunny or Crowley)
        char = Character.SUNNY if msg.speaker == ConversationSpeaker.SUNNY else Character.CROWLEY
        opponent_char = Character.CROWLEY if char == Character.SUNNY else Character.SUNNY
        
        # The target is determined by the message target in the round
        target = msg.target or ResponseTarget.BOTH
        
        # Reconstruct the prompt using the same build helper from src
        char_profile = sunny_profile if char == Character.SUNNY else crowley_profile
        opp_profile = crowley_profile if char == Character.SUNNY else sunny_profile
        
        # Build turn messages
        # Note: build_conversation_turn_messages takes current_transcript (which has the user message but not this agent's response yet)
        prompt_messages = build_conversation_turn_messages(
            character=char,
            dilemma=dilemma,
            transcript=current_transcript,
            target=target,
            user_profile=user_profile,
            agent_profile=char_profile,
            opponent_profile=opp_profile,
            round_history=history_rounds,
        )
        
        system_content = next(m["content"] for m in prompt_messages if m["role"] == "system")
        user_content = next(m["content"] for m in prompt_messages if m["role"] == "user")
        
        print(f"\n--- STEP {idx+1}: MODEL CALL FOR {char.value.upper()} ---")
        print("\n>>> RECONSTRUCTED SYSTEM INSTRUCTIONS:")
        print(system_content)
        print("\n>>> RECONSTRUCTED USER PROMPT:")
        print(user_content)
        print("\n>>> MODEL RESPONSE (OUTPUT):")
        print(msg.content)
        print("-" * 80)
        
        # Append to our running transcript
        current_transcript.append(msg)

    # 4. Reconstruct Judge Prompt
    print("\n" + "#" * 80)
    print("3. MODEL CALL: JUDGE EVALUATION")
    print("#" * 80)
    
    judge_system = JUDGE_INSTRUCTIONS
    judge_user = judge_conversation_input(dilemma, round_obj.conversation)
    
    print("\n>>> RECONSTRUCTED SYSTEM INSTRUCTIONS:")
    print(judge_system)
    print("\n>>> RECONSTRUCTED USER PROMPT:")
    print(judge_user)
    print("\n>>> MODEL RESPONSE VERDICT (OUTPUT):")
    print(json.dumps(round_obj.verdict.model_dump(), indent=2))
    print("-" * 80)

    # 5. Reconstruct Memory Updates Prompts
    print("\n" + "#" * 80)
    print("4. MODEL CALLS: MEMORY & PROFILE UPDATES")
    print("#" * 80)
    
    # 5.1 User Profile Update
    print("\n--- 4.1 USER PROFILE UPDATE ---")
    user_mem_user_content = (
        f"Current profile JSON:\n{user_profile.model_dump_json()}\n\n"
        f"Latest round JSON:\n{round_obj.model_dump_json()}\n\n"
        "Return the updated user profile fields."
    )
    print("\n>>> RECONSTRUCTED SYSTEM INSTRUCTIONS:")
    print(USER_MEMORY_INSTRUCTIONS)
    print("\n>>> RECONSTRUCTED USER PROMPT:")
    print(user_mem_user_content)
    
    # Fetch final updated profiles from DB to show what they became
    final_user_profile = UserProfile.model_validate_json(session_row["user_profile"])
    print("\n>>> RESULTING UPDATED USER PROFILE:")
    print(json.dumps(final_user_profile.model_dump(), indent=2))
    print("-" * 50)
    
    # 5.2 Agent Profiles Update
    for char in (Character.SUNNY, Character.CROWLEY):
        print(f"\n--- 4.2 AGENT PROFILE UPDATE: {char.value.upper()} ---")
        
        char_profile = sunny_profile if char == Character.SUNNY else crowley_profile
        own_tactics = (
            round_obj.verdict.persuasion_tactics_sunny
            if char == Character.SUNNY
            else round_obj.verdict.persuasion_tactics_crowley
        )
        opponent_tactics = (
            round_obj.verdict.persuasion_tactics_crowley
            if char == Character.SUNNY
            else round_obj.verdict.persuasion_tactics_sunny
        )
        
        agent_mem_user_content = (
            f"Current profile JSON:\n{char_profile.model_dump_json()}\n\n"
            f"User profile JSON:\n{final_user_profile.model_dump_json()}\n\n"
            f"Round JSON:\n{round_obj.model_dump_json()}\n\n"
            f"Own tactics: {own_tactics}\nOpponent tactics: {opponent_tactics}\n"
            "Return the updated agent profile fields."
        )
        print("\n>>> RECONSTRUCTED SYSTEM INSTRUCTIONS:")
        print(AGENT_MEMORY_INSTRUCTIONS)
        print("\n>>> RECONSTRUCTED USER PROMPT:")
        print(agent_mem_user_content)
        
        final_agent_profile = (
            AgentProfile.model_validate_json(session_row["sunny_profile"])
            if char == Character.SUNNY
            else AgentProfile.model_validate_json(session_row["crowley_profile"])
        )
        print(f"\n>>> RESULTING UPDATED {char.value.upper()} PROFILE:")
        print(json.dumps(final_agent_profile.model_dump(), indent=2))
        print("-" * 50)

    # 6. Summary of token usage and latencies from model_runs table
    print("\n" + "#" * 80)
    print("5. TOKEN USAGE & LATENCY METADATA")
    print("#" * 80)
    
    total_in = 0
    total_out = 0
    total_ms = 0
    
    for r in model_runs_rows:
        in_t = r["input_tokens"] or 0
        out_t = r["output_tokens"] or 0
        lat = r["latency_ms"] or 0
        total_in += in_t
        total_out += out_t
        total_ms += lat
        print(
            f"- Call: {r['call_type']:<25} | "
            f"Tokens: In={in_t:<4}, Out={out_t:<4} | "
            f"Latency: {lat:<5}ms | Error: {r['error']}"
        )
    
    print("-" * 80)
    print(f"Total Round Latency: {total_ms / 1000:.2f}s")
    print(f"Total Round Tokens:  Input={total_in}, Output={total_out}")
    print("=" * 80)

    conn.close()


if __name__ == "__main__":
    main()
