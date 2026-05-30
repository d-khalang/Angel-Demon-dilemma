import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("data/state.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the local Angel vs Demon SQLite DB.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DB_PATH,
        help="Path to the SQLite database file.",
    )
    args = parser.parse_args()
    db_path = args.db_path

    if not db_path.exists():
        print(
            f"Error: Database file not found at {db_path}. "
            "Make sure to run the app first to generate data."
        )
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("=" * 60)
    print("           SQLITE DATABASE INSPECTOR: state.db")
    print("=" * 60)

    # List tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row["name"] for row in cursor.fetchall()]
    print(f"Tables found: {', '.join(tables)}\n")

    # Quick summaries
    for table in ["users", "sessions", "rounds", "messages", "model_runs"]:
        if table in tables:
            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            count = cursor.fetchone()["count"]
            print(f"- Table '{table}': {count} row(s)")

    print("\n" + "=" * 60)
    print(" 1. LOCAL USERS")
    print("=" * 60)
    if "users" in tables:
        cursor.execute(
            """
            SELECT user_id, display_name, created_at, updated_at
            FROM users
            ORDER BY updated_at DESC
            LIMIT 10
            """
        )
        users = cursor.fetchall()
        if not users:
            print("No users found.")
        for idx, user in enumerate(users, 1):
            print(f"[{idx}] {user['display_name']} ({user['user_id']})")
            print(f"    Created: {user['created_at']}")
            print(f"    Updated: {user['updated_at']}")
            print("-" * 40)
    else:
        print("users table not found.")

    print("\n" + "=" * 60)
    print(" 2. LATEST SESSIONS")
    print("=" * 60)

    if "users" in tables:
        cursor.execute(
            """
            SELECT s.session_id, s.user_id, u.display_name, s.alignment, s.created_at, s.updated_at
            FROM sessions s
            LEFT JOIN users u ON u.user_id = s.user_id
            ORDER BY s.updated_at DESC
            LIMIT 5
            """
        )
    else:
        cursor.execute(
            """
            SELECT session_id, NULL AS user_id, NULL AS display_name,
                   alignment, created_at, updated_at
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT 5
            """
        )
    sessions = cursor.fetchall()
    if not sessions:
        print("No sessions found.")
    for idx, sess in enumerate(sessions, 1):
        print(f"[{idx}] Session ID: {sess['session_id']}")
        print(f"    User: {sess['display_name'] or 'Unknown'} ({sess['user_id']})")
        print(f"    Alignment Score: {sess['alignment']}")
        print(f"    Created: {sess['created_at']}")
        print(f"    Updated: {sess['updated_at']}")
        print("-" * 40)

    print("\n" + "=" * 60)
    print(" 3. LATEST MODEL RUN SUMMARY (Last 5)")
    print("=" * 60)
    if "model_runs" in tables:
        cursor.execute(
            """
            SELECT call_type, model, input_tokens, output_tokens, latency_ms, was_streamed, error
            FROM model_runs
            ORDER BY id DESC
            LIMIT 5
            """
        )
        runs = cursor.fetchall()
        if not runs:
            print("No model runs logged yet.")
        for run in runs:
            streamed = "Yes" if run["was_streamed"] else "No"
            error = f" | Error: {run['error']}" if run["error"] else ""
            print(
                f"- Type: {run['call_type']:<15} | Model: {run['model']:<15} | "
                f"Tokens: In={run['input_tokens'] or 0}, Out={run['output_tokens'] or 0} | "
                f"Latency: {run['latency_ms'] or 0}ms | Streamed: {streamed}{error}"
            )
    else:
        print("model_runs table not found.")

    print("\n" + "=" * 60)
    print(" 4. LATEST DEBATE ROUND VERDICTS")
    print("=" * 60)
    if "rounds" in tables:
        cursor.execute(
            """
            SELECT session_id, round_number, dilemma, round_data
            FROM rounds
            ORDER BY id DESC
            LIMIT 3
            """
        )
        rounds = cursor.fetchall()
        if not rounds:
            print("No rounds found.")
        for r in rounds:
            try:
                data = json.loads(r["round_data"])
                winner = data.get("verdict", {}).get("winner", "Unknown")
                reason = data.get("verdict", {}).get("reason", "")
                print(f"Session: {r['session_id']}")
                print(f"Round #{r['round_number']} Dilemma: {r['dilemma'][:80]}...")
                print(f"Winner: {winner}")
                print(f"Reason: {reason[:120]}...")
                print("-" * 40)
            except Exception as e:
                print(f"Could not parse round data: {e}")
    else:
        print("rounds table not found.")

    conn.close()


if __name__ == "__main__":
    main()
