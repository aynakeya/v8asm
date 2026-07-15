from __future__ import annotations

from dataclasses import dataclass, field

from .profiles import Profile


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Reference:
    kind: str
    values: tuple[int, ...] = ()
    object_index: int | None = None


@dataclass(frozen=True)
class RawChunk:
    object_offset: int
    payload_offset: int
    data: bytes


@dataclass
class SerializedObject:
    index: int
    space: int
    size: int
    payload_offset: int
    map_reference: Reference | None = None
    references: dict[int, Reference] = field(default_factory=dict)
    raw_chunks: list[RawChunk] = field(default_factory=list)

    def image(self) -> tuple[bytes, bytes]:
        data = bytearray(self.size)
        present = bytearray(self.size)
        for chunk in self.raw_chunks:
            end = chunk.object_offset + len(chunk.data)
            data[chunk.object_offset:end] = chunk.data
            present[chunk.object_offset:end] = b"\x01" * len(chunk.data)
        return bytes(data), bytes(present)


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def byte(self) -> int:
        if self.position >= len(self.data):
            raise ParseError("unexpected end of serializer payload")
        value = self.data[self.position]
        self.position += 1
        return value

    def raw(self, size: int) -> tuple[int, bytes]:
        if size < 0 or self.position + size > len(self.data):
            raise ParseError("raw serializer data exceeds payload")
        start = self.position
        self.position += size
        return start, self.data[start : start + size]

    def uint30(self) -> int:
        if self.position + 4 > len(self.data):
            raise ParseError("truncated serializer uint30")
        first = self.data[self.position]
        size = (first & 3) + 1
        value = int.from_bytes(self.data[self.position : self.position + size], "little")
        self.position += size
        return value >> 2

    def uint32(self) -> int:
        _, raw = self.raw(4)
        return int.from_bytes(raw, "little")


