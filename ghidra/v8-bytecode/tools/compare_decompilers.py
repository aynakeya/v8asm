#!/usr/bin/env python3
"""Compare the Python and Ghidra decompilers on one V8 BytecodeArray."""

from __future__ import annotations

import argparse
import difflib
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
MODULE_DIR = Path(__file__).resolve().parents[1]
LANGUAGE_DIR = MODULE_DIR / "data" / "languages"
GHIDRA_SCRIPT_DIR = MODULE_DIR / "ghidra_scripts"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decompiler.context import DecompilerContext  # noqa: E402
from decompiler.core import decompile_bytecode  # noqa: E402
from decompiler.objects.bytecode import V8BytecodeArray  # noqa: E402
from decompiler.recovery.file import postprocess_source_file  # noqa: E402
from decompiler.structured import load_structured_objects  # noqa: E402
from disassembler.disassembler import parse_disassembly_file  # noqa: E402
from disassembler.structured import disassembly_to_dict  # noqa: E402


class CompareError(RuntimeError):
    pass


def _parse_offset(value: str) -> int:
    try:
        result = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer offset") from exc
    if result < 0:
        raise argparse.ArgumentTypeError("offset must be non-negative")
    return result


def _load_document(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input).resolve()
    data = input_path.read_bytes()
    if data.lstrip().startswith(b"{"):
        document = json.loads(data.decode("utf-8"))
        if not isinstance(document, dict):
            raise CompareError("structured disassembly must be a JSON object")
        return document

    parsed = parse_disassembly_file(
        input_path,
        args.version,
        args.runtime_variant,
        args.snapshot_blob,
        args.payload_offset,
    )
    return disassembly_to_dict(parsed)


def _function_names(document: dict[str, Any]) -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    objects = document.get("objects", {})
    for key in document.get("object_order", []):
        record = objects.get(key, {})
        if record.get("type") != "SharedFunctionInfo":
            continue
        address = record.get("bytecode_address")
        if not isinstance(address, str):
            continue
        name = record.get("name_value")
        display = name if isinstance(name, str) and name else "<anonymous>"
        names.setdefault(address, []).append(display)
    return names


def _instruction_bytes(record: dict[str, Any]) -> bytes:
    instructions = record.get("instructions")
    if not isinstance(instructions, list) or not instructions:
        raise CompareError("BytecodeArray has no instructions")

    result = bytearray()
    expected_offset = 0
    for instruction in instructions:
        if not isinstance(instruction, dict):
            raise CompareError("invalid instruction record")
        offset = instruction.get("offset")
        raw = instruction.get("raw_bytes")
        if offset != expected_offset:
            raise CompareError(
                f"non-contiguous bytecode at offset {offset}; expected {expected_offset}"
            )
        if not isinstance(raw, list) or not raw or not all(
            isinstance(value, int) and 0 <= value <= 0xFF for value in raw
        ):
            raise CompareError(f"invalid raw_bytes at offset {offset}")
        result.extend(raw)
        expected_offset += len(raw)
    return bytes(result)


def _bytecode_targets(document: dict[str, Any]) -> list[dict[str, Any]]:
    objects = document.get("objects")
    order = document.get("object_order")
    if not isinstance(objects, dict) or not isinstance(order, list):
        raise CompareError("structured disassembly has no object graph")

    names = _function_names(document)
    targets: list[dict[str, Any]] = []
    for key in order:
        record = objects.get(key)
        if not isinstance(record, dict) or record.get("type") != "BytecodeArray":
            continue
        raw = _instruction_bytes(record)
        record_names = names.get(key, ["<anonymous>"])
        targets.append(
            {
                "index": len(targets),
                "address": key,
                "name": record_names[0],
                "all_names": record_names,
                "record": record,
                "raw": raw,
            }
        )
    if not targets:
        raise CompareError("structured disassembly contains no BytecodeArray")
    return targets


