"""Recover object syntax within one function, using known nested function kinds."""

from __future__ import annotations

import re

from .calls import _rewrite_call_expr
from .common import _extract_indent, code_tokens, is_live_after, uses_identifier
from .objects import _normalize_key, _parse_object_literal, _render_field, _split_top_level


def _render_object(prefix: str, fields: list[str], indent: str) -> list[str]:
    if len(fields) <= 3 and not any("\n" in field for field in fields):
        return [f"{indent}{prefix}{{ {', '.join(fields)} }};"]
    result = [f"{indent}{prefix}{{"]
    for field in fields:
        parts = field.splitlines()
        result.extend(f"{indent}  {part}" for part in parts[:-1])
        result.append(f"{indent}  {parts[-1]},")
    result.append(f"{indent}}};")
    return result


def recover_object_literals(
    lines: list[str], nested: list[str], function_kinds: dict[str, str | None]
) -> tuple[list[str], list[str]]:
    functions: dict[str, tuple[str, list[str]]] = {}
    for function in nested:
        parts = function.splitlines()
        header = re.fullmatch(r"function ([\w$]+)\((.*)\) \{", parts[0])
        if header:
            functions[header[1]] = (header[2], parts[1:-1])

    # Only a single reference in this parent, with no references from sibling or
    # recursive bodies, can be replaced by a newly placed function expression.
    body_tokens = code_tokens("\n".join(lines))
    nested_bodies = "\n".join(line for _, body in functions.values() for line in body)
    eligible = {
        name for name in functions
        if len(re.findall(rf"(?<![\w$.]){re.escape(name)}(?![\w$])", body_tokens)) == 1
        and not uses_identifier(nested_bodies, name)
        and not any("// WARNING:" in line for line in functions[name][1])
    }
    consumed: set[str] = set()

    def method(name: str, key: str, kind: str) -> str | None:
        if name not in eligible or function_kinds.get(name) != kind:
            return None
        params, body = functions[name]
        prefix = {"GetterFunction": "get ", "SetterFunction": "set ", "ConciseMethod": ""}[kind]
        content = [line for line in body if not line.strip().startswith(("// Bytecode ", "// Captures:"))]
        consumed.add(name)
        return "\n".join([f"{prefix}{key}({params}) {{", *content, "}"])

    def data_field(key: str, value: str, set_name: bool = False) -> str | None:
        concise = method(value, key, "ConciseMethod")
        if concise is not None:
            return concise
        if set_name:
            return None
        value = _rewrite_call_expr(value)
        return key if key == value else f"{key}: {value}"

    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.fullmatch(r"(\s*)(r\d+ = |return )(\{.*\})", line)
        if match is None:
            output.append(line)
            index += 1
            continue
        indent, prefix, literal = match.groups()
        register = prefix.split(" = ")[0] if prefix != "return " else None
        if register and uses_identifier(literal, register):
            output.append(line)
            index += 1
            continue
        raw_fields = _split_top_level(literal[1:-1].strip(), ",") if literal[1:-1].strip() else []
        parsed = _parse_object_literal(literal)
        fields = list(raw_fields)
        positions = {}
        if parsed is not None:
            fields = [_render_field(field, field.value) for field in parsed]
            for position, field in enumerate(parsed):
                positions[field.key] = position
                key = '["__proto__"]' if field.key == "__proto__" else field.rendered_key
                # A literal __proto__: null sets the prototype; it is not a data property.
                if field.key != "__proto__":
                    fields[position] = data_field(key, field.value) or fields[position]
        cursor = index + 1
        while register and cursor < len(lines) and _extract_indent(lines[cursor]) == indent:
            statement = lines[cursor].strip()
            conversion = re.fullmatch(r"(r\d+) = ToName\((.*)\)", statement)
            key_register = None
            key_expression = None
            store_index = cursor
            if conversion and cursor + 1 < len(lines):
                key_register, key_expression = conversion.groups()
                store_index += 1
                statement = lines[store_index].strip()
            own = re.fullmatch(r"define_literal_property\((.*)\)", statement)
            accessor = re.fullmatch(r"Define(Accessor|Getter|Setter)PropertyUnchecked\((.*)\)", statement)
            spread = re.fullmatch(r"CopyDataProperties\((.*)\)", statement)
            if own:
                args = _split_top_level(own[1], ",")
                if len(args) != 5 or args[0] != register or args[4] != "true":
                    break
                _, key, value, set_name, _ = args
                if uses_identifier(value, register) or uses_identifier(key, register):
                    break
                if key_register:
                    if (key != key_register or uses_identifier(value, key_register)
                        or uses_identifier(key_expression, register)
                        or is_live_after(lines, store_index + 1, key_register)):
                        break
                    rendered_key = f"[{key_expression}]"
                    position = None
                else:
                    name = _normalize_key(key)
                    rendered_key = name if name and re.fullmatch(r"[A-Za-z_$][\w$]*", name) and name != "__proto__" else f"[{key}]"
                    position = positions.get(name)
                field = data_field(rendered_key, value, set_name == "true")
                if field is None:
                    break
                if (position is not None and parsed[position].value == "undefined"
                    and all(field.endswith(": undefined") for field in fields[position + 1:])):
                    fields[position] = field
                    positions.pop(parsed[position].key)
                else:
                    fields.append(field)
                    if position is not None:
                        positions.pop(parsed[position].key)
            elif accessor:
                mode = accessor[1]
                args = _split_top_level(accessor[2], ",")
                if len(args) != (5 if mode == "Accessor" else 4) or args[0] != register or args[-1] != "0":
                    break
                key = args[1]
                if uses_identifier(key, register):
                    break
                getter, setter = "null", "null"
                if mode == "Accessor":
                    getter, setter = args[2:4]
                elif mode == "Getter":
                    getter = args[2]
                else:
                    setter = args[2]
                if any(fn != "null" and (fn not in eligible or function_kinds.get(fn) != kind)
                       for fn, kind in ((getter, "GetterFunction"), (setter, "SetterFunction"))):
                    break
                if key_register:
                    if (key != key_register or uses_identifier(key_expression, register)
                        or is_live_after(lines, store_index + 1, key_register)
                        or (getter != "null" and setter != "null")):
                        break
                    key = f"[{key_expression}]"
                    position = None
                else:
                    name = _normalize_key(key) if key.startswith('"') else None
                    position = positions.get(name)
                    key = name if name and re.fullmatch(r"[A-Za-z_$][\w$]*", name) else f"[{key}]"
                accessors = [method(fn, key, kind) for fn, kind in ((getter, "GetterFunction"), (setter, "SetterFunction")) if fn != "null"]
                if not accessors:
                    break
                if position is not None and parsed[position].value == "undefined":
                    fields[position] = ",\n".join(accessors)
                else:
                    fields.extend(accessors)
                if position is not None:
                    positions.pop(name)
            elif spread and key_register is None:
                args = _split_top_level(spread[1], ",")
                if len(args) != 2 or args[0] != register or uses_identifier(args[1], register):
                    break
                fields.append(f"...{args[1]}")
                positions.clear()
            else:
                break
            cursor = store_index + 1

        if register and cursor < len(lines) and _extract_indent(lines[cursor]) == indent:
            following = lines[cursor].strip()
            alias = re.fullmatch(rf"(r\d+) = {register}", following)
            if alias and not is_live_after(lines, cursor + 1, register):
                prefix = f"{alias[1]} = "
                cursor += 1
            elif following == f"return {register}":
                prefix = "return "
                cursor += 1
        output.extend(_render_object(prefix, fields, indent))
        index = cursor
    remaining = [text for text in nested if not (
        (header := re.match(r"function ([\w$]+)\(", text)) and header[1] in consumed
    )]
    return output, remaining
