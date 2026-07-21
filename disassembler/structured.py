from __future__ import annotations

from typing import Any

from .model import ParsedDisassembly
from .structured_builder import SCHEMA_NAME, SCHEMA_VERSION, StructuredGraphBuilder


def disassembly_to_dict(parsed: ParsedDisassembly) -> dict[str, Any]:
    return StructuredGraphBuilder(parsed).build()


__all__ = ["SCHEMA_NAME", "SCHEMA_VERSION", "disassembly_to_dict"]
