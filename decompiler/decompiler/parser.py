from typing import List
from objects import *
import re

HEADER_RE = re.compile(r"^(0x[0-9a-f]+): \[([A-Za-z0-9_]+)\]")

def parse_objects(lines: List[str]) -> List[V8HeapObject]:
    objs = []
    for line in lines:
        match = HEADER_RE.match(line)
        if match:
            objs.append(parse_object(int(match.group(1), 16), match.group(2), [line]))
        else:
            # print(objects[-1],line.strip())
            objs[-1].add_line(line.strip("\n"))
    for obj in objs:
        obj.parse()
    return objs