"""V8 bytecode decompiler package."""

from .core import decompile_file, decompile_objects
from .parser import parse_objects

__all__ = ["decompile_file", "decompile_objects", "parse_objects"]
