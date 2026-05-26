from __future__ import annotations

import re
from typing import List

from postprocess_level4_common import _find_block_end


def _strip_iterator_exception_guard(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            if (
                s0 == "ACCU = 0"
                and re.match(r"^ACCU = \(r\d+ === ACCU\)$", s1)
                and s2 == "if (truthy(ACCU)) {"
            ):
                end = _find_block_end(lines, i + 2)
                if end is not None:
                    block_text = "\n".join(lines[i + 2 : end + 1])
                    if "// SetPendingMessage" in block_text and "throw ACCU" in block_text:
                        i = end + 1
                        continue
        out.append(lines[i])
        i += 1
    return out


def _strip_pending_message_status_guard(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            if (
                s0 == "ACCU = 0"
                and re.match(r"^ACCU = \(r\d+ === ACCU\)$", s1)
                and s2 == "if (truthy(ACCU)) {"
            ):
                end = _find_block_end(lines, i + 2)
                if end is not None:
                    final_end = end
                    if end + 1 < len(lines) and lines[end + 1].strip() == "else {":
                        else_end = _find_block_end(lines, end + 1)
                        if else_end is not None:
                            final_end = else_end
                    block = "\n".join(lines[i + 2 : final_end + 1])
                    if "// SetPendingMessage" in block:
                        i = final_end + 1
                        continue
        out.append(lines[i])
        i += 1
    return out
