from __future__ import annotations

if __package__:
    from .cli import main
    from .core import decompile_bytecode, decompile_file, decompile_objects
else:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from decompiler.cli import main  # noqa: E402
    from decompiler.core import (  # noqa: E402
        decompile_bytecode,
        decompile_file,
        decompile_objects,
    )


__all__ = [
    "decompile_bytecode",
    "decompile_file",
    "decompile_objects",
    "main",
]


if __name__ == "__main__":
    main()
