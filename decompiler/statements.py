from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


INDENT = "  "


class Statement:
    def render(self, indent: int = 0) -> List[str]:
        raise NotImplementedError


@dataclass
class SimpleStatement(Statement):
    text: str

    def render(self, indent: int = 0) -> List[str]:
        if not self.text:
            return []
        return [f"{INDENT * indent}{self.text}"]


@dataclass
class IfStatement(Statement):
    condition: str
    then_branch: List[Statement] = field(default_factory=list)
    else_branch: Optional[List[Statement]] = None

    def render(self, indent: int = 0) -> List[str]:
        lines = [f"{INDENT * indent}if ({self.condition}) {{"]
        for stmt in self.then_branch:
            lines.extend(stmt.render(indent + 1))
        lines.append(f"{INDENT * indent}}}")
        if self.else_branch:
            lines.append(f"{INDENT * indent}else {{")
            for stmt in self.else_branch:
                lines.extend(stmt.render(indent + 1))
            lines.append(f"{INDENT * indent}}}")
        return lines


@dataclass
class LoopStatement(Statement):
    condition: str
    body: List[Statement] = field(default_factory=list)

    def render(self, indent: int = 0) -> List[str]:
        lines = [f"{INDENT * indent}while ({self.condition}) {{"]
        for stmt in self.body:
            lines.extend(stmt.render(indent + 1))
        lines.append(f"{INDENT * indent}}}")
        return lines
