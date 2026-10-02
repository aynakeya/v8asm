"""Compile and compare the complete Taskboard fixture using one selected Node."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decompiler import decompile_objects
from decompiler.context import DecompilerContext
from decompiler.core import _decompile_function_tree
from decompiler.objects import V8BytecodeArray
from decompiler.runtime import runtime_prelude
from decompiler.structured import load_structured_objects
from disassembler.disassembler import parse_disassembly_file
from disassembler.structured import disassembly_to_dict

FIXTURE = ROOT / "tests" / "application_fixture"
SCENARIOS = {
    "parser": ("tokenize", "parseCommand"),
    "workflow": ("tokenize", "parseCommand", "createBoard", "execute", "runCommands"),
    "transactions": ("createBoard", "transactionScenario"),
    "selection": ("selectionScenario",),
    "plugins": ("pluginScenario",),
    "iterators": ("iteratorScenario",),
    "classes": ("classScenario",),
    "advanced_classes": ("advancedClassScenario",),
    "generators": ("generatorScenario",),
    "async": ("asyncScenario",),
    "codec": ("codecScenario",),
}


def observe(node: str, source: str, scenario: str) -> dict:
    try:
        result = subprocess.run(
            [node, str(FIXTURE / "taskboard.cjs"), "--observe"],
            input=json.dumps({"source": source, "scenario": scenario}),
            text=True, capture_output=True, timeout=8,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "message": "observer process exceeded 8 seconds"}
    if result.returncode not in (0, 1) or not result.stdout:
        return {"status": "observer_error", "message": result.stderr[-2000:]}
    return json.loads(result.stdout)


def first_difference(expected: object, actual: object, path: str = "$") -> dict | None:
    if type(expected) is not type(actual):
        return {"path": path, "expected": expected, "actual": actual}
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return {"path": path, "expected_keys": sorted(expected), "actual_keys": sorted(actual)}
        for key in expected:
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            return {"path": path + ".length", "expected": len(expected), "actual": len(actual)}
        for index, (left, right) in enumerate(zip(expected, actual)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
    elif expected != actual:
        return {"path": path, "expected": expected, "actual": actual}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default="node", help="Node used for compilation and both observations")
    parser.add_argument("--out", type=Path, default=ROOT / "tests/decomp_rounds/out/taskboard")
    parser.add_argument("--snapshot-blob", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source_path = FIXTURE / "taskboard.js"
    source = source_path.read_text(encoding="utf-8")
    versions = json.loads(subprocess.check_output(
        [args.node, "-p", "JSON.stringify(process.versions)"], text=True, timeout=10,
    ))
    cache = args.out / "taskboard.jsc"
    subprocess.run(
        [args.node, "--no-lazy", str(ROOT / "tests/fixtures/generate_cached_data.cjs"),
         str(source_path), str(cache)], check=True, timeout=30,
    )
    report = {
        "node_version": versions["node"], "v8_version": versions["v8"],
        "electron_version": versions.get("electron"),
        "compile_flags": ["--no-lazy"],
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "cache_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "snapshot_blob": str(args.snapshot_blob.resolve()) if args.snapshot_blob else None,
        "scenarios": {},
    }
    # Keep the observations even when parsing or code generation fails.
    expected = {case: observe(args.node, source, case) for case in SCENARIOS}
    recovered = None
    roots = {}
    stage = "disassemble"
    try:
        parsed = parse_disassembly_file(cache, version=versions["v8"], snapshot_blob=args.snapshot_blob)
        document = disassembly_to_dict(parsed)
        report["disassembly_metadata"] = document["metadata"]
        (args.out / "taskboard.disasm.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
        stage = "decompile"
        objects = load_structured_objects(document)
        recovered = decompile_objects(objects, runtime=True)
        (args.out / "taskboard.decompiled.js").write_text(recovered, encoding="utf-8")
        report["warnings"] = [line.strip() for line in recovered.splitlines() if "// WARNING:" in line]
        syntax = subprocess.run(
            [args.node, "--check", str(args.out / "taskboard.decompiled.js")],
            text=True, capture_output=True, timeout=10,
        )
        report["syntax"] = {"ok": syntax.returncode == 0, "stderr": syntax.stderr}
        # Diagnose whole function trees, without editing failed output or deleting
        # unsupported operations. These probes never count as a full-app pass.
        context = DecompilerContext(objects)
        selected_names = {"taskboard", *(name for names in SCENARIOS.values() for name in names)}
        for obj in objects:
            if not isinstance(obj, V8BytecodeArray):
                continue
            owner = context.get_function_for_bytecode(obj)
            if owner and owner.name_value in selected_names:
                roots[owner.name_value] = _decompile_function_tree(context, obj, False)
    except Exception as error:
        report["pipeline_error"] = {"stage": stage, "type": type(error).__name__, "message": str(error)}
        print(f"{stage}: {type(error).__name__}: {error}")

    if "syntax" in report and not report["syntax"]["ok"]:
        print(report["syntax"]["stderr"].strip())

    for case in SCENARIOS:
        if not report.get("syntax", {}).get("ok", False):
            actual = {"status": "syntax_error" if recovered is not None else "not_run"}
        else:
            actual = observe(args.node, recovered, case)
        difference = first_difference(expected[case], actual)
        equivalent = expected[case]["status"] == "ok" and actual["status"] == "ok" and difference is None
        report["scenarios"][case] = {
            "equivalent": equivalent, "source": expected[case], "recovered": actual,
            "first_difference": difference,
        }
        if roots:
            isolated = "\n\n".join([
                runtime_prelude(), *(roots[name] for name in (*SCENARIOS[case], "taskboard")),
                "globalThis.taskboard = taskboard;",
            ])
            (args.out / f"{case}.isolated.js").write_text(isolated, encoding="utf-8")
            probe = observe(args.node, isolated, case)
            probe_difference = first_difference(expected[case], probe)
            probe_equivalent = expected[case]["status"] == "ok" and probe["status"] == "ok" and probe_difference is None
            report["scenarios"][case]["isolated"] = {
                "equivalent": probe_equivalent, "recovered": probe, "first_difference": probe_difference,
            }
            print(f"{case}: full={'PASS' if equivalent else 'FAIL'}, "
                  f"isolated={'PASS' if probe_equivalent else 'FAIL'} "
                  f"{probe.get('message', probe_difference) or ''}")
        else:
            print(f"{case}: {'PASS' if equivalent else 'FAIL'} {actual.get('message', difference)}")
    passed = sum(case["equivalent"] for case in report["scenarios"].values())
    report["summary"] = {
        "passed": passed, "total": len(SCENARIOS),
        "isolated_passed": sum(case.get("isolated", {}).get("equivalent", False)
                               for case in report["scenarios"].values()),
    }
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{passed}/{len(SCENARIOS)} equivalent; artifacts: {args.out}")
    return 0 if passed == len(SCENARIOS) and not report.get("warnings") and not report.get("pipeline_error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
