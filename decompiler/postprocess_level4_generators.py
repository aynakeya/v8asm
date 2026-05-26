from __future__ import annotations

import re
from typing import List

from postprocess_level4_common import _extract_indent


def _inline_generator_resume_mode_switches(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            mode = re.match(r"^ACCU\s*=\s*(_GeneratorGetResumeMode\(.+\))$", s0)
            switch = re.match(r"^// SwitchOnSmiNoFeedback ACCU(.*)$", s1)
            if mode and switch:
                indent = _extract_indent(lines[i + 1])
                out.append(
                    f"{indent}// SwitchOnSmiNoFeedback {mode.group(1)}{switch.group(1)}"
                )
                i += 2
                continue
        out.append(lines[i])
        i += 1
    return out