class ObjectStreamParser:
    def __init__(self, payload: bytes, profile: Profile, tagged_size: int) -> None:
        if tagged_size not in (4, 8):
            raise ValueError("tagged_size must be 4 or 8")
        self.reader = Reader(payload)
        self.profile = profile
        self.tagged_size = tagged_size
        self.system_pointer_size = 8
        self.tags = profile.serializer_tags
        self.objects: list[SerializedObject] = []
        self.hot_objects: list[Reference | None] = [None] * 8
        self.hot_index = 0
        self.pending_forward_refs: list[
            tuple[SerializedObject, int] | None
        ] = []
        self.pending_forward_ref_count = 0

    def parse(self) -> list[SerializedObject]:
        consumed, _ = self._reference(self.reader.byte(), None, 0)
        if consumed != 1:
            raise ParseError("root serializer entry did not produce one object")
        synchronize = self.tags["Synchronize"]
        while True:
            tag = self.reader.byte()
            if tag == synchronize:
                break
            if not 0 <= tag < self.profile.snapshot_spaces:
                raise ParseError(
                    f"expected deferred object at 0x{self.reader.position - 1:x}, "
                    f"got 0x{tag:02x}"
                )
            self._object(tag)
        while self.reader.position < len(self.reader.data):
            if self.reader.byte() != self.tags["Nop"]:
                raise ParseError("non-padding data follows the serializer terminator")
        if self.pending_forward_ref_count:
            raise ParseError("serializer payload has unresolved forward references")
        return self.objects

    def _object(self, space: int) -> SerializedObject:
        start = self.reader.position - 1
        size_in_tagged = self.reader.uint30()
        size = size_in_tagged * self.tagged_size
        if size < self.tagged_size or size > 512 * 1024 * 1024:
            raise ParseError(f"implausible serialized object size {size}")
        obj = SerializedObject(len(self.objects), space, size, start)
        self.objects.append(obj)

        _, map_reference = self._reference(self.reader.byte(), None, 0)
        obj.map_reference = map_reference
        current = 1
        while current < size_in_tagged:
            tag = self.reader.byte()
            consumed, reference = self._reference(tag, obj, current)
            if consumed < 0 or current + consumed > size_in_tagged:
                raise ParseError(f"serializer entry overruns object {obj.index}")
            if reference is not None and consumed:
                obj.references[current * self.tagged_size] = reference
            current += consumed
        if current != size_in_tagged:
            raise ParseError(
                f"object {obj.index} ended at slot {current}, "
                f"expected {size_in_tagged}"
            )
        return obj

    def _reference(
        self, tag: int, obj: SerializedObject | None, slot: int
    ) -> tuple[int, Reference | None]:
        tags = self.tags
        if 0 <= tag < self.profile.snapshot_spaces:
            nested = self._object(tag)
            return 1, Reference("object", object_index=nested.index)
        if tag == tags["Backref"]:
            index = self.reader.uint30()
            reference = Reference(
                "backref", (index,), index if index < len(self.objects) else None
            )
            self._add_hot(reference)
            return 1, reference
        if tag == tags["ReadOnlyHeapRef"]:
            return 1, Reference("read_only", (self.reader.uint30(), self.reader.uint30()))
        if tag == tags["RootArray"]:
            reference = Reference("root", (self.reader.uint30(),))
            self._add_hot(reference)
            return 1, reference
        for name, kind in (
            ("StartupObjectCache", "startup_cache"),
            ("ReadOnlyObjectCache", "read_only_cache"),
            ("SharedHeapObjectCache", "shared_cache"),
            ("AttachedReference", "attached"),
        ):
            if name in tags and tag == tags[name]:
                return 1, Reference(kind, (self.reader.uint30(),))
        if tags["RootArrayConstants"] <= tag < tags["RootArrayConstants"] + 32:
            return 1, Reference("root", (tag - tags["RootArrayConstants"],))
        if tags["HotObject"] <= tag < tags["HotObject"] + 8:
            index = tag - tags["HotObject"]
            reference = self.hot_objects[index]
            if reference is None:
                raise ParseError(f"empty hot-object slot {index}")
            return 1, reference
        if tags["FixedRawData"] <= tag < tags["FixedRawData"] + 32:
            slots = tag - tags["FixedRawData"] + 1
            return self._raw(obj, slot, slots)
        if tag == tags["VariableRawData"]:
            return self._raw(obj, slot, self.reader.uint30())
        fixed_repeat = tags.get("FixedRepeat", tags.get("FixedRepeatRoot"))
        if fixed_repeat is not None and fixed_repeat <= tag < fixed_repeat + 16:
            count = tag - fixed_repeat + 2
            root = self.reader.byte()
            return count, Reference("repeated_root", (root, count))
        variable_repeat = tags.get("VariableRepeat", tags.get("VariableRepeatRoot"))
        if variable_repeat is not None and tag == variable_repeat:
            count = self.reader.uint30() + 18
            root = self.reader.byte()
            return count, Reference("repeated_root", (root, count))
        if tag == tags["Nop"]:
            return 0, None
        if tag == tags.get("RegisterPendingForwardRef"):
            if obj is None:
                raise ParseError("pending forward reference has no owning object")
            index = len(self.pending_forward_refs)
            self.pending_forward_refs.append((obj, slot * self.tagged_size))
            self.pending_forward_ref_count += 1
            return 1, Reference("pending", (index,))
        if tag == tags.get("ResolvePendingForwardRef"):
            index = self.reader.uint30()
            if obj is None or not 0 <= index < len(self.pending_forward_refs):
                raise ParseError(f"invalid pending forward reference {index}")
            pending = self.pending_forward_refs[index]
            if pending is None:
                raise ParseError(f"pending forward reference {index} already resolved")
            owner, offset = pending
            owner.references[offset] = Reference(
                "forward", (index,), object_index=obj.index
            )
            self.pending_forward_ref_count -= 1
            if self.pending_forward_ref_count:
                self.pending_forward_refs[index] = None
            else:
                self.pending_forward_refs.clear()
            return 0, None
        for name in ("WeakPrefix", "IndirectPointerPrefix", "ProtectedPointerPrefix"):
            if tag == tags.get(name):
                return 0, None
        if tag == tags.get("InitializeSelfIndirectPointer"):
            return 1, Reference("self_indirect")
        if tag == tags.get("AllocateJSDispatchEntry"):
            parameter_count = self.reader.uint30()
            _, code = self._reference(self.reader.byte(), None, 0)
            return 1, Reference(
                "js_dispatch",
                (parameter_count,),
                code.object_index if code else None,
            )
        if tag == tags.get("JSDispatchEntry"):
            return 1, Reference("js_dispatch_backref", (self.reader.uint30(),))
        if tag == tags.get("ClearedWeakReference"):
            return 1, Reference("cleared_weak")
        if tag in {tags.get("ExternalReference"), tags.get("ApiReference")}:
            return 1, Reference("external", (self.reader.uint30(),))
        if tag in {
            tags.get("SandboxedExternalReference"),
            tags.get("SandboxedApiReference"),
        }:
            return 1, Reference("external", (self.reader.uint30(), self.reader.uint30()))
        if tag in {tags.get("RawExternalReference"), tags.get("SandboxedRawExternalReference")}:
            _, raw = self.reader.raw(self.system_pointer_size)
            values = [int.from_bytes(raw, "little")]
            if tag == tags.get("SandboxedRawExternalReference"):
                values.append(self.reader.uint30())
            return 1, Reference("raw_external", tuple(values))
        if tag in {tags.get("OffHeapBackingStore"), tags.get("OffHeapResizableBackingStore")}:
            size = self.reader.uint32()
            if tag == tags.get("OffHeapResizableBackingStore"):
                self.reader.uint32()
            self.reader.raw(size)
            return 0, None
        raise ParseError(
            f"unsupported serializer tag 0x{tag:02x} "
            f"at 0x{self.reader.position - 1:x}"
        )

    def _add_hot(self, reference: Reference) -> None:
        self.hot_objects[self.hot_index] = reference
        self.hot_index = (self.hot_index + 1) & 7

    def _raw(
        self, obj: SerializedObject | None, slot: int, slots: int
    ) -> tuple[int, Reference | None]:
        start, raw = self.reader.raw(slots * self.tagged_size)
        if obj is not None:
            obj.raw_chunks.append(RawChunk(slot * self.tagged_size, start, raw))
        return slots, None
