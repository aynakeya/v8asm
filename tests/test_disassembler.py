from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from disassembler.cache import parse_header
from disassembler.disassembler import (
    decode_instructions,
    disassemble_bytes,
    disassemble_file,
    parse_disassembly_file,
)
from disassembler.profiles import load_profiles
from disassembler.serializer import ObjectStreamParser, ParseError, RawChunk, Reference
from disassembler.snapshot import ReadOnlySnapshot
from disassembler.structured import disassembly_to_dict
from disassembler.structured_builder import StructuredGraphBuilder


ROOT = Path(__file__).resolve().parents[1]
from decompiler import decompile_objects
from decompiler.context import DecompilerContext
from decompiler.objects import V8Address, V8ArrayBoilerplateDescription, V8FixedArray, V8Hole
from decompiler.parser import parse_objects
from decompiler.structured import load_structured_objects


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


def array_boilerplate_signatures(
    text: str,
) -> list[tuple[str | None, int | None, int, str]]:
    objects = parse_objects(text.splitlines())
    context = DecompilerContext(objects)
    signatures: list[tuple[str | None, int | None, int, str]] = []
    for obj in objects:
        if not isinstance(obj, V8ArrayBoilerplateDescription):
            continue
        if obj.constant_elements is None:
            continue
        elements = context.get_object(obj.constant_elements.address)
        if not isinstance(elements, V8FixedArray):
            continue
        signatures.append(
            (
                obj.elements_kind,
                elements.length,
                len(elements.elements),
                context.format_value(V8Address(obj.address)),
            )
        )
    return signatures


