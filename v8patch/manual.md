# manually patch files


## BUILD.gn

```text
v8_executable("v8asm") {
  sources = [ "src/disassembler/main.cc" ]

  # This config allows us to include V8's internal headers,
  # which is necessary for accessing i::CodeSerializer, i::Isolate, etc.
  configs = [ ":internal_config_base" ]

  # Define the direct dependencies for our tool.
  # :v8      - The main V8 public API library.
  # :v8_libbase and :v8_libplatform are essential support libraries.
  deps = [
    ":v8",
    ":v8_base",
    ":v8_snapshot",
    ":v8_libbase",
    ":v8_libplatform",
    "//build/win:default_exe_manifest", # Required for Windows builds.
  ]
}
```


## src/disassembler/main.cc

check out [main.cc](./main.cc)

## src/diagnostics/objects-printer.cc

add header

```cpp
#include <csignal>
#include <csetjmp>
#include <unistd.h>
```


**`PrintHeapObjectHeaderWithoutMap`**: 

replace `reinterpret_cast<void*>` with `AsHex::Address`

```cpp
void PrintHeapObjectHeaderWithoutMap(Tagged<HeapObject> object,
                                     std::ostream& os, const char* id) {
  PtrComprCageBase cage_base = GetPtrComprCageBase();
  os << AsHex::Address(object.ptr()) << ": [";
```


**`HeapObject::HeapObjectShortPrint`**: 

add try catch

```cpp
static sigjmp_buf g_jump_buffer;
void segfault_jumper(int signal_number) {
    siglongjmp(g_jump_buffer, 1);
}

void HeapObject::HeapObjectShortPrint(std::ostream& os) {
  PtrComprCageBase cage_base = GetPtrComprCageBase();
  os << AsHex::Address(this->ptr()) << " ";

  void (*old_handler)(int);
  old_handler = signal(SIGSEGV, segfault_jumper);
  if (sigsetjmp(g_jump_buffer, 1) != 0) {
    os << "<undefined: segmentfault, might outside scope>";
    signal(SIGSEGV, old_handler);
    return
  }

```

reset signal handler in every return 

```cpp
signal(SIGSEGV, old_handler);
```

## src/objects/bytecode-array.cc

**`BytecodeArray::Disassemble`**

move `Print(handle->constant_pool(), os);` to the end of the function


```cpp
  os << "Constant pool (size = " << handle->constant_pool()->length() << ")\n";

  os << "Handler Table (size = " << handle->handler_table()->length() << ")\n";
#ifdef ENABLE_DISASSEMBLER
  if (handle->handler_table()->length() > 0) {
    HandlerTable table(*handle);
    table.HandlerTableRangePrint(os);
  }
#endif

  Tagged<TrustedByteArray> source_position_table =
      handle->SourcePositionTable();
  os << "Source Position Table (size = " << source_position_table->length()
     << ")\n";
#ifdef OBJECT_PRINT
  if (source_position_table->length() > 0) {
    os << Brief(source_position_table) << std::endl;
  }
#endif
#ifdef OBJECT_PRINT
  if (handle->constant_pool()->length() > 0) {
    Print(handle->constant_pool(), os);
  }
#endif
}
```


## src/snapshot/code-serializer.cc

**`SerializedCodeData::SanityCheck`**:

disable sanity check

```cpp

SerializedCodeSanityCheckResult SerializedCodeData::SanityCheck(
    uint32_t expected_ro_snapshot_checksum,
    uint32_t expected_source_hash) const {
  return SerializedCodeSanityCheckResult::kSuccess; 
  // SerializedCodeSanityCheckResult result =
  //     SanityCheckWithoutSource(expected_ro_snapshot_checksum);
  // if (result != SerializedCodeSanityCheckResult::kSuccess) return result;
  // return SanityCheckJustSource(expected_source_hash);
}
```


**`SerializedCodeData::SanityCheckWithoutSource`**:

disable sanity check

```cpp
SerializedCodeSanityCheckResult SerializedCodeData::SanityCheckWithoutSource(
    uint32_t expected_ro_snapshot_checksum) const {
  // if (size_ < kHeaderSize) {
  //   return SerializedCodeSanityCheckResult::kInvalidHeader;
  // }
  // uint32_t magic_number = GetMagicNumber();
  // if (magic_number != kMagicNumber) {
  //   return SerializedCodeSanityCheckResult::kMagicNumberMismatch;
  // }
  // uint32_t version_hash = GetHeaderValue(kVersionHashOffset);
  // if (version_hash != Version::Hash()) {
  //   return SerializedCodeSanityCheckResult::kVersionMismatch;
  // }
  // uint32_t flags_hash = GetHeaderValue(kFlagHashOffset);
  // if (flags_hash != FlagList::Hash()) {
  //   return SerializedCodeSanityCheckResult::kFlagsMismatch;
  // }
  // uint32_t ro_snapshot_checksum =
  //     GetHeaderValue(kReadOnlySnapshotChecksumOffset);
  // if (ro_snapshot_checksum != expected_ro_snapshot_checksum) {
  //   return SerializedCodeSanityCheckResult::kReadOnlySnapshotChecksumMismatch;
  // }
  // uint32_t payload_length = GetHeaderValue(kPayloadLengthOffset);
  // uint32_t max_payload_length = size_ - kHeaderSize;
  // if (payload_length > max_payload_length) {
  //   return SerializedCodeSanityCheckResult::kLengthMismatch;
  // }
  // if (v8_flags.verify_snapshot_checksum) {
  //   uint32_t checksum = GetHeaderValue(kChecksumOffset);
  //   if (Checksum(ChecksummedContent()) != checksum) {
  //     return SerializedCodeSanityCheckResult::kChecksumMismatch;
  //   }
  // }
  return SerializedCodeSanityCheckResult::kSuccess;
}
```


## src/snapshot/deserializer.cc


**`Deserializer<IsolateT>::Deserializer`**

remove magic number checker

```cpp

  back_refs_.reserve(2048);
  js_dispatch_entries_.reserve(512);

#ifdef DEBUG
  num_api_references_ = GetNumApiReferences(isolate);
#endif  // DEBUG
  // CHECK_EQ(magic_number_, SerializedData::kMagicNumber);
}
```