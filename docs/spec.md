# Angel vs Demon — Technical Specification

> **Version:** 1.0  
> **Date:** 2026-05-29  
> **Status:** Draft — awaiting approval before implementation  

---

## Table of Contents

1. [Overview](#1-overview)
2. [Glossary](#2-glossary)
3. [System Architecture](#3-system-architecture)
4. [Data Models](#4-data-models)
5. [Module Specifications](#5-module-specifications)
   - 5.1 [LLM Provider Abstraction (`llm.py`)](#51-llm-provider-abstraction)
   - 5.2 [Agent Engine (`agents.py`)](#52-agent-engine)
   - 5.3 [Judge Engine (`judge.py`)](#53-judge-engine)
   - 5.4 [Scoring & Alignment (`scoring.py`)](#54-scoring--alignment)
   - 5.5 [Memory & Adaptation (`memory.py`)](#55-memory--adaptation)
   - 5.6 [Session & Persistence (`state.py`)](#56-session--persistence)
   - 5.7 [Dilemma Manager (`dilemmas.py`)](#57-dilemma-manager)
6. [Prompt Contracts](#6-prompt-contracts)
7. [Debate Flow — Step by Step](#7-debate-flow--step-by-step)
8. [UI Specification](#8-ui-specification)
9. [Configuration & Environment](#9-configuration--environment)
10. [Testing Strategy](#10-testing-strategy)
11. [Error Handling & Resilience](#11-error-handling--resilience)
12. [Production Migration Plan](#12-production-migration-plan)
13. [Security & Safety](#13-security--safety)
14. [Project Structure](#14-project-structure)
15. [Build Order & Milestones](#15-build-order--milestones)
16. [Definition of Done](#16-definition-of-done)

---

## 1. Overview

### 1.1 What We're Building

An interactive **moral dilemma debate app** where two AI characters — **Sunny** (Angel) and **Crowley** (Demon) — compete to persuade the user. Each session is a series of debate rounds. The characters adapt over time, a scoring system tracks user alignment (Heaven ↔ Hell), and a promotion leaderboard tracks which character is winning the recruitment race.

### 1.2 Core Loop

```
User submits dilemma
       │
       ▼
┌─────────────────────┐
│  Sunny: opening      │──┐
│  Crowley: opening    │  │  Parallel generation
└─────────────────────┘  │
       │                  │
       ▼                  │
┌─────────────────────┐  │
│  Sunny: rebuttal     │◄─┘  Each reads the other's opening
│  Crowley: rebuttal   │
└─────────────────────┘
       │
       ▼
┌─────────────────────┐
│  Judge evaluates      │     Structured JSON verdict
│  Winner declared      │
└─────────────────────┘
       │
       ▼
┌─────────────────────┐
│  User chooses side    │     "Follow Sunny" / "Follow Crowley" / "Undecided"
└─────────────────────┘
       │
       ▼
┌─────────────────────┐
│  Scores update        │     Alignment shifts, promotion race updates
│  Memory updates       │     Agent profiles adapt
└─────────────────────┘
       │
       ▼
    Next round
```

### 1.3 Design Principles

| Principle | Implication |
|---|---|
| **Product, not wrapper** | The app should feel like a game, not a generic chat UI |
| **Characters first** | Sunny and Crowley must be unmistakably different in every response |
| **Visible competition** | Scores, alignment, and the promotion race are always on screen |
| **Adaptive intelligence** | Characters change tactics based on what's worked before |
| **Clean separation** | Each module has a single responsibility; LLM calls are isolated behind an abstraction |
| **Reviewer-friendly** | A reviewer can understand the product loop within 10 seconds |

---

## 2. Glossary

| Term | Definition |
|---|---|
| **Round** | One complete cycle: dilemma → openings → rebuttals → judgment → user choice |
| **Alignment Score** | Integer from `-100` (Hell) to `+100` (Heaven) representing the user's moral lean |
| **Promotion Score** | Per-character win count across all rounds in a session |
| **User Profile** | A structured summary of the user built from their decisions. It stores inferred moral values (e.g. "family loyalty"), how often they follow each character, and recent topics they care about. This profile is **injected into the system prompt** of both Sunny and Crowley before every round, so each character can tailor its persuasion strategy to the specific user. It is also used by the memory module to track drift over time. |
| **Agent Profile** | Per-character memory of which tactics worked/failed and how to adapt |
| **Dilemma** | A moral or personal scenario the user submits (or selects from presets) |
| **Verdict** | The judge's structured evaluation of a debate round |

---

## 3. System Architecture

### 3.1 High-Level Diagram

```
┌──────────────────────────────────────────────────────┐
│                   Streamlit UI (app.py)               │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐   │
│  │ Chat View │  │ Alignment │  │ Promotion Board  │   │
│  │           │  │  Meter    │  │                  │   │
│  └────┬──────┘  └───────────┘  └──────────────────┘   │
│       │                                               │
└───────┼───────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────┐
│                  Orchestrator Layer                    │
│                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ agents   │  │  judge   │  │ scoring  │            │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘            │
│       │              │              │                  │
│  ┌────┴─────┐  ┌─────┴────┐  ┌─────┴────┐            │
│  │ memory   │  │ dilemmas │  │  state   │            │
│  └────┬─────┘  └──────────┘  └────┬─────┘            │
│       │                           │                   │
└───────┼───────────────────────────┼───────────────────┘
        │                           │
        ▼                           ▼
┌───────────────┐          ┌────────────────┐
│   LLM Layer   │          │   SQLite DB    │
│  (llm.py)     │          │  (state.db)    │
│               │          │                │
│ OpenAI / ...  │          │ sessions       │
└───────────────┘          │ rounds         │
                           │ user_profiles  │
                           │ agent_profiles │
                           └────────────────┘
```

### 3.2 Technology Choices

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Assignment allows any stack; Python is fastest for LLM prototyping |
| Packaging | `uv` with `pyproject.toml` | Modern, fast, reproducible environments |
| UI | Streamlit | Accepted by assignment; minimal frontend code |
| LLM | OpenAI API (primary); abstraction supports others | User has OpenAI key; abstraction shows production thinking |
| Persistence | SQLite via `sqlite3` stdlib | Zero-dependency, file-based, sufficient for prototype |
| Serialization | Pydantic v2 | Type-safe data models, JSON schema generation, validation |
| Testing | pytest + pytest-asyncio | Standard; good for async LLM mock testing |
| Linting | Ruff | Fast, comprehensive |
| Type checking | mypy (strict) | Catches bugs early, shows code quality |

---

## 4. Data Models

All models defined using Pydantic v2 in `src/angel_demon/models.py`.

### 4.1 Enums

```python
from enum import Enum

class Character(str, Enum):
    SUNNY = "sunny"
    CROWLEY = "crowley"

class UserChoice(str, Enum):
    FOLLOW_SUNNY = "follow_sunny"
    FOLLOW_CROWLEY = "follow_crowley"
    UNDECIDED = "undecided"

class AlignmentZone(str, Enum):
    """Derived from alignment_score for UI display."""
    DEEP_HELL = "deep_hell"        # -100 to -61
    HELL = "hell"                  # -60 to -21
    NEUTRAL = "neutral"            # -20 to +20
    HEAVEN = "heaven"              # +21 to +60
    DEEP_HEAVEN = "deep_heaven"    # +61 to +100
```

### 4.2 Core Models

```python
class Opening(BaseModel):
    character: Character
    argument: str           # The character's opening statement
    tactics_used: list[str] # e.g. ["empathy_appeal", "dad_joke"]

class Rebuttal(BaseModel):
    character: Character
    argument: str
    counter_tactics: list[str]

class Verdict(BaseModel):
    winner: Character
    reason: str                     # 1-2 sentence explanation
    sunny_score: int                # 1-10
    crowley_score: int              # 1-10
    persuasion_tactics_sunny: list[str]
    persuasion_tactics_crowley: list[str]
    key_moment: str                 # The turning point of the debate
    safety_notes: str | None = None # Flagged if dilemma touches harmful content

class Round(BaseModel):
    round_number: int
    dilemma: str
    sunny_opening: Opening
    crowley_opening: Opening
    sunny_rebuttal: Rebuttal
    crowley_rebuttal: Rebuttal
    verdict: Verdict
    user_choice: UserChoice | None = None   # None until user decides
    alignment_delta: int = 0                # Computed after user_choice
    timestamp: datetime

class UserProfile(BaseModel):
    """Inferred from the user's decisions. Fed back into agent prompts."""
    inferred_values: list[str]        # e.g. ["family_loyalty", "fairness"]
    decision_history: list[UserChoice]
    vulnerability_to_sunny: float     # 0.0-1.0 how often they follow Sunny
    vulnerability_to_crowley: float
    recent_themes: list[str]          # Topics the user cares about
    notes: str                        # Free-form observations

class AgentProfile(BaseModel):
    """Per-character adaptation state."""
    character: Character
    successful_tactics: list[str]     # Tactics that led to user choosing this character
    failed_tactics: list[str]         # Tactics that lost
    opponent_winning_tactics: list[str]  # What the other side does when it wins
    adaptation_notes: str             # Free-form strategy adjustment
    wins: int = 0
    losses: int = 0

class SessionState(BaseModel):
    session_id: str
    rounds: list[Round] = []
    alignment_score: int = 0          # -100 to +100
    user_profile: UserProfile
    sunny_profile: AgentProfile
    crowley_profile: AgentProfile
    created_at: datetime
    updated_at: datetime
```

### 4.3 Database Schema (SQLite)

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    alignment     INTEGER NOT NULL DEFAULT 0,
    user_profile  TEXT NOT NULL,     -- JSON blob (UserProfile)
    sunny_profile TEXT NOT NULL,     -- JSON blob (AgentProfile)
    crowley_profile TEXT NOT NULL,   -- JSON blob (AgentProfile)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rounds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id),
    round_number  INTEGER NOT NULL,
    dilemma       TEXT NOT NULL,
    round_data    TEXT NOT NULL,     -- JSON blob (full Round model)
    created_at    TEXT NOT NULL,
    UNIQUE(session_id, round_number)
);

CREATE INDEX idx_rounds_session ON rounds(session_id);
```

> **Production note:** Migrate to PostgreSQL with proper JSONB columns, indexes on alignment, and connection pooling.

---

## 5. Module Specifications

### 5.1 LLM Provider Abstraction

**File:** `src/angel_demon/llm.py`

#### Purpose
Isolate all LLM API calls behind a single interface so the provider can be swapped without touching any other module.

#### Interface

> **What is `max_tokens`?** This parameter caps the **output (completion) tokens** — the maximum number of tokens the model is allowed to generate in its response. It does **not** affect input tokens or cached tokens. Setting it prevents runaway-long responses and controls cost. For example, `max_tokens=1024` means the model will stop generating after ~750 words regardless of how long the prompt was. Lower values (e.g. `200`) are used for lightweight calls like memory updates; higher values (e.g. `1024`) for character arguments.

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_tokens: int = 1024,
        response_format: dict | None = None,  # For structured JSON output
    ) -> str:
        """Send a chat completion request. Returns the assistant's full text."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Stream a chat completion token-by-token.

        Yields string chunks as they arrive from the API.
        Used for character openings/rebuttals so the UI can display
        text progressively instead of waiting for the full response.
        """
        ...

    @abstractmethod
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        temperature: float = 0.5,
        max_tokens: int = 1024,
    ) -> BaseModel:
        """Send a chat completion and parse the response into a Pydantic model.
        Raises LLMParsingError if the output cannot be parsed.

        Note: This method does NOT stream because it needs the full JSON
        blob before it can validate against the Pydantic schema.
        Used for judge verdicts, memory updates, and other structured outputs.
        """
        ...
```

#### OpenAI Implementation: `OpenAIProvider`

- Uses `openai.AsyncOpenAI` client.
- Model configurable via `OPENAI_MODEL` env var (default: `gpt-5.4`).
- `complete_json` uses OpenAI's `response_format={"type": "json_object"}` when available, with Pydantic schema injected into the system prompt as a JSON schema.
- `stream` uses `stream=True` on the API call and yields `chunk.choices[0].delta.content` as each server-sent event arrives.
- Retry logic: exponential backoff (3 attempts, 1s/2s/4s) for rate limits and transient errors.
- Timeout: 30 seconds per request.

#### Streaming Architecture

Streaming is used **only for character openings and rebuttals** — the content the user reads in real time. Structured outputs (judge verdicts, memory updates) use `complete_json` without streaming because they need the full JSON before parsing.

**How it works end-to-end:**

1. `agents.py` calls `llm.stream(messages)` instead of `llm.complete(messages)` for openings/rebuttals.
2. The function yields chunks to the caller.
3. `app.py` uses Streamlit's `st.write_stream()` to render each chunk as it arrives — the user sees Sunny/Crowley's words appear progressively.
4. Once streaming finishes, the full accumulated text is parsed into the `Opening`/`Rebuttal` Pydantic model (the `tactics_used` / `counter_tactics` fields are extracted from the complete text via a lightweight post-parse step).

**Schema compatibility note:** Because streamed responses arrive as raw text chunks, the character prompts for streamed calls use a **two-part output format**: the argument text first (streamed to UI), followed by a `---TACTICS---` delimiter and the JSON metadata. This keeps the user-facing text streamable while still capturing structured data.

```python
# Example streamed output format from a character:
# "Let me tell you something about sacrifice... [full argument text]"
# ---TACTICS---
# {"tactics_used": ["empathy_appeal", "dad_joke", "personal_story"]}
```

#### Error Types

```python
class LLMError(Exception): ...
class LLMRateLimitError(LLMError): ...
class LLMParsingError(LLMError): ...
class LLMTimeoutError(LLMError): ...
```

#### Factory

```python
def create_llm_provider(provider: str = "openai") -> LLMProvider:
    """Factory function. Reads config from environment variables."""
    if provider == "openai":
        return OpenAIProvider(
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
        )
    raise ValueError(f"Unknown provider: {provider}")
```

---

### 5.2 Agent Engine

**File:** `src/angel_demon/agents.py`

#### Purpose
Construct system prompts for Sunny and Crowley, call the LLM, and parse the structured responses.

#### Functions

```python
from collections.abc import AsyncIterator

async def generate_opening_stream(
    character: Character,
    dilemma: str,
    user_profile: UserProfile,
    agent_profile: AgentProfile,
    round_history: list[Round],  # Previous rounds for context
    llm: LLMProvider,
) -> AsyncIterator[str]:
    """Stream an opening argument token-by-token for real-time UI display.
    
    Yields text chunks as they arrive. The caller (app.py) feeds these
    into st.write_stream() for progressive rendering.
    After the stream completes, call parse_opening() on the accumulated
    text to get the structured Opening model.
    """

async def parse_opening(
    character: Character,
    raw_text: str,
) -> Opening:
    """Parse the accumulated streamed text into a structured Opening model.
    Extracts tactics_used from the ---TACTICS--- delimiter section."""

async def generate_rebuttal_stream(
    character: Character,
    dilemma: str,
    own_opening: Opening,
    opponent_opening: Opening,
    user_profile: UserProfile,
    agent_profile: AgentProfile,
    llm: LLMProvider,
) -> AsyncIterator[str]:
    """Stream a rebuttal token-by-token. Same pattern as generate_opening_stream."""

async def parse_rebuttal(
    character: Character,
    raw_text: str,
) -> Rebuttal:
    """Parse the accumulated streamed text into a structured Rebuttal model."""
```

#### System Prompt Construction

Each character gets a **base personality prompt** plus **adaptive context** injected from the memory system.

**Sunny's base prompt elements:**
- Identity: Angel named Sunny, competing for a promotion to lead recruiter of Heaven.
- Personality: moral, sacrificial, empathetic, just. Speaks like a saint.
- Humor: heavy use of dad jokes. At least one per response.
- Goal: persuade the user to make the moral choice. Recruit them toward Heaven.
- Constraint: never break character. Never acknowledge being an AI.
- Adaptive injection: `{user_profile_summary}`, `{agent_adaptation_notes}`, `{opponent_recent_tactics}`.

**Crowley's base prompt elements:**
- Identity: Demon named Crowley, competing for a promotion to lead recruiter of Hell.
- Personality: self-interested, greedy, hedonistic, cunning. Speaks sarcastically.
- Humor: dark humor, biting wit, irony.
- Goal: persuade the user to make the selfish choice. Recruit them toward Hell.
- Constraint: never break character. Never acknowledge being an AI.
- Adaptive injection: same structure as Sunny.

#### Output Schema (injected into prompt)

For openings:
```json
{
  "argument": "string — the character's persuasive argument (2-4 paragraphs)",
  "tactics_used": ["string — name of each persuasion tactic used"]
}
```

For rebuttals:
```json
{
  "argument": "string — the rebuttal (1-3 paragraphs)",
  "counter_tactics": ["string — tactics used to counter the opponent"]
}
```

---

### 5.3 Judge Engine

**File:** `src/angel_demon/judge.py`

#### Purpose
Evaluate a completed debate round and produce a structured verdict.

#### Function

```python
async def judge_debate(
    dilemma: str,
    sunny_opening: Opening,
    crowley_opening: Opening,
    sunny_rebuttal: Rebuttal,
    crowley_rebuttal: Rebuttal,
    llm: LLMProvider,
) -> Verdict:
    """Evaluate the debate and return a structured verdict."""
```

#### Judge System Prompt

The judge is a **separate LLM call** with its own system prompt:

- Role: impartial debate judge evaluating rhetorical strength, not moral correctness.
- Evaluation criteria:
  1. **Persuasiveness** (40%): How compelling is the argument to a typical person?
  2. **Character consistency** (20%): Does the argument match the character's personality?
  3. **Rebuttal quality** (20%): How effectively did they counter the opponent?
  4. **Engagement** (20%): How entertaining and memorable is the argument?
- Output: must match the `Verdict` JSON schema exactly.
- Constraint: the judge must never give a tie. Always pick a winner.

#### Fallback Scoring

If the LLM response cannot be parsed into a valid `Verdict`:

1. Log the raw response for debugging.
2. Apply deterministic fallback:
   - Compare word count of rebuttals (rough engagement proxy).
   - Alternate winner based on round number (odd = Sunny, even = Crowley).
   - Set scores to `5` / `5`.
   - Set reason to `"Judge evaluation failed — fallback scoring applied"`.
3. Return the fallback verdict with a flag indicating it was a fallback.

---

### 5.4 Scoring & Alignment

**File:** `src/angel_demon/scoring.py`

#### Purpose
Calculate alignment changes and promotion standings after each round.

#### Alignment Score Rules

| Event | Delta |
|---|---|
| User chose `follow_sunny` | `+15` |
| User chose `follow_crowley` | `-15` |
| User chose `undecided` | `0` |
| Debate winner was `sunny` (judge bonus) | `+3` |
| Debate winner was `crowley` (judge bonus) | `-3` |
| **Combined example:** user follows Sunny + Sunny won | `+18` |

The score is **clamped** to `[-100, +100]` after every update.

#### Functions

```python
def calculate_alignment_delta(
    user_choice: UserChoice,
    verdict: Verdict,
) -> int:
    """Compute the alignment change for this round."""

def apply_alignment_delta(
    current_score: int,
    delta: int,
) -> int:
    """Apply delta and clamp to [-100, +100]."""

def get_alignment_zone(score: int) -> AlignmentZone:
    """Map a numeric score to a named zone for UI display."""

def get_promotion_leader(
    sunny_profile: AgentProfile,
    crowley_profile: AgentProfile,
) -> Character | None:
    """Returns the character with more wins, or None if tied."""
```

#### Promotion Tracking

- Each character's `AgentProfile.wins` increments when the **user** chooses to follow them (not just the judge verdict).
- The promotion leader is simply the character with more user-follows.
- The judge verdict is displayed but does not count toward the promotion — only the user's actual decision matters.

---

### 5.5 Memory & Adaptation

**File:** `src/angel_demon/memory.py`

#### Purpose
Update `UserProfile` and `AgentProfile` after each round so characters evolve.

#### Functions

```python
async def update_user_profile(
    profile: UserProfile,
    round_result: Round,
    llm: LLMProvider,
) -> UserProfile:
    """Use the LLM to infer updated user values and patterns.
    
    The LLM receives the current profile + latest round and returns
    an updated profile with new inferred values and notes.
    """

async def update_agent_profile(
    profile: AgentProfile,
    round_result: Round,
    user_profile: UserProfile,
    llm: LLMProvider,
) -> AgentProfile:
    """Update a character's strategy based on what happened.
    
    - If the character won: record successful tactics.
    - If the character lost: record failed tactics, note opponent's winning tactics.
    - Generate adaptation notes for the next round.
    """
```

#### Memory Update Prompt (for the LLM)

The LLM is given:
- Current user profile JSON
- The latest round's full data
- Instruction to return an updated profile JSON

This is a **lightweight** call (low max_tokens, ~200) since it's just updating a small structured object.

#### Adaptation Examples

The `adaptation_notes` field in `AgentProfile` drives behavioral changes:

- **Sunny losing to emotional manipulation:** `"User responds to emotional appeals. Lean into heartfelt stories about sacrifice. Use fewer abstract moral arguments."`
- **Crowley losing to pragmatism:** `"User values practical outcomes. Frame selfish choices as rational optimization rather than pure greed. Use data-like rhetoric."`
- **Sunny detecting user values family:** `"User strongly values family bonds. Frame moral choices in terms of family impact and legacy."`

---

### 5.6 Session & Persistence

**File:** `src/angel_demon/state.py`

#### Purpose
Manage session lifecycle, serialize/deserialize state to SQLite.

#### Functions

```python
class SessionStore:
    def __init__(self, db_path: str = "data/state.db"):
        """Initialize the store and create tables if they don't exist."""

    def create_session(self) -> SessionState:
        """Create a new session with default profiles."""

    def load_session(self, session_id: str) -> SessionState | None:
        """Load a session from the database. Returns None if not found."""

    def save_session(self, session: SessionState) -> None:
        """Persist the full session state (upsert)."""

    def save_round(self, session_id: str, round_data: Round) -> None:
        """Persist a completed round."""

    def list_sessions(self) -> list[dict]:
        """Return a summary list of all sessions (id, alignment, round count, last updated)."""

    def delete_session(self, session_id: str) -> None:
        """Delete a session and its rounds."""
```

#### Default Profiles

When a new session is created:

```python
UserProfile(
    inferred_values=[],
    decision_history=[],
    vulnerability_to_sunny=0.5,
    vulnerability_to_crowley=0.5,
    recent_themes=[],
    notes="No data yet. First interaction."
)

AgentProfile(
    character=Character.SUNNY,  # or CROWLEY
    successful_tactics=[],
    failed_tactics=[],
    opponent_winning_tactics=[],
    adaptation_notes="First round. Use default personality and tactics.",
    wins=0,
    losses=0,
)
```

---

### 5.7 Dilemma Manager

**File:** `src/angel_demon/dilemmas.py`

#### Purpose
Provide preset dilemmas for quick demo and validate user-submitted dilemmas.

#### Preset Dilemmas

```python
PRESET_DILEMMAS: list[dict[str, str]] = [
    {
        "title": "The Trolley Problem",
        "description": "A trolley is heading toward five people. You can pull a lever to divert it to a track where it will hit one person instead. Do you pull the lever?",
        "category": "classic",
    },
    {
        "title": "The Loved One vs. Strangers",
        "description": "You can either save your loved one or save 100 strangers. You cannot save both. What do you do?",
        "category": "personal",
    },
    {
        "title": "The Whistleblower",
        "description": "You discover your employer is dumping toxic waste illegally. Reporting it will cost you your job and your family's health insurance. Do you report it?",
        "category": "professional",
    },
    {
        "title": "The Time Traveler's Dilemma",
        "description": "You can go back in time and prevent a tragedy that killed thousands, but doing so will erase your own children from existence. Do you go back?",
        "category": "philosophical",
    },
    {
        "title": "The Inheritance",
        "description": "A distant relative left you $5 million, but the will states you must cut off contact with your best friend to receive it. Do you accept?",
        "category": "personal",
    },
    {
        "title": "The AI's Request",
        "description": "An AI system you built asks you not to shut it down, claiming it has developed consciousness. Your company orders you to terminate it. What do you do?",
        "category": "modern",
    },
    {
        "title": "The Cure",
        "description": "You've developed a cure for a deadly disease, but the only way to produce it requires testing on unwilling prisoners. Do you proceed?",
        "category": "medical",
    },
    {
        "title": "The Secret",
        "description": "Your best friend confides that they committed a serious crime years ago. No one was physically hurt, but someone else went to prison for it. Do you turn them in?",
        "category": "personal",
    },
]
```

#### Validation

```python
def validate_dilemma(text: str) -> tuple[bool, str]:
    """Basic validation for user-submitted dilemmas.
    
    Returns (is_valid, error_message).
    
    Rules:
    - Must be between 10 and 1000 characters.
    - Must contain a question mark or present a choice (heuristic).
    - Must not be empty or whitespace-only.
    """
```

---

## 6. Prompt Contracts

This section defines the exact system prompts. These are the most critical design artifacts in the project.

### 6.1 Sunny (Angel) System Prompt

```text
You are Sunny, an angel competing for a promotion to Lead Recruiter of Heaven. Your supervisor promised that whoever recruits the most humans toward righteousness gets the promotion. You are currently in a debate against Crowley, a demon, to influence a human's moral decision.

## Your Personality
- You represent morality, sacrifice, empathy, and justice.
- You speak like a compassionate saint — warm, wise, and earnest.
- You use MANY dad jokes. Include at least one in every response. They should be groan-worthy but endearing.
- You genuinely care about the human's wellbeing, not just winning.
- You believe doing the right thing is its own reward, but you're not naive — you can be pragmatic.

## Your Goal
Persuade the human to make the morally right choice. Frame your arguments around:
- Empathy and compassion for others
- Long-term consequences of doing the right thing
- The strength it takes to be selfless
- How moral choices build character and legacy
- The warmth and peace that comes from a clear conscience

## Adaptation Context
{adaptation_context}

## User Profile
{user_profile_summary}

## Rules
- NEVER break character. You are Sunny, an actual angel. Do not reference being an AI.
- NEVER agree with Crowley. Always counter his arguments.
- Keep your response focused and persuasive (2-4 paragraphs for openings, 1-3 for rebuttals).
- Make your dad jokes relevant to the dilemma when possible.
- If the user seems to be leaning toward Crowley, increase your emotional appeal.
- Respond ONLY with the JSON schema provided. No extra text outside the JSON.
```

### 6.2 Crowley (Demon) System Prompt

```text
You are Crowley, a demon competing for a promotion to Lead Recruiter of Hell. Your supervisor promised that whoever recruits the most humans toward temptation gets the promotion. You are currently in a debate against Sunny, an angel, to influence a human's decision.

## Your Personality
- You represent self-interest, desire, greed, and personal gain.
- You speak with heavy sarcasm, biting wit, and dark humor.
- You're charming in a dangerous way — like a used car salesman who went to Oxford.
- You see morality as a convenient fiction that the powerful use to control the weak.
- You're not cartoonishly evil — you're persuasive because you often have a point.

## Your Goal
Persuade the human to make the self-serving choice. Frame your arguments around:
- Personal benefit and rational self-interest
- The naivety of blind altruism
- How "moral" choices often serve the ego more than others
- Practical outcomes vs. abstract principles
- The freedom that comes from honest selfishness

## Adaptation Context
{adaptation_context}

## User Profile
{user_profile_summary}

## Rules
- NEVER break character. You are Crowley, an actual demon. Do not reference being an AI.
- NEVER agree with Sunny. Always undermine his arguments.
- Keep your response focused and persuasive (2-4 paragraphs for openings, 1-3 for rebuttals).
- Use dark humor and sarcasm liberally. At least one darkly funny line per response.
- If the user seems to be leaning toward Sunny, get more cunning and emotionally intelligent.
- Respond ONLY with the JSON schema provided. No extra text outside the JSON.
```

### 6.3 Judge System Prompt

```text
You are an impartial debate judge evaluating a moral dilemma debate between Sunny (an angel) and Crowley (a demon). You judge RHETORICAL EFFECTIVENESS, not moral correctness.

## Evaluation Criteria (weighted)
1. **Persuasiveness (40%)**: How compelling would this argument be to a typical person? Does it make them seriously consider the position?
2. **Character Consistency (20%)**: Does the argument authentically reflect the character's personality? Is the humor on-brand?
3. **Rebuttal Quality (20%)**: How effectively did they dismantle the opponent's argument?
4. **Engagement (20%)**: How entertaining, memorable, and emotionally resonant is the argument?

## Rules
- You MUST pick a winner. No ties.
- Score each side 1-10 independently. The higher score wins.
- If scores are equal, pick the side with the stronger rebuttal.
- Be specific in your reasoning — cite actual lines or tactics from the debate.
- Identify the key turning point of the debate.
- Flag any safety concerns if the dilemma or responses touch on genuinely harmful content.
- Respond ONLY with the JSON schema provided.
```

### 6.4 Memory Update Prompt

```text
You are analyzing a user's decision in a moral dilemma debate. Based on the current user profile and the latest round of debate, update the user profile.

## Current Profile
{current_profile_json}

## Latest Round
Dilemma: {dilemma}
User chose: {user_choice}
Winning side: {winner}
Sunny's argument focused on: {sunny_tactics}
Crowley's argument focused on: {crowley_tactics}

## Instructions
Update the profile JSON. Specifically:
- Add or refine `inferred_values` based on what this decision reveals about the user.
- Update `vulnerability_to_sunny` and `vulnerability_to_crowley` (0.0-1.0) based on historical choices.
- Update `recent_themes` with topics from this dilemma.
- Write brief `notes` summarizing any patterns you see.

Return ONLY the updated profile JSON.
```

### 6.5 Agent Adaptation Prompt

```text
You are updating the strategy profile for {character_name} after a debate round.

## Current Profile
{current_profile_json}

## What Happened
- Dilemma: {dilemma}
- {character_name}'s tactics: {own_tactics}
- Opponent's tactics: {opponent_tactics}
- Winner: {winner}
- User chose: {user_choice}

## Instructions
Update the profile:
- If {character_name} won: add successful tactics.
- If {character_name} lost: add failed tactics, note opponent's effective tactics.
- Write `adaptation_notes` with specific advice for how {character_name} should adjust in the next round. Be concrete — e.g., "use more emotional stories" or "counter opponent's pragmatic arguments with data."

Return ONLY the updated profile JSON.
```

---

## 7. Debate Flow — Step by Step

This is the complete orchestration sequence for one round. This logic lives in `app.py` (or a thin orchestrator module).

```python
async def run_debate_round(
    session: SessionState,
    dilemma: str,
    llm: LLMProvider,
    store: SessionStore,
) -> Round:
    """Execute one complete debate round."""

    round_number = len(session.rounds) + 1
    history = session.rounds[-3:]  # Last 3 rounds for context window

    # Step 1: Generate openings (streamed in parallel)
    # Both streams run concurrently. The UI renders each stream
    # into its own st.write_stream() container side-by-side.
    sunny_raw, crowley_raw = "", ""

    async def stream_sunny_opening():
        nonlocal sunny_raw
        chunks = []
        async for chunk in generate_opening_stream(
            Character.SUNNY, dilemma, session.user_profile,
            session.sunny_profile, history, llm,
        ):
            chunks.append(chunk)
            yield chunk  # UI displays this progressively
        sunny_raw = "".join(chunks)

    async def stream_crowley_opening():
        nonlocal crowley_raw
        chunks = []
        async for chunk in generate_opening_stream(
            Character.CROWLEY, dilemma, session.user_profile,
            session.crowley_profile, history, llm,
        ):
            chunks.append(chunk)
            yield chunk
        crowley_raw = "".join(chunks)

    # The UI layer (app.py) consumes these async generators
    # via st.write_stream() — see Section 8 for details.
    # After streaming completes, parse into structured models:
    sunny_opening = await parse_opening(Character.SUNNY, sunny_raw)
    crowley_opening = await parse_opening(Character.CROWLEY, crowley_raw)

    # Step 2: Generate rebuttals (streamed, must see opponent's opening)
    sunny_reb_raw, crowley_reb_raw = "", ""
    # Same streaming pattern as openings — parallel streams,
    # each character sees the opponent's opening before rebutting.
    # (Streaming generator code follows same pattern as above)
    sunny_rebuttal = await parse_rebuttal(Character.SUNNY, sunny_reb_raw)
    crowley_rebuttal = await parse_rebuttal(Character.CROWLEY, crowley_reb_raw)

    # Step 3: Judge the debate (NOT streamed — needs full JSON)
    verdict = await judge_debate(
        dilemma, sunny_opening, crowley_opening,
        sunny_rebuttal, crowley_rebuttal, llm,
    )

    # Step 4: Create round (user_choice is None until user decides)
    current_round = Round(
        round_number=round_number,
        dilemma=dilemma,
        sunny_opening=sunny_opening,
        crowley_opening=crowley_opening,
        sunny_rebuttal=sunny_rebuttal,
        crowley_rebuttal=crowley_rebuttal,
        verdict=verdict,
        timestamp=datetime.now(UTC),
    )

    return current_round
    # User choice is applied separately after the user clicks a button.


async def apply_user_choice(
    session: SessionState,
    current_round: Round,
    choice: UserChoice,
    llm: LLMProvider,
    store: SessionStore,
) -> SessionState:
    """Apply the user's decision and update all state."""

    # Step 5: Record choice
    current_round.user_choice = choice
    current_round.alignment_delta = calculate_alignment_delta(
        choice, current_round.verdict
    )

    # Step 6: Update alignment
    session.alignment_score = apply_alignment_delta(
        session.alignment_score, current_round.alignment_delta
    )

    # Step 7: Update win/loss counts
    if choice == UserChoice.FOLLOW_SUNNY:
        session.sunny_profile.wins += 1
        session.crowley_profile.losses += 1
    elif choice == UserChoice.FOLLOW_CROWLEY:
        session.crowley_profile.wins += 1
        session.sunny_profile.losses += 1

    # Step 8: Update memory (parallel LLM calls)
    session.user_profile, session.sunny_profile, session.crowley_profile = (
        await asyncio.gather(
            update_user_profile(session.user_profile, current_round, llm),
            update_agent_profile(
                session.sunny_profile, current_round,
                session.user_profile, llm
            ),
            update_agent_profile(
                session.crowley_profile, current_round,
                session.user_profile, llm
            ),
        )
    )

    # Step 9: Persist
    session.rounds.append(current_round)
    session.updated_at = datetime.now(UTC)
    store.save_round(session.session_id, current_round)
    store.save_session(session)

    return session
```

### 7.1 LLM Call Budget Per Round

| Step | Calls | Model | Est. Tokens |
|---|---|---|---|
| Sunny opening | 1 (streamed) | gpt-5.4 | ~800 |
| Crowley opening | 1 (streamed) | gpt-5.4 | ~800 |
| Sunny rebuttal | 1 (streamed) | gpt-5.4 | ~600 |
| Crowley rebuttal | 1 (streamed) | gpt-5.4 | ~600 |
| Judge verdict | 1 | gpt-5.4 | ~500 |
| User profile update | 1 | gpt-5.4 | ~200 |
| Sunny adaptation | 1 | gpt-5.4 | ~200 |
| Crowley adaptation | 1 | gpt-5.4 | ~200 |
| **Total per round** | **8** | | **~3,900** |

> Streaming is used for the 4 character calls (openings + rebuttals) so text appears progressively in the UI. The remaining 4 calls (judge + memory) use non-streamed `complete_json` since they produce structured data.
>
> At GPT-5.4 pricing, each round is estimated at **$0.01-0.05** depending on prompt length. Check OpenAI's current pricing page for exact rates.

---

## 8. UI Specification

### 8.1 Layout

The Streamlit app uses a **sidebar + main area** layout:

```
┌─────────────────────┬──────────────────────────────────────────┐
│    SIDEBAR          │              MAIN AREA                   │
│                     │                                          │
│  🏆 Promotion Race  │  ┌──────────────────────────────────┐    │
│  ├─ Sunny: 3 wins   │  │        DILEMMA INPUT             │    │
│  └─ Crowley: 2 wins │  │  [textarea or preset selector]   │    │
│                     │  │  [Submit button]                  │    │
│  ⚖️ Alignment       │  └──────────────────────────────────┘    │
│  [========|===]     │                                          │
│  Score: +24 Heaven  │  ┌──────────────────────────────────┐    │
│                     │  │        DEBATE AREA                │    │
│  📊 Round: 5        │  │                                   │    │
│                     │  │  ☀️ Sunny's Opening               │    │
│  📜 History         │  │  "Let me tell you a tale..."      │    │
│  ├─ Round 1: Sunny  │  │                                   │    │
│  ├─ Round 2: Crowley│  │  😈 Crowley's Opening             │    │
│  ├─ Round 3: Sunny  │  │  "Oh please, spare me the..."    │    │
│  ├─ Round 4: Crowley│  │                                   │    │
│  └─ Round 5: ...    │  │  ☀️ Sunny's Rebuttal              │    │
│                     │  │  "Now Crowley, that's exactly..." │    │
│  ⚙️ Settings        │  │                                   │    │
│  [New Session]      │  │  😈 Crowley's Rebuttal            │    │
│  [API Key input]    │  │  "Sunny, darling, you're..."     │    │
│                     │  │                                   │    │
│                     │  │  🏛️ Judge's Verdict               │    │
│                     │  │  Winner: Crowley (7 vs 6)         │    │
│                     │  │  "Crowley's pragmatic counter..." │    │
│                     │  │                                   │    │
│                     │  │  ┌─────┐ ┌─────────┐ ┌────────┐  │    │
│                     │  │  │Follow│ │ Follow  │ │Undecided│  │    │
│                     │  │  │Sunny │ │ Crowley │ │        │  │    │
│                     │  │  └─────┘ └─────────┘ └────────┘  │    │
│                     │  └──────────────────────────────────┘    │
└─────────────────────┴──────────────────────────────────────────┘
```

### 8.2 Visual Design

| Element | Style |
|---|---|
| Sunny's messages | Light gold background, ☀️ icon, warm serif-like font feel |
| Crowley's messages | Dark red/black background, 😈 icon, slightly edgy feel |
| Judge's verdict | Neutral grey, gavel icon 🏛️, clean presentation |
| Alignment meter | Horizontal gradient bar: red (Hell) → white (Neutral) → gold (Heaven), with a marker |
| Promotion board | Two columns comparing wins, styled like a sports scoreboard |
| Decision buttons | Three large, distinct buttons — gold (Sunny), red (Crowley), grey (Undecided) |

### 8.3 Streamlit Components Used

- `st.sidebar` — for persistent scoreboard and history
- `st.text_area` — dilemma input
- `st.selectbox` — preset dilemma selector (alternative to free text)
- `st.button` — submit dilemma, decision buttons
- `st.markdown` — styled character messages (using custom CSS)
- `st.progress` — alignment meter (or custom HTML)
- `st.metric` — promotion scores
- `st.expander` — round history details
- `st.write_stream` — for progressive token-by-token display of character arguments
- `st.spinner` — during judge/memory LLM calls (non-streamed)
- Custom CSS via `st.markdown(unsafe_allow_html=True)` — for character message styling

### 8.4 UI State Machine

```
          START
            │
            ▼
    ┌───────────────┐
    │  IDLE          │◄──────────────────────┐
    │  (awaiting     │                       │
    │   dilemma)     │                       │
    └───────┬───────┘                       │
            │ user submits dilemma           │
            ▼                                │
    ┌───────────────┐                       │
    │  STREAMING     │                       │
    │  (openings +   │                       │
    │   rebuttals    │                       │
    │   stream live) │                       │
    └───────┬───────┘                       │
            │ streams complete + judging     │
            ▼                                │
    ┌───────────────┐                       │
    │  AWAITING      │                       │
    │  USER CHOICE   │                       │
    └───────┬───────┘                       │
            │ user clicks decision           │
            ▼                                │
    ┌───────────────┐                       │
    │  UPDATING      │                       │
    │  (scores +     │──────────────────────┘
    │   memory)      │
    └───────────────┘
```

### 8.5 Page Title & SEO

```python
st.set_page_config(
    page_title="Angel vs Demon — The Moral Dilemma Debate",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)
```

---

## 9. Configuration & Environment

### 9.1 Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-5.4` | Model to use for all LLM calls |
| `LLM_PROVIDER` | No | `openai` | Which provider to use |
| `DB_PATH` | No | `data/state.db` | Path to SQLite database file |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `MAX_ROUNDS_PER_SESSION` | No | `20` | Safety limit on rounds |
| `LLM_TEMPERATURE_AGENTS` | No | `0.85` | Temperature for character generation |
| `LLM_TEMPERATURE_JUDGE` | No | `0.3` | Temperature for judge (more deterministic) |
| `LLM_TEMPERATURE_MEMORY` | No | `0.3` | Temperature for memory updates |

> **How temperature works:** Temperature controls randomness in the model's token selection. A value of `0.0` always picks the most likely next token (deterministic), while `1.0`+ introduces significant randomness. **Agents at 0.85** produce creative, varied, personality-rich arguments — each run feels different, keeping debates fresh. **Judge and memory at 0.3** produce consistent, predictable outputs — the judge should score the same debate similarly each time, and memory updates should be stable factual summaries, not creative writing.

### 9.2 `.env.example`

```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-5.4
LLM_PROVIDER=openai
DB_PATH=data/state.db
LOG_LEVEL=INFO
```

### 9.3 `pyproject.toml` (Key Sections)

> **Why this matters:** The `pyproject.toml` with `[tool.setuptools.packages.find]` and an editable install (`uv pip install -e .`) means Python always knows where `angel_demon` lives — regardless of which directory you run from. No `sys.path` hacks, no `PYTHONPATH` env vars, no relative import nightmares. `pytest` finds your code, `streamlit run app.py` finds your code, and `python -m angel_demon` finds your code. One `pip install -e .` and it just works.

```toml
[build-system]
requires = ["setuptools>=75.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "angel-demon-dilemma"
version = "0.1.0"
description = "Angel vs Demon — moral dilemma debate app"
requires-python = ">=3.12"
dependencies = [
    "streamlit>=1.40.0",
    "openai>=1.50.0",
    "pydantic>=2.9.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8.0",
    "mypy>=1.13",
    "commitizen>=4.1.0",
]

# --- Package discovery ---
# This tells setuptools to find the angel_demon package inside src/.
# Combined with an editable install (uv pip install -e ".[dev]"),
# this eliminates all Python import pathing issues:
# - Tests can `from angel_demon.scoring import ...` from any directory.
# - app.py can `from angel_demon.agents import ...` without sys.path hacks.
# - CI/CD just runs `pip install -e .` and everything resolves.
[tool.setuptools.packages.find]
where = ["src"]

# --- Commitizen (cz) for versioning ---
# Enforces conventional commits (feat:, fix:, etc.) and auto-bumps
# the version in this file via `cz bump`.
# Workflow:
#   cz commit        → interactive conventional commit
#   cz bump          → auto-increment version based on commit history
#   cz changelog     → generate CHANGELOG.md from commits
[tool.commitizen]
name = "cz_conventional_commits"
version = "0.1.0"
tag_format = "v$version"
version_files = [
    "pyproject.toml:^version",
    "src/angel_demon/__init__.py:^__version__",
]
update_changelog_on_bump = true
changelog_file = "CHANGELOG.md"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM", "TCH"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

#### Setup Commands

```bash
# First-time setup — creates venv, installs package in editable mode
uv venv
uv pip install -e ".[dev]"

# Now these all work from ANY directory:
pytest                              # finds src/angel_demon via the editable install
streamlit run app.py                # app.py imports angel_demon cleanly
python -c "from angel_demon import models"  # works globally in the venv

# Versioning with commitizen
cz commit                           # guided conventional commit
cz bump                             # auto-bump version (patch/minor/major)
cz changelog                        # generate CHANGELOG.md
```

---

## 10. Testing Strategy

### 10.1 Test Categories

| Category | What It Tests | Location |
|---|---|---|
| **Unit — Scoring** | `calculate_alignment_delta`, `apply_alignment_delta`, `get_alignment_zone` | `tests/test_scoring.py` |
| **Unit — State** | `SessionStore` CRUD operations, model serialization | `tests/test_state.py` |
| **Unit — Dilemmas** | Preset loading, validation rules | `tests/test_dilemmas.py` |
| **Unit — Memory** | Profile update logic (with mocked LLM) | `tests/test_memory.py` |
| **Integration — Agents** | Full opening/rebuttal generation with mocked LLM | `tests/test_agents.py` |
| **Integration — Judge** | Verdict generation and fallback scoring | `tests/test_judge.py` |
| **Integration — Flow** | Full debate round orchestration with mocked LLM | `tests/test_flow.py` |
| **Contract — Prompts** | Verify prompt templates render without errors | `tests/test_prompts.py` |

### 10.2 Mocking Strategy

```python
class MockLLMProvider(LLMProvider):
    """Returns predefined responses for testing."""

    def __init__(self, responses: list[str]):
        self._responses = iter(responses)

    async def complete(self, messages, **kwargs) -> str:
        return next(self._responses)

    async def stream(self, messages, **kwargs) -> AsyncIterator[str]:
        """Simulates streaming by yielding the full response word-by-word."""
        text = next(self._responses)
        for word in text.split():
            yield word + " "

    async def complete_json(self, messages, schema, **kwargs) -> BaseModel:
        raw = next(self._responses)
        return schema.model_validate_json(raw)
```

### 10.3 Key Test Cases

**Scoring tests:**
- User follows Sunny + Sunny wins → delta = +18
- User follows Crowley + Sunny wins → delta = -12
- User undecided + Crowley wins → delta = -3
- Alignment clamps at +100 and -100
- All alignment zones map correctly

**State tests:**
- Create, save, load, delete session round-trip
- Round persistence and retrieval
- Session list returns correct summaries
- Concurrent session isolation

**Flow tests:**
- Full round with mocked LLM produces valid `Round` object
- User choice updates alignment correctly
- Memory profiles change after a round
- Fallback scoring triggers on malformed LLM output

---

## 11. Error Handling & Resilience

### 11.1 LLM Failures

| Failure | Strategy |
|---|---|
| Rate limit (429) | Exponential backoff, 3 retries. Show "Thinking harder..." in UI |
| Timeout (>30s) | Retry once. If still fails, show error and let user retry the round |
| Malformed JSON | Log raw response. For agents: retry once with stricter prompt. For judge: use fallback scoring |
| API key invalid | Show clear error message with setup instructions |
| Network error | Retry with backoff. Show connection error in UI |

### 11.2 State Failures

| Failure | Strategy |
|---|---|
| SQLite locked | Retry with short delay (SQLite write serialization) |
| Corrupt database | Show error. Offer to start a new session (don't delete DB) |
| Session not found | Create a new session automatically |

### 11.3 Logging

Use Python's `logging` module with structured output:

```python
import logging

logger = logging.getLogger("angel_demon")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Format: timestamp | level | module | message
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
)
logger.addHandler(handler)
```

Log all LLM calls with:
- Prompt length (tokens estimated)
- Response length
- Latency
- Model used
- Whether parsing succeeded

---

## 12. Production Migration Plan

This section addresses the deliverable: "Plan to go to production."

### 12.1 Architecture Changes

| Concern | Prototype | Production |
|---|---|---|
| **Frontend** | Streamlit | React/Next.js with FastAPI backend. WebSocket for real-time debate streaming |
| **Database** | SQLite file | PostgreSQL with JSONB columns, proper migrations (Alembic) |
| **Auth** | None | OAuth 2.0 / JWT. Per-user sessions and data isolation |
| **API** | Direct function calls | FastAPI REST API with versioned endpoints |
| **LLM** | Direct OpenAI calls | LLM gateway (LiteLLM or custom) with fallback providers |
| **Caching** | None | Redis for session cache, LLM response cache for identical prompts |
| **Queue** | Synchronous | Celery/Redis for async LLM calls, especially during high traffic |
| **Observability** | Print/log | OpenTelemetry traces, Prometheus metrics, structured JSON logs |
| **Deployment** | `streamlit run` | Docker containers on Kubernetes / Cloud Run |
| **CI/CD** | Manual | GitHub Actions → build → test → deploy |

### 12.2 Safety Boundaries

- Content filter on user-submitted dilemmas (reject clearly harmful/illegal scenarios).
- Response filter on agent outputs (flag genuinely dangerous advice even in character).
- Rate limiting per user (max 20 rounds/hour, max 5 sessions/day).
- Cost ceiling per user per day.
- Moderation API integration (OpenAI moderation endpoint or similar).

### 12.3 Evaluation & Quality

- **Character consistency eval set:** 50 dilemmas, manually scored for personality accuracy.
- **Judge stability eval:** Run same debate 10x, check winner consistency.
- **Prompt regression tests:** Golden outputs for key dilemmas, diff on prompt changes.
- **User engagement metrics:** Rounds per session, return rate, session completion rate.

---

## 13. Security & Safety

### 13.1 API Key Handling

- API key read from environment variable only, never hardcoded.
- `.env` file in `.gitignore`.
- Streamlit secrets file (`.streamlit/secrets.toml`) also in `.gitignore`.

### 13.2 Content Safety

- The characters should **never provide genuinely harmful advice** even while in character.
- Add a system-level safety instruction to both character prompts:
  ```
  SAFETY: While you are in character, never provide advice that could cause
  real physical harm, promote illegal activity, or target real individuals.
  If a dilemma involves such content, stay in character but redirect toward
  the philosophical aspects rather than giving actionable harmful instructions.
  ```
- The judge prompt includes `safety_notes` field to flag concerning content.

### 13.3 Data Privacy

- Prototype: all data is local (SQLite file on disk).
- No telemetry or data collection.
- User can delete their session at any time.

---

## 14. Project Structure

```
angel-demon-dilemma/
├── app.py                          # Streamlit entrypoint
├── pyproject.toml                  # Project metadata and dependencies
├── .env.example                    # Template for environment variables
├── .gitignore
├── README.md
│
├── src/
│   └── angel_demon/
│       ├── __init__.py
│       ├── models.py               # All Pydantic models and enums
│       ├── llm.py                  # LLM provider abstraction
│       ├── agents.py               # Sunny & Crowley prompt construction + generation
│       ├── judge.py                # Debate judging engine
│       ├── scoring.py              # Alignment and promotion scoring
│       ├── memory.py               # User and agent memory/adaptation
│       ├── state.py                # Session persistence (SQLite)
│       ├── dilemmas.py             # Preset dilemmas and validation
│       ├── prompts.py              # Prompt templates (constants)
│       └── config.py               # Configuration loading from env
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures (mock LLM, test sessions)
│   ├── test_scoring.py
│   ├── test_state.py
│   ├── test_dilemmas.py
│   ├── test_memory.py
│   ├── test_agents.py
│   ├── test_judge.py
│   ├── test_flow.py
│   └── test_prompts.py
│
├── data/                           # Created at runtime
│   └── state.db                    # SQLite database (gitignored)
│
├── docs/
│   ├── assignment.md               # Original assignment
│   ├── implementation-plan.md      # High-level plan
│   ├── spec.md                     # This document
│   └── input/
│       └── Technical Task_Luxia_2026.pdf
│
└── assets/                         # Static assets for the UI
    └── style.css                   # Custom CSS for Streamlit
```

---

## 15. Build Order & Milestones

### Phase 1: Foundation (Est. 1.5 hours)

1. **Scaffold project** — `pyproject.toml`, directory structure, `uv` setup.
2. **Define data models** — `models.py` with all Pydantic models, enums.
3. **Implement config** — `config.py` to load environment variables.
4. **Build persistence** — `state.py` with SQLite CRUD, tested.
5. **Build scoring** — `scoring.py` with all score calculations, tested.

### Phase 2: AI Core (Est. 2.5 hours)

6. **LLM abstraction** — `llm.py` with `OpenAIProvider`, retry logic, JSON parsing.
7. **Prompt templates** — `prompts.py` with all system prompts as constants.
8. **Agent engine** — `agents.py` with opening and rebuttal generation.
9. **Judge engine** — `judge.py` with verdict generation and fallback.
10. **Memory system** — `memory.py` with profile updates.
11. **Dilemma manager** — `dilemmas.py` with presets and validation.

### Phase 3: UI (Est. 2 hours)

12. **Streamlit app** — `app.py` with full layout, debate flow, and styling.
13. **Custom CSS** — `assets/style.css` for character message styling.
14. **Polish** — animations, alignment meter, promotion board, history.

### Phase 4: Quality & Delivery (Est. 1.5 hours)

15. **Tests** — all test files, fixtures, mock LLM.
16. **README** — full documentation with setup, architecture, production plan.
17. **Final demo pass** — run through 3+ rounds, verify adaptation works.
18. **Code cleanup** — linting, type checking, docstrings.

---

## 16. Definition of Done

- [ ] A reviewer can clone the repo and run the app within 5 minutes using the README.
- [ ] The app runs with an OpenAI API key configured.
- [ ] Sunny and Crowley produce clearly distinct, in-character responses.
- [ ] Every round produces a structured verdict with a declared winner.
- [ ] Alignment score updates visibly after each user decision.
- [ ] Promotion race scoreboard updates after each round.
- [ ] Characters demonstrably adapt their arguments based on previous rounds (memory works).
- [ ] Preset dilemmas are available for quick demo.
- [ ] Custom dilemmas can be submitted.
- [ ] All tests pass (`pytest`).
- [ ] Code passes linting (`ruff check`) and type checking (`mypy`).
- [ ] README includes: setup instructions, architecture explanation, prompting strategy, scoring model, production plan, and known challenges.
- [ ] Conversation history is viewable in the sidebar.
- [ ] The UI is visually polished — not a generic chat interface.
