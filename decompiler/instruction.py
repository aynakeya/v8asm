from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List

from objects.bytecode import CodeLine

OPERAND_SCALE_SUFFIXES = (".Wide", ".ExtraWide")


def _split_operands(operand_text: str) -> List[str]:
    if not operand_text:
        return []

    parts: List[str] = []
    current = []
    depth = 0
    for ch in operand_text:
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth = max(0, depth - 1)
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)

    tokens: List[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "(" in part and ")" in part and not part.startswith("("):
            idx = part.index("(")
            before = part[:idx].strip()
            after = part[idx:].strip()
            if before:
                tokens.append(before)
            if after:
                tokens.append(after)
        else:
            tokens.append(part)
    return tokens


@dataclass
class Instruction:
    offset: int
    mnemonic: str
    args: List[str]
    raw_line: str

    def __post_init__(self) -> None:
        for suffix in OPERAND_SCALE_SUFFIXES:
            if self.mnemonic.endswith(suffix):
                self.mnemonic = self.mnemonic[: -len(suffix)]
                break

    @classmethod
    def from_codeline(cls, line: CodeLine) -> "Instruction":
        return cls(
            offset=line.offset,
            mnemonic=line.mnemonic,
            args=_split_operands(line.operands),
            raw_line=line.raw,
        )