class OfflineDisassemblerTests(unittest.TestCase):
    def test_structured_references_report_stable_provenance(self) -> None:
        parsed = parse_disassembly_file(ROOT / "samples" / "main.d8.jsc")
        builder = StructuredGraphBuilder(parsed)

        serialized = builder._reference(Reference("object", object_index=0))
        self.assertEqual(serialized["source"]["kind"], "serialized_object")
        self.assertEqual(serialized["source"]["id"], "serialized_object:0")
        self.assertEqual(serialized["resolution"], "serialized_object")
        self.assertIn("type_evidence", serialized)

        root = builder._reference(Reference("root", (4,)))
        self.assertEqual(root["source"]["kind"], "root")
        self.assertEqual(root["source"]["id"], "root:4")
        self.assertEqual(root["resolution"], "profile_metadata")
        self.assertEqual(root["literal"], "undefined")

        offset, value = next(iter(parsed.profile.read_only_strings.items()))
        read_only = builder._reference(Reference("read_only", (0, offset)))
        self.assertEqual(read_only["source"]["kind"], "read_only_heap")
        self.assertEqual(read_only["source"]["id"], f"read_only_heap:0:{offset}")
        self.assertEqual(read_only["resolution"], "profile_metadata")
        self.assertEqual(read_only["target_type"], "String")
        self.assertEqual(builder.records[read_only["address"]]["value"], value)

        for reference_kind, source_kind in (
            ("startup_cache", "startup_object_cache"),
            ("read_only_cache", "read_only_object_cache"),
            ("shared_cache", "shared_heap_object_cache"),
            ("attached", "attached_reference"),
        ):
            with self.subTest(reference_kind=reference_kind):
                reference = builder._reference(Reference(reference_kind, (7,)))
                self.assertEqual(reference["source"]["kind"], source_kind)
                self.assertEqual(reference["source"]["id"], f"{source_kind}:7")
                self.assertEqual(reference["resolution"], "unresolved")
                self.assertNotIn("target_type", reference)

    def test_structured_output_preserves_addressed_object_graph(self) -> None:
        parsed = parse_disassembly_file(ROOT / "samples" / "main.d8.jsc")
        document = disassembly_to_dict(parsed)

        self.assertEqual(document["schema"], "v8asm.disassembly")
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["metadata"]["v8_version"], parsed.profile.version)
        self.assertEqual(
            document["metadata"]["address_kind"],
            "synthetic_serializer_object",
        )
        self.assertEqual(
            document["metadata"]["header"]["payload_length"],
            parsed.header.payload_length,
        )

        objects = document["objects"]
        self.assertTrue(objects)
        self.assertEqual(set(document["object_order"]), set(objects))
        for address, record in objects.items():
            self.assertRegex(address, r"^0x[0-9a-f]{12}$")
            self.assertEqual(record["address"], address)
            self.assertIn("provenance", record)
            self.assertIn("type_evidence", record)

        bytecodes = [
            record for record in objects.values() if record["type"] == "BytecodeArray"
        ]
        self.assertEqual(len(bytecodes), 4)
        self.assertTrue(
            all(
                record["type_evidence"]["kind"] == "bytecode_array_layout"
                for record in bytecodes
            )
        )
        add = next(
            record
            for record in bytecodes
            if any(
                obj.get("type") == "SharedFunctionInfo"
                and obj.get("name_value") == "add"
                and obj.get("bytecode_address") == record["address"]
                for obj in objects.values()
            )
        )
        self.assertIn(add["constant_pool_address"], objects)
        self.assertTrue(add["instructions"])
        instruction = add["instructions"][0]
        self.assertIsInstance(instruction["operands"], list)
        self.assertIsInstance(instruction["arguments"], list)
        self.assertIn("raw_bytes", instruction)

    def test_disassembler_cli_emits_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "disassembler",
                str(ROOT / "samples" / "main.d8.jsc"),
                "--format",
                "json",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        document = json.loads(result.stdout)
        self.assertEqual(document["schema"], "v8asm.disassembly")
        self.assertEqual(document["metadata"]["bytecode_array_count"], 4)

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

    def test_repeated_serializer_references_preserve_identity_and_bounds(self) -> None:
        for version in ("10.2.154.26", "11.3.244.8", "13.6.233.10"):
            profile = load_profiles().by_version(version)
            tags = profile.serializer_tags
            legacy = "FixedRepeat" in tags
            fixed = tags["FixedRepeat" if legacy else "FixedRepeatRoot"]
            variable = tags["VariableRepeat" if legacy else "VariableRepeatRoot"]
            root = tags["RootArrayConstants"]
            for size in (4, 8):
                for count in (2, 20):
                    for nested in (False, True) if legacy else (False,):
                        with self.subTest(version=version, size=size, count=count, nested=nested):
                            repeat = bytes([fixed]) if count == 2 else bytes([variable]) + encode_uint30(count - 18)
                            target = bytes([root + 5]) if legacy else b"\x05"
                            if nested:
                                target = bytes([0]) + encode_uint30(1) + bytes([root])
                            body = repeat + target + bytes([tags["Synchronize"]]) + bytes([tags["Nop"]]) * 4
                            payload = bytes([0]) + encode_uint30(count + 1) + bytes([root]) + body
                            objects = ObjectStreamParser(payload, profile, size).parse()
                            expected = Reference("object", object_index=1) if nested else Reference("root", (5,))
                            self.assertEqual(objects[0].references, {slot * size: expected for slot in range(1, count + 1)})
                            truncated_owner = bytes([0]) + encode_uint30(count) + bytes([root]) + body
                            with self.assertRaisesRegex(ParseError, "repeated reference exceeds"):
                                ObjectStreamParser(truncated_owner, profile, size).parse()

    def test_numeric_object_values_and_bounds(self) -> None:
        parsed = parse_disassembly_file(ROOT / "tests/semantic_fixtures/numeric-literals.jsc")
        document = disassembly_to_dict(parsed)
        record = next(value for value in document["objects"].values()
                      if value["type"] == "FixedDoubleArray" and value["length"] == 5)
        obj = parsed.objects[record["serializer"]["object_index"]]
        layout = parsed.profile.number_layout
        start = layout["fixed_double_data_slot"] * parsed.tagged_size
        bits = ["0x8000000000000000", "0x7ff8000000000001", "0x7ff0000000000000",
                layout["hole_nan_bits"], "0xfff0000000000000"]
        image = bytearray(obj.image()[0])
        image[start:start + 40] = b"".join(int(value, 16).to_bytes(8, "little") for value in bits)

        def with_image(data):
            objects = list(parsed.objects)
            objects[obj.index] = replace(obj, raw_chunks=[RawChunk(0, 0, bytes(data))])
            return disassembly_to_dict(replace(parsed, objects=tuple(objects)))

        changed = with_image(image)
        encoded = changed["objects"][record["address"]]["elements"]
        self.assertEqual(encoded[:3], [{"kind": "float64", "bits": value} for value in bits[:3]])
        self.assertEqual(encoded[3:], [{"kind": "hole"}, {"kind": "float64", "bits": bits[4]}])
        json.dumps(changed, allow_nan=False)
        array = next(value for value in load_structured_objects(changed) if value.address == int(record["address"], 16))
        self.assertEqual(math.copysign(1, array.elements[0]), -1)
        self.assertTrue(math.isnan(array.elements[1]))
        self.assertEqual(array.elements[2], math.inf)
        self.assertIsInstance(array.elements[3], V8Hole)
        self.assertEqual(array.elements[4], -math.inf)
        incomplete = json.loads(json.dumps(changed))
        del incomplete["objects"][record["address"]]["elements"]
        with self.assertRaisesRegex(ValueError, "no numeric data"):
            load_structured_objects(incomplete)
        with self.assertRaisesRegex(ValueError, "structured JSON"):
            parse_objects(["0x1234: [FixedDoubleArray]", " - length: 1", " 0: 1.25"])
        ambiguous = bytearray(image)
        ambiguous[start:start + 8] = int(layout["undefined_nan_bits"], 16).to_bytes(8, "little")
        with self.assertRaisesRegex(ValueError, "requires confirmed build flags"):
            with_image(ambiguous)
        with self.assertRaisesRegex(ValueError, "missing numeric data"):
            with_image(image[:-1])
        offset = layout["fixed_double_length_slot"] * parsed.tagged_size
        shift = 32 if parsed.tagged_size == 8 else 1
        image[offset:offset + parsed.tagged_size] = (obj.size << shift).to_bytes(parsed.tagged_size, "little")
        with self.assertRaisesRegex(ValueError, "invalid FixedDoubleArray length"):
            with_image(image)

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

    def test_recovers_tracked_cache_bytecode_semantics(self) -> None:
        expected_counts = {"main.d8": 4, "main.node": 5}
        add_bytecode = bytes.fromhex("0b 04 3f 03 00 b3")
        for name, expected_count in expected_counts.items():
            with self.subTest(name=name):
                output = disassemble_file(ROOT / "samples" / f"{name}.jsc")
                blobs = bytecode_blobs(output)
                self.assertEqual(len(blobs), expected_count)
                self.assertTrue(all(blobs))
                self.assertIn(add_bytecode, blobs)

                objects = parse_objects(output.splitlines())
                context = DecompilerContext(objects)
                bytecodes = [
                    obj for obj in objects if obj.i_type == "BytecodeArray"
                ]
                names = [
                    context.get_function_name(
                        context.get_function_for_bytecode(bytecode)
                    )
                    for bytecode in bytecodes
                ]
                self.assertIn("add", names)
                self.assertIn("listSum", names)

    def test_reads_captured_input_as_normal_cached_data(self) -> None:
        source = ROOT / "samples" / "main.d8.jsc"
        expected = disassemble_file(source)
        with tempfile.TemporaryDirectory() as directory:
            captured = Path(directory) / "0000.input.jsc"
            captured.write_bytes(source.read_bytes())
            actual = disassemble_file(captured)
        self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))
        self.assertEqual(metadata_signature(actual), metadata_signature(expected))

    def test_detects_unaligned_checksum_header_from_payload_length(self) -> None:
        cache = (
            ROOT / "tests" / "fixtures" / "electron-13.2.152.41.jsc"
        ).read_bytes()
        profiles = load_profiles()
        aligned_header, profile = parse_header(cache, profiles)
        self.assertEqual(aligned_header.header_size, 32)
        self.assertEqual(cache[28:32], b"\0" * 4)

        unaligned = cache[:28] + cache[32:]
        header, detected_profile = parse_header(unaligned, profiles)
        self.assertEqual(header.header_size, 28)
        self.assertEqual(header.payload_length, len(unaligned) - 28)
        self.assertEqual(detected_profile.version, profile.version)

        expected = disassemble_bytes(cache)
        self.assertIn("tagged_size=4", expected)
        self.assertIn('[String]: "answer"', expected)
        actual = disassemble_bytes(unaligned)
        self.assertEqual(bytecode_blobs(actual), bytecode_blobs(expected))
        self.assertEqual(metadata_signature(actual), metadata_signature(expected))

    def test_rejects_ambiguous_cached_data_header_layout(self) -> None:
        profile = load_profiles().by_version("13.2.152.41")
        cache = bytearray(40)
        cache[0:4] = (0xC0DE0673).to_bytes(4, "little")
        cache[4:8] = profile.version_hash.to_bytes(4, "little")
        cache[16:20] = (16).to_bytes(4, "little")
        cache[20:24] = (12).to_bytes(4, "little")

        with self.assertRaisesRegex(ValueError, "header layout is ambiguous"):
            parse_header(bytes(cache), load_profiles())

    def test_node_capture_hook_writes_input_and_normalized_cache(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")
        hook = ROOT / "disassembler" / "capture_cached_data.cjs"
        expected_words = [f"value-{index:04d}" for index in range(3000)]
        expected_words[:5] = [
            "config",
            "NEW_APP_NAME",
            "removeSwitch",
            "isOpenDevTools",
            "array-start",
        ]
        expected_words[2677] = "remote-debugging-port"
        compiled_source = (
            "const words="
            + json.dumps(expected_words, separators=(",", ":"))
            + ";globalThis.answer=words[2677]"
        )
        source = (
            'const vm=require("node:vm");'
            f"const source={json.dumps(compiled_source)};"
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

            disassembly = disassemble_file(
                normalized_path, version=metadata["v8_version"]
            )
            self.assertIn("[ArrayBoilerplateDescription]", disassembly)
            self.assertIn("[FixedArray]", disassembly)
            expected_rendering = json.dumps(expected_words)
            matches = [
                signature
                for signature in array_boilerplate_signatures(disassembly)
                if signature[3] == expected_rendering
            ]
            self.assertEqual(len(matches), 1)
            _, declared_length, parsed_length, rendered = matches[0]
            self.assertEqual((declared_length, parsed_length), (3000, 3000))
            self.assertEqual(json.loads(rendered), expected_words)

    def test_recovers_fixed_array_contents_without_v8asm_output(self) -> None:
        output = disassemble_file(ROOT / "samples" / "main.d8.jsc")
        self.assertIn("[ArrayBoilerplateDescription]", output)
        self.assertIn(" - elements kind:", output)
        self.assertIn(" - constant elements:", output)
        self.assertIn("[FixedArray]", output)

        matches = [
            signature
            for signature in array_boilerplate_signatures(output)
            if signature[3] == "[1, 2, 3, 4, 5]"
        ]
        self.assertEqual(len(matches), 1)
        _, declared_length, parsed_length, _ = matches[0]
        self.assertEqual((declared_length, parsed_length), (5, 5))

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

    def test_recovers_self_cache_version_matrix(self) -> None:
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
                self.assertTrue(all(bytecode_blobs(actual)))

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

                parsed = parse_disassembly_file(path)
                structured_objects = load_structured_objects(
                    disassembly_to_dict(parsed)
                )
                structured_context = DecompilerContext(structured_objects)
                structured_bytecodes = [
                    obj
                    for obj in structured_objects
                    if obj.i_type == "BytecodeArray"
                ]
                structured_names = [
                    structured_context.get_function_name(
                        structured_context.get_function_for_bytecode(bytecode)
                    )
                    for bytecode in structured_bytecodes
                ]
                self.assertEqual(structured_names, names)
                decompiled = decompile_objects(structured_objects, linear=True)
                self.assertIn("function calc(", decompiled)
                recognized += 1
        self.assertEqual(recognized, 26)

    def test_recovers_real_electron_and_bytenode_caches(self) -> None:
        electron = ROOT / "tests" / "decomp_rounds" / "electron_matrix"
        for path in sorted(electron.glob("*/electron-case.jsc")):
            with self.subTest(cache=path.parent.name):
                actual = disassemble_file(path)
                objects = parse_objects(actual.splitlines())
                context = DecompilerContext(objects)
                bytecodes = [
                    obj for obj in objects if obj.i_type == "BytecodeArray"
                ]
                names = [
                    context.get_function_name(
                        context.get_function_for_bytecode(bytecode)
                    )
                    for bytecode in bytecodes
                ]
                self.assertEqual(len(bytecodes), 3)
                self.assertIn("calc", names)
                self.assertEqual(actual.count("[SharedFunctionInfo]"), 3)

        matrix = ROOT / "tests" / "decomp_rounds" / "version_matrix"
        for node_version in ("18.20.8", "20.20.2", "22.17.0", "24.7.0"):
            with self.subTest(node=node_version):
                path = (
                    matrix
                    / f"bytenode-{node_version}"
                    / "01_arith.bytenode.jsc"
                )
                actual = disassemble_file(path)
                objects = parse_objects(actual.splitlines())
                context = DecompilerContext(objects)
                bytecodes = [
                    obj for obj in objects if obj.i_type == "BytecodeArray"
                ]
                names = [
                    context.get_function_name(
                        context.get_function_for_bytecode(bytecode)
                    )
                    for bytecode in bytecodes
                ]
                self.assertEqual(len(bytecodes), 3)
                self.assertIn("calc", names)
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
