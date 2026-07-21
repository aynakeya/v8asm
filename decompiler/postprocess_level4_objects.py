from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import List, Optional

from .postprocess_level4_common import _extract_indent


IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class _ObjectField:
    key: str
    rendered_key: str
    value: str


def _split_top_level(value: str, delimiter: str) -> List[str]:
    parts: List[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'", "`"}:
            quote = character
            continue
        if character in "([{":
            depth += 1
            continue
        if character in ")]}":
            depth = max(0, depth - 1)
            continue
        if character == delimiter and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _split_field(value: str) -> Optional[tuple[str, str]]:
    parts = _split_top_level(value, ":")
    if len(parts) != 2 or not all(parts):
        return None
    return parts[0], parts[1]


def _normalize_key(value: str) -> Optional[str]:
    value = value.strip()
    if IDENT_RE.fullmatch(value):
        return value
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, str) else None
    return None


def _parse_object_literal(value: str) -> Optional[List[_ObjectField]]:
    value = value.strip()
    if not (value.startswith("{") and value.endswith("}")):
        return None
    content = value[1:-1].strip()
    if not content:
        return []
    fields: List[_ObjectField] = []
    seen: set[str] = set()
    for raw_field in _split_top_level(content, ","):
        split = _split_field(raw_field)
        if split is None:
            shorthand = raw_field.strip()
            if not IDENT_RE.fullmatch(shorthand):
                return None
            rendered_key, field_value = shorthand, shorthand
        else:
            rendered_key, field_value = split
        key = _normalize_key(rendered_key)
        if key is None or key in seen:
            return None
        seen.add(key)
        fields.append(_ObjectField(key, rendered_key.strip(), field_value.strip()))
    return fields


def _property_assignment(
    line: str, register: str
) -> Optional[tuple[str, str]]:
    dot = re.match(
        rf"^{re.escape(register)}\.([A-Za-z_$][A-Za-z0-9_$]*)"
        r"\s*=(?!=)\s*(.+)$",
        line,
    )
    if dot:
        return dot.group(1), dot.group(2).strip()
    bracket = re.match(
        rf"^{re.escape(register)}\[(.+)\]\s*=(?!=)\s*(.+)$",
        line,
    )
    if not bracket:
        return None
    key = _normalize_key(bracket.group(1))
    return (key, bracket.group(2).strip()) if key is not None else None


def _render_field(field: _ObjectField, value: str) -> str:
    if IDENT_RE.fullmatch(field.rendered_key) and field.key == value:
        return field.key
    return f"{field.rendered_key}: {value}"


def _is_pure_existing_value(value: str) -> bool:
    value = value.strip()
    if value in {"undefined", "null", "true", "false"}:
        return True
    if IDENT_RE.fullmatch(value):
        return True
    if re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", value):
        return True
    if value.startswith('"') and value.endswith('"'):
        try:
            return isinstance(json.loads(value), str)
        except json.JSONDecodeError:
            return False
    return False


def _compact_object_literal_initializers(lines: List[str]) -> List[str]:
    output: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        assignment = re.match(r"^(r\d+)\s*=(?!=)\s*(\{.*\})$", stripped)
        if not assignment:
            output.append(line)
            index += 1
            continue

        register, literal = assignment.groups()
        fields = _parse_object_literal(literal)
        if not fields or any(
            not _is_pure_existing_value(field.value) for field in fields
        ):
            output.append(line)
            index += 1
            continue

        positions = {field.key: position for position, field in enumerate(fields)}
        values = {field.key: field.value for field in fields}
        indent = _extract_indent(line)
        cursor = index + 1
        previous_position = -1
        updates = 0
        valid = True
        while cursor < len(lines) and _extract_indent(lines[cursor]) == indent:
            update = _property_assignment(lines[cursor].strip(), register)
            if update is None:
                break
            key, value = update
            position = positions.get(key)
            if (
                position is None
                or position <= previous_position
                or values[key] != "undefined"
            ):
                valid = False
                break
            values[key] = value
            previous_position = position
            updates += 1
            cursor += 1
        if not valid or updates == 0:
            output.append(line)
            index += 1
            continue

        rendered = ", ".join(
            _render_field(field, values[field.key]) for field in fields
        )
        object_literal = f"{{ {rendered} }}"
        next_line = lines[cursor].strip() if cursor < len(lines) else ""
        if cursor < len(lines) and _extract_indent(lines[cursor]) == indent:
            if next_line == f"return {register}":
                output.append(f"{indent}return {object_literal}")
                cursor += 1
            else:
                final_assignment = re.match(
                    r"^([A-Za-z_$][A-Za-z0-9_$]*"
                    r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]]+\])*)"
                    rf"\s*=(?!=)\s*{re.escape(register)}$",
                    next_line,
                )
                if final_assignment:
                    output.append(
                        f"{indent}{final_assignment.group(1)} = {object_literal}"
                    )
                    cursor += 1
                else:
                    output.append(f"{indent}{register} = {object_literal}")
        else:
            output.append(f"{indent}{register} = {object_literal}")
        index = cursor
    return output