def _select_target(
    targets: list[dict[str, Any]], function: str | None, index: int | None
) -> dict[str, Any]:
    if function is not None:
        matches = [target for target in targets if function in target["all_names"]]
        if not matches:
            available = ", ".join(
                f"{target['index']}:{target['name']}" for target in targets
            )
            raise CompareError(
                f"function {function!r} not found; available functions: {available}"
            )
        if len(matches) > 1:
            indexes = ", ".join(str(target["index"]) for target in matches)
            raise CompareError(
                f"function {function!r} is ambiguous; use --bytecode-index ({indexes})"
            )
        return matches[0]

    if index is not None:
        normalized = index + len(targets) if index < 0 else index
        if not 0 <= normalized < len(targets):
            raise CompareError(
                f"bytecode index {index} is outside 0..{len(targets) - 1}"
            )
        return targets[normalized]

    return max(targets, key=lambda target: (len(target["raw"]), -target["index"]))


def _additional_entry_points(
    document: dict[str, Any], target: dict[str, Any]
) -> list[tuple[str, int]]:
    record = target["record"]
    entries: dict[int, str] = {}
    for handler in record.get("handler_entries", []):
        if not isinstance(handler, dict):
            continue
        offset = handler.get("handler")
        if isinstance(offset, int):
            entries[offset] = "handler"

    pool_address = record.get("constant_pool_address")
    pool = document.get("objects", {}).get(pool_address, {})
    elements = pool.get("elements", []) if isinstance(pool, dict) else []
    for instruction in record.get("instructions", []):
        if not isinstance(instruction, dict):
            continue
        mnemonic = str(instruction.get("mnemonic", "")).split(".", 1)[0]
        jump_target = instruction.get("jump_target")
        if mnemonic.endswith("Constant") and isinstance(jump_target, int):
            entries.setdefault(jump_target, "jump")
        operands = instruction.get("operands", [])
        if mnemonic == "SwitchOnGeneratorState":
            index_position, count_position = 1, 2
        elif mnemonic == "SwitchOnSmiNoFeedback":
            index_position, count_position = 0, 1
        else:
            continue
        if not isinstance(operands, list) or len(operands) <= count_position:
            continue
        pool_index = operands[index_position].get("value")
        count = operands[count_position].get("value")
        source_offset = instruction.get("offset")
        if not all(isinstance(value, int) for value in (pool_index, count, source_offset)):
            continue
        for element in elements[pool_index : pool_index + count]:
            if not isinstance(element, dict) or element.get("kind") != "smi":
                continue
            relative = element.get("value")
            if isinstance(relative, int):
                entries.setdefault(source_offset + relative, "switch")

    code_size = len(target["raw"])
    return [
        (kind, offset)
        for offset, kind in sorted(entries.items())
        if 0 < offset < code_size
    ]


def _write_entry_metadata(
    metadata_dir: Path, raw_name: str, entries: list[tuple[str, int]]
) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    contents = "".join(f"{kind} {offset}\n" for kind, offset in entries)
    (metadata_dir / f"{raw_name}.entries").write_text(contents, encoding="ascii")


def _python_decompile_with_context(
    context: DecompilerContext, bytecode: V8BytecodeArray
) -> str:
    source = decompile_bytecode(
        context,
        bytecode,
        as_script=context.is_script(bytecode),
    )
    return postprocess_source_file(source).rstrip() + "\n"


def _python_decompile(document: dict[str, Any], address: str) -> str:
    objects = load_structured_objects(document)
    context = DecompilerContext(objects)
    target_address = int(address, 16)
    bytecode = next(
        (
            obj
            for obj in objects
            if isinstance(obj, V8BytecodeArray) and obj.address == target_address
        ),
        None,
    )
    if bytecode is None:
        raise CompareError(f"Python decompiler cannot find BytecodeArray {address}")
    return _python_decompile_with_context(context, bytecode)


def _application_properties(ghidra_home: Path) -> dict[str, str]:
    path = ghidra_home / "Ghidra" / "application.properties"
    properties: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value
    return properties


def _run_logged(
    command: list[str], env: dict[str, str], log_path: Path, label: str
) -> None:
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    log_path.write_text(process.stdout, encoding="utf-8")
    if process.returncode != 0:
        raise CompareError(
            f"{label} failed with exit code {process.returncode}; see {log_path}"
        )


