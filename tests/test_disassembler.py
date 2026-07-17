from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from disassembler.cache import parse_header
from disassembler.disassembler import (
    decode_instructions,
    disassemble_bytes,
    disassemble_file,
)
from disassembler.profiles import load_profiles
from disassembler.serializer import ObjectStreamParser
from disassembler.snapshot import ReadOnlySnapshot


ROOT = Path(__file__).resolve().parents[1]
DECOMPILER = ROOT / "decompiler"
if str(DECOMPILER) not in sys.path:
    sys.path.insert(0, str(DECOMPILER))

from context import DecompilerContext
from parser import parse_objects


BYTECODE_ARRAY_RE = re.compile(r"^\s*0x[0-9a-f]+:\s+\[BytecodeArray\]", re.I)
INSTRUCTION_RE = re.compile(
    r"@\s*(\d+)\s*:\s*([0-9a-f]{2}(?:\s+[0-9a-f]{2})*)", re.I
)
HANDLER_RE = re.compile(
    r"\(\s*(\d+),\s*(\d+)\)\s*->\s*(\d+)\s*"
    r"\(prediction=(\d+),\s*data=(-?\d+)\)"
)


def encode_uint30(value: int) -> bytes:
    encoded = value << 2
    size = max(1, (encoded.bit_length() + 7) // 8)
    return (encoded | (size - 1)).to_bytes(size, "little")


def static_snapshot_blob(
    version: str,
    magic: int,
    checksum: int,
    objects: bytes,
) -> bytes:
    payload = b"".join(
        (
            b"\x01",
            encode_uint30(0),
            encode_uint30(len(objects)),
            (0).to_bytes(4, "little"),
            b"\x02",
            encode_uint30(0),
            encode_uint30(0),
            encode_uint30(len(objects)),
            objects,
            b"\x04\x05",
        )
    )
    return snapshot_container(version, magic, checksum, payload)


def snapshot_container(
    version: str, magic: int, checksum: int, payload: bytes
) -> bytes:
    header = bytearray(96)
    header[0:4] = (1).to_bytes(4, "little")
    header[4:8] = (1).to_bytes(4, "little")
    header[12:16] = checksum.to_bytes(4, "little")
    version_bytes = version.encode("ascii")
    header[16 : 16 + len(version_bytes)] = version_bytes
    startup = magic.to_bytes(4, "little") + (0).to_bytes(4, "little")
    read_only_offset = len(header) + len(startup)
    read_only = magic.to_bytes(4, "little") + len(payload).to_bytes(4, "little") + payload
    shared_heap_offset = read_only_offset + len(read_only)
    header[80:84] = read_only_offset.to_bytes(4, "little")
    header[84:88] = shared_heap_offset.to_bytes(4, "little")
    header[88:92] = shared_heap_offset.to_bytes(4, "little")
    return bytes(header) + startup + read_only


def bytecode_blobs(text: str) -> list[bytes]:
    blocks: list[dict[int, bytes]] = []
    current: dict[int, bytes] | None = None
    for line in text.splitlines():
        if BYTECODE_ARRAY_RE.search(line):
            current = {}
            blocks.append(current)
            continue
        match = INSTRUCTION_RE.search(line)
        if current is not None and match:
            current[int(match.group(1))] = bytes.fromhex(match.group(2))
    result: list[bytes] = []
    for block in blocks:
        size = max(offset + len(raw) for offset, raw in block.items())
        blob = bytearray(size)
        for offset, raw in block.items():
            blob[offset : offset + len(raw)] = raw
        result.append(bytes(blob))
    return result


def metadata_signature(text: str) -> tuple[object, ...]:
    prefixes = (
        "Parameter count ",
        "Register count ",
        "Frame size ",
        "Constant pool (size = ",
        "Handler Table (size = ",
        "Source Position Table (size = ",
    )
    scalar_values = tuple(
        (
            prefix,
            tuple(
                int(value)
                for value in re.findall(
                    rf"^{re.escape(prefix)}(\d+)", text, flags=re.M
                )
            ),
        )
        for prefix in prefixes
    )
    handlers = tuple(HANDLER_RE.findall(text))
    runtime_names = tuple(re.findall(r"CallRuntime \[([^\]]+)\]", text))
    jump_targets = tuple(
        int(value) for value in re.findall(r"\(0x[0-9a-f]+ @ (\d+)\)", text, re.I)
    )
    return scalar_values, handlers, runtime_names, jump_targets


class OfflineDisassemblerTests(unittest.TestCase):
    def test_resolves_static_read_only_snapshot_strings(self) -> None:
        profile = load_profiles().by_version("13.4.114.21")
        one_byte_map = next(
            pointer
            for pointer, name in profile.static_root_maps.items()
            if name == "InternalizedOneByteStringMap"
        )
        two_byte_map = next(
            pointer
            for pointer, name in profile.static_root_maps.items()
            if name == "InternalizedTwoByteStringMap"
        )
        objects = b"".join(
            (
                one_byte_map.to_bytes(4, "little"),
                b"\0" * 4,
                (3).to_bytes(4, "little"),
                b"abc\0",
                two_byte_map.to_bytes(4, "little"),
                b"\0" * 4,
                (1).to_bytes(4, "little"),
                "\u03a9".encode("utf-16-le"),
                b"\0\0",
            )
        )
        blob = static_snapshot_blob(
            "13.4.114.21-electron.0", 0xC0DE0687, 0x12345678, objects
        )
        snapshot = ReadOnlySnapshot.parse(blob, profile, 4)
        self.assertEqual(snapshot.string_at(0, 16), "abc")
        self.assertEqual(snapshot.string_at(0, 32), "\u03a9")
        self.assertIsNone(snapshot.string_at(0, 48))

    def test_resolves_relocatable_read_only_snapshot_strings(self) -> None:
        profile = load_profiles().by_version("13.2.152.41")
        map_index = profile.root_names.index("InternalizedOneByteStringMap")
        root_offsets = [16 + index * 4 for index in range(map_index + 1)]
        roots = [((offset // 4) << 14).to_bytes(4, "little") for offset in root_offsets]
        page = bytearray(544)
        map_reference = (root_offsets[map_index] // 4) << 14
        page[512:516] = map_reference.to_bytes(4, "little")
        page[520:524] = (4).to_bytes(4, "little")
        page[524:528] = b"node"
        relocation = bytearray(((len(page) // 4) + 7) // 8)
        relocation[(512 // 4) // 8] |= 1 << ((512 // 4) % 8)
        payload = b"".join(
            (
                b"\x00",
                encode_uint30(0),
                encode_uint30(len(page)),
                b"\x02",
                encode_uint30(0),
                encode_uint30(0),
                encode_uint30(len(page)),
                bytes(page),
                b"\x03",
                bytes(relocation),
                b"\x04",
                *roots,
                b"\x05",
            )
        )
        blob = snapshot_container(
            profile.version, 0xC0DE0687, 0x12345678, payload
        )
        snapshot = ReadOnlySnapshot.parse(blob, profile, 4)
        self.assertFalse(snapshot.static_roots)
        self.assertEqual(snapshot.string_at(0, 528), "node")

    def test_snapshot_is_checked_before_disassembly(self) -> None:
        cache = (ROOT / "samples" / "main.d8.jsc").read_bytes()
        profile = load_profiles().by_hash(int.from_bytes(cache[4:8], "little"))
        map_pointer = next(
            pointer
            for pointer, name in profile.static_root_maps.items()
            if name == "InternalizedOneByteStringMap"
        )
        objects = (
            map_pointer.to_bytes(4, "little")
            + b"\0" * 4
            + (1).to_bytes(4, "little")
            + b"x\0\0\0"
        )
        blob = static_snapshot_blob(
            profile.version,
            int.from_bytes(cache[0:4], "little"),
            int.from_bytes(cache[16:20], "little"),
            objects,
        )
        expected = disassemble_bytes(cache)
        actual = disassemble_bytes(cache, snapshot_blob=blob)
        self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))

        bad_blob = bytearray(blob)
        bad_blob[12:16] = (0xDEADBEEF).to_bytes(4, "little")
        with self.assertRaisesRegex(ValueError, "checksum.*does not match"):
            disassemble_bytes(cache, snapshot_blob=bytes(bad_blob))

    def test_resolves_serializer_forward_reference(self) -> None:
        profile = load_profiles().by_version("13.4.114.21")
        tags = profile.serializer_tags
        root = tags["RootArrayConstants"]
        payload = bytes(
            (
                0,
                2 << 2,
                root,
                tags["RegisterPendingForwardRef"],
                0,
                2 << 2,
                root,
                tags["ResolvePendingForwardRef"],
                0,
                root,
                tags["Synchronize"],
                tags["Nop"],
                tags["Nop"],
                tags["Nop"],
            )
        )
        objects = ObjectStreamParser(payload, profile, 4).parse()
        self.assertEqual(len(objects), 2)
        self.assertEqual(objects[0].references[4].kind, "forward")
        self.assertEqual(objects[0].references[4].object_index, 1)

    def test_decodes_known_13_6_sequence(self) -> None:
        profiles = load_profiles()
        profile = profiles.by_version("13.6.233.10")
        raw = bytes.fromhex("0b 04 3f 03 00 ce 0b 05 3f f9 01 1b f9 f8 ce 4d 02 02 b3")
        instructions = decode_instructions(raw, profile, profiles)
        self.assertEqual(
            [instruction.name for instruction in instructions],
            ["Ldar", "Add", "Star0", "Ldar", "Add", "Mov", "Star0", "MulSmi", "Return"],
        )
        self.assertEqual(b"".join(instruction.raw for instruction in instructions), raw)

    def test_matches_tracked_v8asm_bytecode_arrays(self) -> None:
        for name in ("main.d8", "main.node"):
            with self.subTest(name=name):
                actual = disassemble_file(ROOT / "samples" / f"{name}.jsc")
                expected = (ROOT / "samples" / f"{name}.jsc.txt").read_text()
                self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))

    def test_reads_captured_input_as_normal_cached_data(self) -> None:
        source = ROOT / "samples" / "main.d8.jsc"
        expected = disassemble_file(source)
        with tempfile.TemporaryDirectory() as directory:
            captured = Path(directory) / "0000.input.jsc"
            captured.write_bytes(source.read_bytes())
            actual = disassemble_file(captured)
        self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))
        self.assertEqual(metadata_signature(actual), metadata_signature(expected))

    def test_node_capture_hook_writes_input_and_normalized_cache(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")
        hook = ROOT / "disassembler" / "capture_cached_data.cjs"
        source = (
            'const vm=require("node:vm");'
            'const source="globalThis.answer=21*2";'
            "const seed=new vm.Script(source);"
            "const cache=seed.createCachedData();"
            "const loaded=new vm.Script(source,{"
            'filename:"capture-test.js",cachedData:cache});'
            "if(loaded.cachedDataRejected)process.exitCode=2;"
            "console.log(process.pid);"
        )
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.pop("NODE_OPTIONS", None)
            environment["V8_CACHE_DUMP_DIR"] = directory
            result = subprocess.run(
                [node, "--require", str(hook), "-e", source],
                check=True,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
            )
            output = Path(directory) / result.stdout.strip()
            input_path = output / "0000.input.jsc"
            normalized_path = output / "0000.normalized.jsc"
            payload_path = output / "0000.payload.bin"
            metadata = json.loads((output / "0000.json").read_text())
            self.assertGreater(input_path.stat().st_size, 0)
            self.assertGreater(normalized_path.stat().st_size, 0)
            self.assertGreater(payload_path.stat().st_size, 0)
            self.assertFalse(metadata["cached_data_rejected"])
            self.assertRegex(metadata["v8_version"], r"^\d+\.\d+\.\d+")
            self.assertEqual(metadata["input_size"], input_path.stat().st_size)
            self.assertEqual(
                metadata["normalized_size"], normalized_path.stat().st_size
            )
            self.assertEqual(metadata["payload_size"], payload_path.stat().st_size)
            normalized = normalized_path.read_bytes()
            payload_offset = metadata["payload_offset"]
            self.assertEqual(payload_path.read_bytes(), normalized[payload_offset:])
            self.assertEqual(metadata["filename"], "capture-test.js")

    def test_parses_raw_serializer_payload_at_explicit_offset(self) -> None:
        cache = (ROOT / "samples" / "main.d8.jsc").read_bytes()
        profiles = load_profiles()
        header, profile = parse_header(cache, profiles)
        payload = cache[
            header.header_size : header.header_size + header.payload_length
        ]
        prefix = b"private wrapper"
        actual = disassemble_bytes(
            prefix + payload,
            version=profile.version,
            runtime_variant=profile.runtime_variant_by_flags_hash.get(
                header.flags_hash
            ),
            payload_offset=len(prefix),
        )
        expected = disassemble_bytes(cache)
        self.assertIn(
            f"# raw_serializer_payload offset={len(prefix)} tagged_size=", actual
        )
        self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))
        self.assertEqual(metadata_signature(actual), metadata_signature(expected))

        with self.assertRaisesRegex(ValueError, "requires an explicit V8 version"):
            disassemble_bytes(payload, payload_offset=0)

    def test_matches_self_cache_version_matrix(self) -> None:
        recognized = 0
        matrix = ROOT / "tests" / "decomp_rounds" / "version_matrix"
        for path in sorted(matrix.glob("self-v8asm.*/01_arith.jsc")):
            with self.subTest(build=path.parent.name):
                try:
                    actual = disassemble_file(path)
                except ValueError as exc:
                    if "unknown V8 version hash" in str(exc):
                        continue
                    raise
                expected = path.with_name("01_arith.disasm.txt").read_text(
                    errors="replace"
                )
                self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))
                self.assertEqual(metadata_signature(actual), metadata_signature(expected))

                objects = parse_objects(actual.splitlines())
                context = DecompilerContext(objects)
                bytecodes = [
                    obj for obj in objects if obj.i_type == "BytecodeArray"
                ]
                self.assertEqual(len(bytecodes), 2)
                self.assertEqual(len(context.bytecode_functions), 2)
                names = [
                    context.get_function_name(
                        context.get_function_for_bytecode(bytecode)
                    )
                    for bytecode in bytecodes
                ]
                self.assertIn("calc", names)
                recognized += 1
        self.assertEqual(recognized, 26)

    def test_matches_real_electron_and_bytenode_caches(self) -> None:
        electron = ROOT / "tests" / "decomp_rounds" / "electron_matrix"
        for path in sorted(electron.glob("*/electron-case.jsc")):
            with self.subTest(cache=path.parent.name):
                expected_paths = list(
                    path.parent.glob("*/v8_context_snapshot/disasm.txt")
                )
                self.assertEqual(len(expected_paths), 1)
                actual = disassemble_file(path)
                expected = expected_paths[0].read_text(errors="replace")
                self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))
                self.assertEqual(metadata_signature(actual), metadata_signature(expected))
                self.assertEqual(
                    actual.count("[SharedFunctionInfo]"),
                    len(bytecode_blobs(expected)),
                )

        matrix = ROOT / "tests" / "decomp_rounds" / "version_matrix"
        bytenode_builds = {
            "18.20.8": "10.2.node18",
            "20.20.2": "11.3.node20",
            "22.17.0": "12.4.node22",
            "24.7.0": "13.6.node24",
        }
        for node_version, build in bytenode_builds.items():
            with self.subTest(node=node_version):
                path = (
                    matrix
                    / f"bytenode-{node_version}"
                    / "01_arith.bytenode.jsc"
                )
                expected_paths = list(
                    matrix.glob(
                        f"bytenode-{node_version}-v8asm.{build}.x64.release/"
                        "01_arith.force.disasm.txt"
                    )
                )
                self.assertEqual(len(expected_paths), 1)
                actual = disassemble_file(path)
                expected = expected_paths[0].read_text(errors="replace")
                self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))
                self.assertEqual(metadata_signature(actual), metadata_signature(expected))
                self.assertEqual(actual.count("[SharedFunctionInfo]"), 3)

    def test_recovers_metadata_constants_and_handlers(self) -> None:
        output = disassemble_file(ROOT / "samples" / "main.d8.jsc")
        self.assertIn("CallRuntime [DeclareGlobals]", output)
        self.assertIn("CallRuntime [ThrowIteratorResultNotAnObject]", output)
        self.assertIn("Parameter count 2\nRegister count 14\nFrame size 112", output)
        self.assertIn("Constant pool (size = 6)", output)
        self.assertIn("Handler Table (size = 32)", output)
        self.assertIn("(  19,  65)  ->    71 (prediction=0, data=10)", output)
        self.assertIn('[String]: "console"', output)
        self.assertIn('[String]: "nums"', output)

        objects = parse_objects(output.splitlines())
        context = DecompilerContext(objects)
        bytecodes = [obj for obj in objects if obj.i_type == "BytecodeArray"]
        self.assertEqual(len(bytecodes), 4)
        self.assertEqual(len(context.bytecode_constant_pools), 3)
        self.assertEqual(
            context.get_function_name(context.get_function_for_bytecode(bytecodes[1])),
            "add",
        )
        self.assertEqual(
            context.get_function_name(context.get_function_for_bytecode(bytecodes[2])),
            "listSum",
        )
        values = [
            context.format_value(entry.raw)
            for entry in context.constant_pool_entries(bytecodes[-1])
        ]
        self.assertEqual(values[0], '"console"')
        self.assertEqual(values[-1], '"nums"')


if __name__ == "__main__":
    unittest.main()
