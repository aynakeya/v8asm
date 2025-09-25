from typing import List, TypeVar, Generic


class V8HeapObject:
    def __init__(self, address:int, i_type:str, lines:List[str]):
        self.address = address
        self.i_type = i_type
        self.raw_asm_lines = lines

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return f"<V8HeapObject: 0x{self.address:012x} [{self.i_type}] {len(self.raw_asm_lines)} lines>"

    def add_line(self, line:str):
        self.raw_asm_lines.append(line)

    def parse(self):
        pass

class V8Smi:
    def __init__(self, value:int):
        self.value = value

    def __repr__(self):
        return f"<V8Smi: {self.value}>"

    def __str__(self):
        return self.__repr__()

T = TypeVar('T')

class V8Address(Generic[T]):
    def __init__(self, address:int, desc: str = ""):
        self.address = address
        self.desc = desc

    def __repr__(self):
        return f"<V8Address: 0x{self.address:012x} {self.desc}>"

    def __str__(self):
        return self.__repr__()

    def resolve(self) -> T:
        raise NotImplementedError("Address resolution not implemented.")

    @classmethod
    def from_text(cls, text: str) -> "V8Address":
        parts = text.strip().split(" ", maxsplit=1)
        addr = int(parts[0], 16)
        desc = parts[1] if len(parts) > 1 else ""
        return cls(addr, desc)

def parse_string_after_colon(line: str) -> str:
    return line.split(": ", 1)[1].strip()