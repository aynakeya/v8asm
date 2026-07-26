#!/usr/bin/env python3
"""Run Python/Ghidra decompiler comparisons over a V8 bytecode corpus."""

from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile

import compare_decompilers as compare


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return cleaned or "anonymous"


def _expand_inputs(values: list[str]) -> list[Path]:
    inputs: list[Path] = []
    for value in values:
        path = Path(value).resolve()
        if path.is_file():
            inputs.append(path)
            continue
        if not path.is_dir():
            raise compare.CompareError(f"input does not exist: {path}")
        candidates = sorted(path.glob("*/*.v8asm.jsc"))
        if not candidates:
            candidates = sorted(path.rglob("*.jsc"))
        inputs.extend(candidate.resolve() for candidate in candidates)
    unique = list(dict.fromkeys(inputs))
    if not unique:
        raise compare.CompareError("no .jsc inputs found")
    return unique


def _document_args(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        input=str(path),
        version=None,
        runtime_variant=None,
        snapshot_blob=None,
        payload_offset=None,
    )


def _case_name(path: Path) -> str:
    for suffix in (".v8asm.jsc", ".jsc", ".json"):
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return path.stem


def _prepare_entries(inputs: list[Path], output_dir: Path) -> list[dict]:
    raw_dir = output_dir / "bytecode"
    metadata_dir = output_dir / "ghidra-metadata"
    results_dir = output_dir / "results"
    raw_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for input_path in inputs:
        document = compare._load_document(_document_args(input_path))
        objects = compare.load_structured_objects(document)
        context = compare.DecompilerContext(objects)
        bytecodes = {
            obj.address: obj
            for obj in objects
            if isinstance(obj, compare.V8BytecodeArray)
        }
        for target in compare._bytecode_targets(document):
            ordinal = len(entries)
            name = (
                target["name"]
                if target["name"] != "<anonymous>"
                else f"anonymous_{target['index']}"
            )
            stem = (
                f"{ordinal:04d}_{_slug(_case_name(input_path))}_"
                f"b{target['index']}_{_slug(name)}"
            )
            raw_path = raw_dir / f"{stem}.bin"
            result_dir = results_dir / stem
            result_dir.mkdir(exist_ok=True)
            raw_path.write_bytes(target["raw"])
            additional_entries = compare._additional_entry_points(document, target)
            compare._write_entry_metadata(
                metadata_dir, raw_path.name, additional_entries
            )
            bytecode = bytecodes.get(int(target["address"], 16))
            if bytecode is None:
                raise compare.CompareError(
                    f"Python decompiler cannot find BytecodeArray {target['address']}"
                )
            python_source = compare._python_decompile_with_context(
                context, bytecode
            )
            (result_dir / "python.js").write_text(
                python_source, encoding="utf-8"
            )
            entries.append(
                {
                    "stem": stem,
                    "input": input_path,
                    "document": document,
                    "target": target,
                    "raw_path": raw_path,
                    "result_dir": result_dir,
                    "python_source": python_source,
                    "additional_entries": additional_entries,
                }
            )
    return entries


def _run_ghidra(
    raw_dir: Path,
    ghidra_output_dir: Path,
    metadata_dir: Path,
    output_dir: Path,
    ghidra_home: Path,
    java_home: Path,
) -> None:
    headless = ghidra_home / "support" / "analyzeHeadless"
    for path in (
        ghidra_home / "support" / "sleigh",
        headless,
        java_home / "bin" / "java",
    ):
        if not path.exists():
            raise compare.CompareError(f"required executable does not exist: {path}")

    with tempfile.TemporaryDirectory(prefix="v8asm-ghidra-corpus-") as temp_name:
        temp_dir = Path(temp_name)
        config_home = temp_dir / "config"
        project_dir = temp_dir / "projects"
        build_dir = temp_dir / "build"
        config_home.mkdir()
        project_dir.mkdir()
        build_dir.mkdir()

        env = os.environ.copy()
        env["JAVA_HOME"] = str(java_home)
        env["XDG_CONFIG_HOME"] = str(config_home)
        compare._install_language(
            ghidra_home,
            env,
            config_home,
            build_dir,
            output_dir / "sleigh.log",
        )
        compare._run_logged(
            [
                str(headless),
                str(project_dir),
                "v8corpus",
                "-import",
                str(raw_dir),
                "-recursive",
                "-processor",
                "V8Bytecode:LE:32:default",
                "-cspec",
                "default",
                "-overwrite",
                "-scriptPath",
                str(compare.GHIDRA_SCRIPT_DIR),
                "-postScript",
                "DumpV8Decompile.java",
                str(ghidra_output_dir),
                "AUTO",
                str(metadata_dir),
                "-log",
                str(output_dir / "ghidra-headless.log"),
                "-scriptlog",
                str(output_dir / "ghidra-script.log"),
                "-deleteProject",
            ],
            env,
            output_dir / "ghidra-console.log",
            "Ghidra corpus analysis",
        )


