#!/usr/bin/env python3
"""Vendor skills/caveman/SKILL.md into the ADK agent as instruction.md.

`adk deploy cloud_run` copies only the agent source folder into the image
(see google/adk/cli/cli_deploy.py, _DOCKERFILE_TEMPLATE), so a path reaching
up into ../../skills/ resolves locally and is missing at runtime. The skill
body therefore has to live inside caveman_agent/.

The copy is a build output. CLAUDE.md keeps skills/caveman/SKILL.md as the
single source of truth for caveman behavior; edit there and re-run this.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
SOURCE = REPO_ROOT / "skills" / "caveman" / "SKILL.md"
TARGET = AGENT_DIR / "caveman_agent" / "instruction.md"


def strip_frontmatter(text: str) -> str:
    """Drop the leading YAML frontmatter block, if present.

    The frontmatter is skill-registry metadata (name, description) that the
    Claude Code plugin loader consumes to decide when to activate. A model
    reading it as instruction would treat the activation triggers as behavior.
    """
    if not text.startswith("---"):
        return text.strip()
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    # An unterminated opening fence means the file is not what we think it is.
    raise SystemExit(f"{SOURCE}: frontmatter opened with --- but never closed")


def render() -> tuple[str, str, int]:
    """Return (rendered file contents, body digest, body length)."""
    if not SOURCE.exists():
        raise SystemExit(f"skill source not found: {SOURCE}")

    body = strip_frontmatter(SOURCE.read_text(encoding="utf-8"))
    if not body:
        raise SystemExit(f"{SOURCE}: no content after frontmatter")

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    header = (
        "<!-- GENERATED FILE - DO NOT EDIT.\n"
        "     Source: skills/caveman/SKILL.md\n"
        f"     Body sha256: {digest}\n"
        "     Regenerate: python caveman-agent/sync_instruction.py -->\n\n"
    )
    return header + body + "\n", digest, len(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify the committed instruction.md matches the skill and exit "
            "non-zero if it does not. Writes nothing. Used by CI so a deploy "
            "can never ship an instruction that differs from the committed one."
        ),
    )
    args = parser.parse_args()

    rendered, digest, length = render()
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else None

    if args.check:
        if current is None:
            print(f"FAIL: {TARGET.name} is missing", file=sys.stderr)
        elif current != rendered:
            print(
                f"FAIL: {TARGET.name} is stale — skills/caveman/SKILL.md has "
                f"changed since it was generated (expected body {digest}).",
                file=sys.stderr,
            )
        else:
            print(f"instruction.md matches the skill (body {digest})")
            return 0
        print(
            "Run: python caveman-agent/sync_instruction.py — then commit the result.",
            file=sys.stderr,
        )
        return 1

    if current == rendered:
        print(f"instruction.md already current (body {digest})")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO_ROOT)} ({length} chars, body {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
