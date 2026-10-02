from typing import List

from .base import V8HeapObject, V8Address, V8Smi, V8Hole, V8HeapNumber
from .boilerplate import (
    V8ArrayBoilerplateDescription,
    V8ObjectBoilerplateDescription,
    V8ClassBoilerplate,
    V8ScopeInfo,
)
from .bytecode import V8BytecodeArray,CodeLine
from .fixed_array import V8TrustedFixedArray, V8FixedArray, V8FixedDoubleArray
from .string import V8String
from .sfi import V8SharedFunctionInfo


def parse_object(address:int, i_type:str, lines:List[str]) -> V8HeapObject:
    if i_type == "String":
        obj = V8String(address, i_type, lines)
    elif i_type == "SharedFunctionInfo":
        obj = V8SharedFunctionInfo(address, i_type, lines)
    elif i_type == "TrustedFixedArray":
        obj = V8TrustedFixedArray(address, i_type, lines)
    elif i_type == "FixedArray":
        obj = V8FixedArray(address, i_type, lines)
    elif i_type == "FixedDoubleArray":
        obj = V8FixedDoubleArray(address, i_type, lines)
    elif i_type == "HeapNumber":
        obj = V8HeapNumber(address, i_type, lines)
    elif i_type == "ArrayBoilerplateDescription":
        obj = V8ArrayBoilerplateDescription(address, i_type, lines)
    elif i_type == "ObjectBoilerplateDescription":
        obj = V8ObjectBoilerplateDescription(address, i_type, lines)
    elif i_type == "ClassBoilerplate":
        obj = V8ClassBoilerplate(address, i_type, lines)
    elif i_type == "ScopeInfo":
        obj = V8ScopeInfo(address, i_type, lines)
    elif i_type == "BytecodeArray":
        obj = V8BytecodeArray(address, i_type, lines)
    else:
        obj = V8HeapObject(address, i_type, lines)
    return obj
