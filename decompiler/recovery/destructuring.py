from __future__ import annotations

import re

from .common import _extract_indent, is_live_after, uses_identifier
from .objects import _split_top_level


def recover_object_rest(lines: list[str]) -> list[str]:
    """Match the null guard, ordered property reads, and their exact rest exclusions."""
    output: list[str] = []
    index = 0
    while index < len(lines):
        window = [line.strip() for line in lines[index:index + 7]]
        load = re.fullmatch(r"ACCU = (r\d+|arg\d+)", window[0]) if window else None
        saved = re.fullmatch(r"(r\d+) = (r\d+|arg\d+)", window[1]) if len(window) == 7 else None
        if not load or not saved or load[1] != saved[2] or window[2:] != [
            "if (!(isNullish(ACCU))) {", "}", "else {",
            f"ACCU = ThrowPatternAssignmentNonCoercible({saved[1]})", "}",
        ]:
            output.append(lines[index])
            index += 1
            continue
        source, receiver = load[1], saved[1]
        indent = _extract_indent(lines[index])
        cursor = index + 7
        keys, fields, targets = [], [], []
        while cursor + 1 < len(lines) and _extract_indent(lines[cursor]) == indent:
            conversion = re.fullmatch(r"(ACCU|r\d+) = ToName\((.*)\)", lines[cursor].strip())
            if conversion is None:
                break
            converted, key = conversion.groups()
            end = cursor + 1
            if converted == "ACCU":
                save_key = re.fullmatch(r"(r\d+) = ACCU", lines[end].strip())
                if save_key is None:
                    break
                key_register = save_key[1]
                end += 1
            else:
                key_register = converted
            read = re.fullmatch(rf"(r\d+) = {receiver}\[{converted}\]", lines[end].strip()) if end < len(lines) else None
            if read is None or uses_identifier(key, receiver):
                break
            keys.append(key_register)
            targets.append(read[1])
            fields.append(f"[{key}]: {read[1]}")
            cursor = end + 1
        rest = re.fullmatch(r"(r\d+) = CopyDataPropertiesWithExcludedPropertiesOnStack\((.*)\)", lines[cursor].strip()) if cursor < len(lines) else None
        temporaries = ["ACCU", receiver, *keys]
        if (not fields or rest is None or _split_top_level(rest[2], ",") != [receiver, *keys]
            or len(set(targets + [rest[1]])) != len(targets) + 1
            or any(target in temporaries for target in targets + [rest[1]])
            or any(is_live_after(lines, cursor + 1, temp) for temp in temporaries)):
            output.append(lines[index])
            index += 1
            continue
        # An assignment pattern checks coercibility before evaluating the first key,
        # then evaluates each key/getter exactly once before copying the rest.
        output.append(f"{indent};({{ {', '.join(fields)}, ...{rest[1]} }} = {source});")
        index = cursor + 1
    return output