def _ghidra_status(contents: str) -> str:
    if "<decompile failed>" in contents:
        return "decompile_failed"
    if "Bad instruction" in contents or "halt_baddata" in contents:
        return "bad_instruction"
    return "ok"


def _collect_results(entries: list[dict], ghidra_output_dir: Path) -> None:
    marker = "== Decompile ==\n"
    combined: list[str] = ["/* Combined Ghidra output generated by compare_corpus.py. */\n"]
    for entry in entries:
        full_source = ghidra_output_dir / f"{entry['stem']}.bin.txt"
        result_dir = entry["result_dir"]
        if not full_source.exists():
            entry["ghidra_status"] = "missing_output"
            entry["ghidra_warnings"] = 0
            continue

        contents = full_source.read_text(encoding="utf-8", errors="replace")
        destination = result_dir / "ghidra-full.txt"
        destination.write_text(contents, encoding="utf-8")
        entry["ghidra_status"] = _ghidra_status(contents)
        entry["ghidra_warnings"] = contents.count("WARNING:")
        if marker not in contents:
            entry["ghidra_status"] = "missing_decompile_section"
            continue

        ghidra_source = contents.split(marker, 1)[1].strip() + "\n"
        (result_dir / "ghidra.c").write_text(ghidra_source, encoding="utf-8")
        combined.append(f"\n/* {entry['stem']} */\n")
        combined.append(ghidra_source)
        diff = "".join(
            difflib.unified_diff(
                entry["python_source"].splitlines(keepends=True),
                ghidra_source.splitlines(keepends=True),
                fromfile="python.js",
                tofile="ghidra.c",
            )
        )
        (result_dir / "comparison.diff").write_text(diff, encoding="utf-8")
    (ghidra_output_dir.parent / "ghidra-combined.c").write_text(
        "".join(combined), encoding="utf-8"
    )


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write_summary(entries: list[dict], output_dir: Path) -> int:
    failures = [entry for entry in entries if entry.get("ghidra_status") != "ok"]
    warning_entries = [entry for entry in entries if entry.get("ghidra_warnings", 0)]
    additional_entries = sum(len(entry["additional_entries"]) for entry in entries)
    lines = [
        "# V8 Ghidra corpus comparison",
        "",
        f"- Inputs: `{len({entry['input'] for entry in entries})}`",
        f"- Bytecode arrays: `{len(entries)}`",
        f"- Ghidra successful: `{len(entries) - len(failures)}`",
        f"- Ghidra failed: `{len(failures)}`",
        f"- Outputs with warnings: `{len(warning_entries)}`",
        f"- Additional handler/switch entries: `{additional_entries}`",
        "- Combined Ghidra output: [ghidra-combined.c](ghidra-combined.c)",
        "",
        "| input | function | index | bytes | instructions | extra entries | Ghidra | warnings | artifacts |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for entry in entries:
        target = entry["target"]
        relative = entry["result_dir"].relative_to(output_dir).as_posix()
        artifacts = (
            f"[Python]({relative}/python.js) / "
            f"[Ghidra]({relative}/ghidra.c) / "
            f"[listing]({relative}/ghidra-full.txt) / "
            f"[diff]({relative}/comparison.diff)"
            if entry.get("ghidra_status") == "ok"
            else f"[Python]({relative}/python.js)"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(entry["input"].parent.name),
                    _markdown_cell(target["name"]),
                    str(target["index"]),
                    str(len(target["raw"])),
                    str(len(target["record"].get("instructions", []))),
                    str(len(entry["additional_entries"])),
                    entry.get("ghidra_status", "missing"),
                    str(entry.get("ghidra_warnings", 0)),
                    artifacts,
                ]
            )
            + " |"
        )
    lines.append("")
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return len(failures)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare Python and Ghidra decompilers across a corpus"
    )
    parser.add_argument("inputs", nargs="+", help=".jsc files or a corpus directory")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="/tmp/v8asm-ghidra-corpus",
        help="artifact directory (default: /tmp/v8asm-ghidra-corpus)",
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
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if not args.ghidra_home:
        parser.error("--ghidra-home or GHIDRA_HOME is required")
    if not args.java_home:
        parser.error("--java-home or JAVA_HOME is required")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        inputs = _expand_inputs(args.inputs)
        entries = _prepare_entries(inputs, output_dir)
        ghidra_output_dir = output_dir / "ghidra-output"
        ghidra_output_dir.mkdir(exist_ok=True)
        _run_ghidra(
            output_dir / "bytecode",
            ghidra_output_dir,
            output_dir / "ghidra-metadata",
            output_dir,
            Path(args.ghidra_home).resolve(),
            Path(args.java_home).resolve(),
        )
        _collect_results(entries, ghidra_output_dir)
        failures = _write_summary(entries, output_dir)
    except (compare.CompareError, OSError, ValueError) as exc:
        raise SystemExit(f"compare_corpus: {exc}") from exc

    print(f"compared {len(entries)} BytecodeArray objects")
    print(f"summary: {output_dir / 'summary.md'}")
    print(f"combined Ghidra: {output_dir / 'ghidra-combined.c'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
