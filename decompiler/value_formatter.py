from __future__ import annotations

import json
import math
from typing import Any, TYPE_CHECKING

from .objects import (
    V8Address,
    V8ArrayBoilerplateDescription,
    V8BytecodeArray,
    V8FixedArray,
    V8HeapNumber,
    V8Hole,
    V8ObjectBoilerplateDescription,
    V8ScopeInfo,
    V8SharedFunctionInfo,
    V8Smi,
    V8String,
)

if TYPE_CHECKING:
    from .context import DecompilerContext


class ValueFormatter:
    def __init__(self, context: DecompilerContext) -> None:
        self.context = context

    def format(self, raw: Any) -> str:
        if isinstance(raw, V8Smi):
            return str(raw.value)
        if isinstance(raw, V8Hole):
            return "HOLE"
        if isinstance(raw, float):
            if math.isnan(raw):
                return "(0 / 0)"
            if math.isinf(raw):
                return "(1 / 0)" if raw > 0 else "(-1 / 0)"
            return repr(raw)

        if isinstance(raw, V8Address):
            target = self.context.get_object(raw.address)
            if isinstance(target, V8String):
                return json.dumps(target.value)
            if isinstance(target, V8HeapNumber) and target.value is not None:
                return self.format(target.value)
            if isinstance(target, V8SharedFunctionInfo):
                return self.context.get_function_name(target)
            if isinstance(target, V8ArrayBoilerplateDescription):
                return self._format_array_boilerplate(target)
            if isinstance(target, V8ObjectBoilerplateDescription):
                return self._format_object_boilerplate(target)
            if isinstance(target, V8FixedArray):
                return self._format_fixed_array(target)
            if isinstance(target, V8BytecodeArray):
                owner = self.context.bytecode_functions.get(target.address)
                if owner:
                    return f"<bytecode {self.context.get_function_name(owner)}>"
                return f"<Bytecode 0x{target.address:012x}>"
            if isinstance(target, V8ScopeInfo):
                return self._format_scope_info(target)
            description = self._format_address_description(raw.desc)
            if description is not None:
                return description
            if target:
                return json.dumps(
                    f"<{target.i_type} 0x{target.address:012x}>"
                )
            return json.dumps(raw.desc or f"0x{raw.address:012x}")

        if isinstance(raw, str):
            return json.dumps(raw)
        if raw is None:
            return "undefined"
        return str(raw)

    def _format_fixed_array(self, array: V8FixedArray, *, holes: bool = False) -> str:
        parts = ["" if holes and isinstance(element, V8Hole) else self.format(element)
                 for element in array.elements]
        trailing = "," if parts and parts[-1] == "" else ""
        return "[" + ", ".join(parts) + trailing + "]"

    def _format_array_boilerplate(
        self, boilerplate: V8ArrayBoilerplateDescription
    ) -> str:
        if not boilerplate.constant_elements:
            return f"<ArrayBoilerplate {boilerplate.elements_kind}>"
        constant = self.context.get_object(
            boilerplate.constant_elements.address
        )
        if isinstance(constant, V8FixedArray):
            return self._format_fixed_array(constant, holes=True)
        return f"<ArrayBoilerplate {boilerplate.elements_kind}>"

    @staticmethod
    def _format_address_description(description: str) -> str | None:
        text = description.strip()
        if not text:
            return None
        inner = text[1:-1] if text.startswith("<") and text.endswith(">") else text
        if inner in {"true", "false", "null", "undefined"}:
            return inner
        normalized = "".join(
            character for character in inner.lower() if character.isalpha()
        )
        return "undefined" if normalized == "uninitializedvalue" else None

    def _format_object_key(self, raw: Any) -> str:
        key = self.format(raw)
        if key.startswith('"') and key.endswith('"'):
            try:
                plain = json.loads(key)
            except json.JSONDecodeError:
                return key
            if plain == "__proto__":
                return f"[{key}]"
            if plain.isidentifier():
                return plain
        return key

    def _format_object_boilerplate(
        self, boilerplate: V8ObjectBoilerplateDescription
    ) -> str:
        parts = []
        if boilerplate.flags and boilerplate.literal_flags and (
            boilerplate.flags & boilerplate.literal_flags["object_literal_null_prototype"]
        ):
            parts.append("__proto__: null")
        entries = boilerplate.entries
        for index in range(0, len(entries), 2):
            key = entries[index]
            value = entries[index + 1] if index + 1 < len(entries) else None
            parts.append(
                f"{self._format_object_key(key)}: {self.format(value)}"
            )
        return "{ " + ", ".join(parts) + " }"

    @staticmethod
    def _format_scope_info(scope: V8ScopeInfo) -> str:
        scope_type = scope.scope_type or "Scope"
        return f"<ScopeInfo {scope_type}>"
