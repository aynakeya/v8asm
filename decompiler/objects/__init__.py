from typing import List

from objects.base import V8HeapObject
from objects.boilerplate import V8ArrayBoilerplateDescription
from objects.bytecode import V8BytecodeArray,CodeLine
from objects.fixed_array import V8TrustedFixedArray, V8FixedArray
from objects.string import V8String
from objects.sfi import V8SharedFunctionInfo


def parse_object(address:int, i_type:str, lines:List[str]) -> V8HeapObject:
    if i_type == "String":
        obj = V8String(address, i_type, lines)
    elif i_type == "SharedFunctionInfo":
        obj = V8SharedFunctionInfo(address, i_type, lines)
    elif i_type == "TrustedFixedArray":
        obj = V8TrustedFixedArray(address, i_type, lines)
    elif i_type == "FixedArray":
        obj = V8FixedArray(address, i_type, lines)
    elif i_type == "ArrayBoilerplateDescription":
        obj = V8ArrayBoilerplateDescription(address, i_type, lines)
    elif i_type == "BytecodeArray":
        obj = V8BytecodeArray(address, i_type, lines)
    else:
        obj = V8HeapObject(address, i_type, lines)
    return obj