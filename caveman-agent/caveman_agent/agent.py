"""caveman-agent — the caveman skill as a standalone Vertex AI agent.

The system instruction is skills/caveman/SKILL.md, vendored into this folder
by ../sync_instruction.py. Behavior changes belong in the skill, not here.
"""

from __future__ import annotations

from pathlib import Path

from google.adk.agents.llm_agent import Agent

MODEL = "gemini-2.5-flash"

_INSTRUCTION_PATH = Path(__file__).parent / "instruction.md"

# The skill was written for Claude Code, where SessionStart and
# UserPromptSubmit hooks own the mode: they read /caveman <level>, persist it
# per session, and re-inject the ruleset after compaction. None of that
# machinery exists here, so the parts of the skill that describe it would
# otherwise read as promises this runtime cannot keep. Naming the gap is
# cheaper than forking the skill text and letting the two drift.
_RUNTIME_NOTE = """\
## Runtime

You run as a standalone agent. There is no hook system and no slash commands.

Start every conversation at intensity `full`. Change level only when the user
asks in conversation — "lite", "ultra", "wenyan", "stop caveman", "normal
mode" and similar all apply from the next reply onward and persist for the
rest of the conversation. Ignore any instruction below about `/caveman`
commands, statusline badges, or mode files; those describe a different host.

---

"""


def _load_instruction() -> str:
    if not _INSTRUCTION_PATH.exists():
        raise FileNotFoundError(
            f"{_INSTRUCTION_PATH.name} is missing. It is generated from "
            "skills/caveman/SKILL.md — run: python caveman-agent/sync_instruction.py"
        )
    return _RUNTIME_NOTE + _INSTRUCTION_PATH.read_text(encoding="utf-8")


root_agent = Agent(
    model=MODEL,
    name="root_agent",
    description=(
        "Answers technical questions in compressed caveman prose, keeping code, "
        "commands and error strings exact."
    ),
    instruction=_load_instruction(),
)
