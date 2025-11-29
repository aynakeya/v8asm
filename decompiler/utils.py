from __future__ import annotations

import re
from typing import Optional

from instruction import Instruction

JUMP_TARGET_RE = re.compile(r"@ (\d+)\)")


def parse_jump_target(instr: Instruction) -> Optional[int]:
    """Extract the numeric jump target from an instruction, if present."""
    for token in instr.args:
        match = JUMP_TARGET_RE.search(token)
        if match:
            return int(match.group(1))
    return None


def strip_trailing_goto(statements, target_offset: int) -> None:
    """Remove a trailing `goto offset_X` statement if it matches the target."""
    if not statements:
        return
    last = statements[-1]
    text = getattr(last, "text", "").strip()
    if text == f"goto offset_{target_offset}":
        statements.pop()