def _install_language(
    ghidra_home: Path,
    env: dict[str, str],
    config_home: Path,
    work_dir: Path,
    log_path: Path,
) -> None:
    properties = _application_properties(ghidra_home)
    version = properties.get("application.version")
    release = properties.get("application.release.name")
    if not version or not release:
        raise CompareError("cannot determine the Ghidra version")

    compiled_sla = work_dir / "v8bytecode.sla"
    _run_logged(
        [
            str(ghidra_home / "support" / "sleigh"),
            str(LANGUAGE_DIR / "v8bytecode.slaspec"),
            str(compiled_sla),
        ],
        env,
        log_path,
        "SLEIGH compilation",
    )

    extension_root = (
        config_home
        / f"{getpass.getuser()}-ghidra"
        / f"ghidra_{version}_{release}"
        / "Extensions"
        / "V8Bytecode"
    )
    extension_languages = extension_root / "data" / "languages"
    extension_languages.mkdir(parents=True, exist_ok=True)
    for name in (
        "v8bytecode.slaspec",
        "v8bytecode.pspec",
        "v8bytecode.cspec",
        "v8bytecode.ldefs",
    ):
        shutil.copy2(LANGUAGE_DIR / name, extension_languages / name)
    shutil.copy2(compiled_sla, extension_languages / compiled_sla.name)
    shutil.copy2(MODULE_DIR / "extension.properties", extension_root)
    shutil.copy2(MODULE_DIR / "Module.manifest", extension_root)


def _ghidra_decompile(
    raw_path: Path,
    output_dir: Path,
    ghidra_home: Path,
    java_home: Path,
    function_name: str,
    additional_entries: list[tuple[str, int]],
) -> tuple[str, Path]:
    sleigh = ghidra_home / "support" / "sleigh"
    headless = ghidra_home / "support" / "analyzeHeadless"
    java = java_home / "bin" / "java"
    for path in (sleigh, headless, java):
        if not path.exists():
            raise CompareError(f"required executable does not exist: {path}")

    full_output = output_dir / "ghidra-full.txt"
    headless_log = output_dir / "ghidra-headless.log"
    script_log = output_dir / "ghidra-script.log"
    metadata_dir = output_dir / "ghidra-metadata"
    _write_entry_metadata(metadata_dir, raw_path.name, additional_entries)
    with tempfile.TemporaryDirectory(prefix="v8asm-ghidra-") as temp_name:
        temp_dir = Path(temp_name)
        config_home = temp_dir / "config"
        project_dir = temp_dir / "projects"
        work_dir = temp_dir / "build"
        config_home.mkdir()
        project_dir.mkdir()
        work_dir.mkdir()

        env = os.environ.copy()
        env["JAVA_HOME"] = str(java_home)
        env["XDG_CONFIG_HOME"] = str(config_home)
        _install_language(
            ghidra_home,
            env,
            config_home,
            work_dir,
            output_dir / "sleigh.log",
        )
        _run_logged(
            [
                str(headless),
                str(project_dir),
                "v8compare",
                "-import",
                str(raw_path),
                "-processor",
                "V8Bytecode:LE:32:default",
                "-cspec",
                "default",
                "-overwrite",
                "-scriptPath",
                str(GHIDRA_SCRIPT_DIR),
                "-postScript",
                "DumpV8Decompile.java",
                str(full_output),
                function_name,
                str(metadata_dir),
                "-log",
                str(headless_log),
                "-scriptlog",
                str(script_log),
                "-deleteProject",
            ],
            env,
            output_dir / "ghidra-console.log",
            "Ghidra headless analysis",
        )

    if not full_output.exists():
        raise CompareError("Ghidra did not produce a decompiler output")
    contents = full_output.read_text(encoding="utf-8", errors="replace")
    marker = "== Decompile ==\n"
    if marker not in contents:
        raise CompareError(f"Ghidra output has no decompile section: {full_output}")
    return contents.split(marker, 1)[1].strip() + "\n", full_output


