
import re
from typing import List

from objects import *

with open("main.d8.jsc.txt","r") as f:
    data = f.readlines()


HEADER_RE = re.compile(r"^(0x[0-9a-f]+): \[([A-Za-z0-9_]+)\]")

objects: List[V8HeapObject] = []
curr_addr = 0
curr_type = ""
for line in data:
    match = HEADER_RE.match(line)
    if match:
        objects.append(parse_object(int(match.group(1),16), match.group(2), [line]))
    else:
        # print(objects[-1],line.strip())
        objects[-1].add_line(line.strip("\n"))

for obj in objects:
    obj.parse()

for obj in objects:
    if isinstance(obj, V8SharedFunctionInfo):
        print(obj.name,obj.trusted_function_data)
        continue
    if not isinstance(obj, V8BytecodeArray):
        continue

    # bytecodeArray: V8BytecodeArray = obj
    # print(obj)
    # for instruction in bytecodeArray.instructions:
    #     print(instruction)