def _write_report(
    output_dir: Path,
    input_path: Path,
    document: dict[str, Any],
    target: dict[str, Any],
    python_source: str,
    ghidra_source: str,
) -> None:
    python_path = output_dir / "python.js"
    ghidra_path = output_dir / "ghidra.c"
    diff_path = output_dir / "comparison.diff"
    report_path = output_dir / "comparison.md"
    python_path.write_text(python_source, encoding="utf-8")
    ghidra_path.write_text(ghidra_source, encoding="utf-8")
    diff = "".join(
        difflib.unified_diff(
            python_source.splitlines(keepends=True),
            ghidra_source.splitlines(keepends=True),
            fromfile="python.js",
            tofile="ghidra.c",
        )
    )
    diff_path.write_text(diff, encoding="utf-8")

    metadata = document.get("metadata", {})
    record = target["record"]
    additional_entries = _additional_entry_points(document, target)
    report = f"""# V8 decompiler comparison

- Input: `{input_path}`
- V8 version: `{metadata.get('v8_version', 'unknown')}`
- Function: `{target['name']}`
- Bytecode index: `{target['index']}`
- Bytecode address: `{target['address']}`
- Byte size: `{len(target['raw'])}`
- Parameters: `{record.get('parameter_count', 'unknown')}`
- Registers: `{record.get('register_count', 'unknown')}`
- Additional handler/switch entries: `{len(additional_entries)}`

## Python decompiler

~~~javascript
{python_source.rstrip()}
~~~

## Ghidra decompiler

~~~c
{ghidra_source.rstrip()}
~~~

## Artifacts

- `python.js`: selected function from the handwritten decompiler
- `ghidra.c`: Ghidra decompiler output
- `ghidra-full.txt`: Ghidra listing and decompiler output
- `comparison.diff`: textual diff of the two outputs
- `ghidra-metadata/bytecode.bin.entries`: additional handler/switch entry points
- `ghidra-console.log`, `ghidra-headless.log`, `ghidra-script.log`: diagnostics
"""
    report_path.write_text(report, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare Python and Ghidra decompilation of one V8 function"
    )
    parser.add_argument("input", help="V8 .jsc file or structured disassembly JSON")
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--function", help="exact SharedFunctionInfo name")
    selector.add_argument("--bytecode-index", type=int, help="BytecodeArray index")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="/tmp/v8asm-ghidra-compare",
        help="artifact directory (default: /tmp/v8asm-ghidra-compare)",
    )
    parser.add_argument(
        "--ghidra-home",
        default=os.environ.get("GHIDRA_HOME"),
        help="Ghidra installation directory (default: GHIDRA_HOME)",
    )
    parser.add_argument(
        "--java-home",
        default=os.environ.get("JAVA_HOME"),
        help="JDK directory (default: JAVA_HOME)",
    )
    parser.add_argument("--version", help="override V8 version detection")
    parser.add_argument("--runtime-variant")
    parser.add_argument("--snapshot-blob")
    parser.add_argument("--payload-offset", type=_parse_offset)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if not args.ghidra_home:
        parser.error("--ghidra-home or GHIDRA_HOME is required")
    if not args.java_home:
        parser.error("--java-home or JAVA_HOME is required")

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        parser.error(f"input does not exist: {input_path}")
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        document = _load_document(args)
        targets = _bytecode_targets(document)
        target = _select_target(targets, args.function, args.bytecode_index)
        (output_dir / "disassembly.json").write_text(
            json.dumps(document, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        raw_path = output_dir / "bytecode.bin"
        raw_path.write_bytes(target["raw"])

        python_source = _python_decompile(document, target["address"])
        ghidra_source, _ = _ghidra_decompile(
            raw_path,
            output_dir,
            Path(args.ghidra_home).resolve(),
            Path(args.java_home).resolve(),
            (
                target["name"]
                if target["name"] != "<anonymous>"
                else f"bytecode_{target['index']}"
            ),
            _additional_entry_points(document, target),
        )
        _write_report(
            output_dir,
            input_path,
            document,
            target,
            python_source,
            ghidra_source,
        )
    except (CompareError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"compare_decompilers: {exc}") from exc

    print(
        f"selected [{target['index']}] {target['name']} "
        f"({len(target['raw'])} bytes, {target['address']})"
    )
    print(f"comparison report: {output_dir / 'comparison.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
