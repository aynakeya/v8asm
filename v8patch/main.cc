#include <stdio.h>
#include <stdlib.h>
#include <fstream>
#include <string.h>
#include <vector>

#include "include/libplatform/libplatform.h"
#include "include/v8-context.h"
#include "include/v8-initialization.h"
#include "include/v8-isolate.h"
#include "include/v8-local-handle.h"
#include "include/v8-primitive.h"
#include "include/v8-script.h"

#include "src/heap/read-only-spaces.h"
#include "src/objects/managed-inl.h"
#include "src/objects/literal-objects-inl.h"
#include "src/objects/objects-inl.h"
#include "src/flags/flags.h"
#include "src/snapshot/code-serializer.h"
#include "src/snapshot/snapshot.h"
#include "src/utils/ostreams.h"
#include "src/utils/version.h"

#include <csignal>
#include <csetjmp>
#include <set>
#include <unistd.h>


class V8ObjectExplorer {
public:
    explicit V8ObjectExplorer(v8::internal::Isolate* isolate,
                              bool best_effort = false)
        : isolate_(isolate), best_effort_(best_effort) {}

    void Disassemble(v8::internal::Tagged<v8::internal::Object> start_obj) {
        // printf("before traversal\n");
        if (best_effort_) {
          void (*old_handler)(int);
          old_handler = signal(SIGSEGV, segfault_jumper);
          DiscoverReachableObjects(start_obj);
          signal(SIGSEGV, old_handler);
        } else {
          DiscoverReachableObjects(start_obj);
        }
        // printf("traversal done!\n");
        PrintDiscoveredObjects();
    }
private:
    void DiscoverReachableObjects(v8::internal::Tagged<v8::internal::Object> obj) {
        if (v8::internal::IsHeapObject(obj)) {
            auto heap_obj = v8::internal::Cast<v8::internal::HeapObject>(obj);
            if (!best_effort_) {
                Traverse(heap_obj);
                return;
            }
            if (sigsetjmp(jump_buffer_, 1) == 0) {
                currently_discovering_obj_addr_ = heap_obj.ptr();
                Traverse(heap_obj);
                currently_discovering_obj_addr_ = 0;
            } else {
                if (currently_discovering_obj_addr_ != 0) {
                    v8::internal::Address skipped_addr = currently_discovering_obj_addr_;
                    skipped_objects_.insert(skipped_addr);
                }
                currently_discovering_obj_addr_ = 0;
            }
        }
    }

    void Traverse(v8::internal::Tagged<v8::internal::HeapObject> obj) {
        // if compiled by node, sometimes the object will point to an address outside current bytecode scope,
        // which is normally located in snapshot_blob.bin (?).
        // if this happen, we are not able to read the data of the object, neither the type of the object.
        // so so we need to check if the object is readable here, if not, we need to stop here so that program doesnt crash.
        {
          {
            // might works, place here just in case
            v8::internal::Tagged<v8::internal::Map> map_handle = obj->map();
            if (map_handle.ptr() == v8::internal::kNullAddress) {
              // printf("wtf is going on\n");
              return;
            }
          }
          // {
          //   // this will also exclue ReadOnlySpace Data
          //   // not used
          //   v8::internal::Isolate* tmpisolate = nullptr;
          //   if (!v8::internal::GetIsolateFromHeapObject(obj, &tmpisolate)) {
          //     // printf("not able to get isolate\n");
          //     return;
          //   }
          // }
          {
            // works
            // some object might have forwarding address.
            v8::internal::MapWord map_word = obj->map_word(v8::kRelaxedLoad);
            if (map_word.IsForwardingAddress()) {
                // printf("kRelaxedLoad\n");
                return;
            }
            // v8::internal::Tagged<v8::internal::Map> map_handle = map_word.ToMap();
            // v8::internal::InstanceType instance_type = map_handle->instance_type();
            // v8::internal::OFStream os(stdout);
            // os << instance_type;
          }
          // in other case, the container object is readable, but object inside, for example objects inside
          // TrustedFixArray is not readable. in this case, we need handle it inside object-printer.cc
        }

        if (!discovered_objects_.insert({obj.ptr(), obj}).second) {
            return;
        }

        if (v8::internal::IsBytecodeArray(obj)) {
            auto bytecode = v8::internal::Cast<v8::internal::BytecodeArray>(obj);
            auto consts = bytecode->constant_pool();
            DiscoverReachableObjects(consts);
            for (int i = 0; i < consts->length(); i++) {
              DiscoverReachableObjects(consts->get(i));
            }
        } else if (v8::internal::IsSharedFunctionInfo(obj)) {
            auto sfi = v8::internal::Cast<v8::internal::SharedFunctionInfo>(obj);
            if (sfi->HasBytecodeArray()) {
                DiscoverReachableObjects(sfi->GetBytecodeArray(isolate_));
            }
        } else if (v8::internal::IsFixedArray(obj)) {
            auto fixed_array = v8::internal::Cast<v8::internal::FixedArray>(obj);
            for (int i = 0; i < fixed_array->length(); ++i) {
                DiscoverReachableObjects(fixed_array->get(i));
            }
        } else if (v8::internal::IsArrayBoilerplateDescription(obj)) {
            auto abd = v8::internal::Cast<v8::internal::ArrayBoilerplateDescription>(obj);
            DiscoverReachableObjects(abd->constant_elements());
        } else if (v8::internal::IsObjectBoilerplateDescription(obj)) {
            auto obd = v8::internal::Cast<v8::internal::ObjectBoilerplateDescription>(obj);
            for (int i = 0; i < obd->length(); i++) {
                DiscoverReachableObjects(obd->get(i));
            }
        }
    }
    static void segfault_jumper(int signal_number) {
        siglongjmp(V8ObjectExplorer::jump_buffer_, 1);
    }

    void PrintReadOnlyAddressDiagnostics(v8::internal::OFStream& os,
                                         v8::internal::Address tagged_addr) {
        using v8::internal::Address;
        using v8::internal::kHeapObjectTag;
        if (isolate_ == nullptr || tagged_addr == v8::internal::kNullAddress) {
            return;
        }
        Address object_addr = tagged_addr - kHeapObjectTag;
        v8::internal::ReadOnlySpace* read_only_space =
            isolate_->heap()->read_only_space();
        const auto& pages = read_only_space->pages();
        char buf[320];
        for (size_t i = 0; i < pages.size(); ++i) {
            const v8::internal::ReadOnlyPageMetadata* page = pages[i];
            if (!page->Contains(object_addr)) continue;
            size_t object_chunk_offset =
                static_cast<size_t>(object_addr - page->ChunkAddress());
            size_t tagged_chunk_offset =
                static_cast<size_t>(tagged_addr - page->ChunkAddress());
            size_t area_offset =
                static_cast<size_t>(object_addr - page->area_start());
            snprintf(buf, sizeof(buf),
                     " (ro_page=%zu object_chunk_offset=0x%zx "
                     "tagged_chunk_offset=0x%zx area_offset=0x%zx "
                     "page=[0x%llx,0x%llx))",
                     i, object_chunk_offset, tagged_chunk_offset, area_offset,
                     static_cast<unsigned long long>(page->area_start()),
                     static_cast<unsigned long long>(page->area_end()));
            os << buf;
            PrintCurrentReadOnlyObjectBoundary(os, read_only_space, page,
                                               object_addr);
            return;
        }
        snprintf(buf, sizeof(buf),
                 " (not in current read-only space; tagged_low16=0x%04llx "
                 "object_low16=0x%04llx)",
                 static_cast<unsigned long long>(tagged_addr & 0xffff),
                 static_cast<unsigned long long>(object_addr & 0xffff));
        os << buf;
    }

    void PrintCurrentReadOnlyObjectBoundary(
        v8::internal::OFStream& os,
        const v8::internal::ReadOnlySpace* read_only_space,
        const v8::internal::ReadOnlyPageMetadata* page,
        v8::internal::Address object_addr) {
        using v8::internal::Address;
        Address cursor = page->area_start();
        Address end = page->area_end();
        while (cursor < end) {
            if (cursor == read_only_space->top() &&
                cursor != read_only_space->limit()) {
                cursor = read_only_space->limit();
                continue;
            }
            v8::internal::Tagged<v8::internal::HeapObject> current =
                v8::internal::HeapObject::FromAddress(cursor);
            int object_size = current->Size();
            int aligned_size = ALIGN_TO_ALLOCATION_ALIGNMENT(object_size);
            if (aligned_size <= 0) break;
            Address next = cursor + aligned_size;
            if (object_addr >= cursor && object_addr < next) {
                size_t current_offset =
                    static_cast<size_t>(cursor - page->ChunkAddress());
                size_t current_end =
                    static_cast<size_t>(next - page->ChunkAddress());
                size_t delta = static_cast<size_t>(object_addr - cursor);
                char buf[192];
                snprintf(buf, sizeof(buf),
                         " current_ro_object=[0x%zx,0x%zx) "
                         "delta=0x%zx hit=%s",
                         current_offset, current_end, delta,
                         delta == 0 ? "start" : "inside");
                os << buf;
                return;
            }
            cursor = next;
        }
        os << " current_ro_object=n/a";
    }

    void PrintDiscoveredObjects() {
        v8::internal::OFStream os(stdout);

        void (*old_handler)(int) = nullptr;
        if (best_effort_) {
            old_handler = signal(SIGSEGV, segfault_jumper);
        }

        for (const auto& pair : discovered_objects_) {
            auto obj = pair.second;
            if (!best_effort_) {
              currently_printing_obj_addr_ = pair.first;
              v8::internal::Print(obj, os);
              currently_printing_obj_addr_ = 0;
            } else if (sigsetjmp(jump_buffer_, 1) == 0) {
              currently_printing_obj_addr_ = pair.first;
              v8::internal::Print(obj, os);
              currently_printing_obj_addr_ = 0;
            } else {
              fflush(stdout);
              os << std::endl << "!" <<v8::internal::AsHex::Address(currently_printing_obj_addr_) << ": segmentfault, disassemble stop";
              PrintReadOnlyAddressDiagnostics(
                  os, static_cast<v8::internal::Address>(currently_printing_obj_addr_));
              os << std::endl;
              currently_printing_obj_addr_ = 0;
            }
            fflush(stdout);
        }
        if (best_effort_) {
            for (const auto& addr : skipped_objects_) {
                os << std::endl << "!" << v8::internal::AsHex::Address(addr)
                   << ": segmentfault while discovering object, skipped";
                PrintReadOnlyAddressDiagnostics(os, addr);
                os << std::endl;
            }
            signal(SIGSEGV, old_handler);
        }
        fflush(stdout);
    }
private:
    static sigjmp_buf jump_buffer_;
    static volatile v8::internal::Address currently_printing_obj_addr_;
    static volatile v8::internal::Address currently_discovering_obj_addr_;
    v8::internal::Isolate* isolate_;
    bool best_effort_;
    std::map<v8::internal::Address, v8::internal::Tagged<v8::internal::HeapObject>> discovered_objects_;
    std::set<v8::internal::Address> skipped_objects_;
};
volatile v8::internal::Address V8ObjectExplorer::currently_printing_obj_addr_ = 0;
volatile v8::internal::Address V8ObjectExplorer::currently_discovering_obj_addr_ = 0;
sigjmp_buf V8ObjectExplorer::jump_buffer_;


// todo: do not disassemble duplicated memory address
static void disassemble(v8::internal::Isolate* isolate,
                                    v8::internal::Tagged<v8::internal::Object> obj) {

    v8::internal::OFStream os(stdout);
    // os << "->" << std::endl;
    v8::internal::Print(obj,os);

    if (v8::internal::IsBytecodeArray(obj)) {
      auto bytecode = v8::internal::Cast<v8::internal::BytecodeArray>(obj);
      // v8::internal::PrintF("0x%012llx: [BytecodeArray]\n", static_cast<unsigned long long>(bytecode.ptr()));
      // bytecode->Disassemble(os);
      auto consts = bytecode->constant_pool();
      for (int i = 0; i < consts->length(); i++) {
        auto inner = consts->get(i);
        if (v8::internal::IsHeapObject(inner)) {
          auto shared = v8::internal::Cast<v8::internal::HeapObject>(inner);
          disassemble(isolate,shared);
        }else {
          // smi
          // v8::internal::Print(inner,os);
        }
      }
    }

    if (v8::internal::IsSharedFunctionInfo(obj)) {
        auto sfi = v8::internal::Cast<v8::internal::SharedFunctionInfo>(obj);
        if (sfi->HasBytecodeArray()) {
            disassemble(isolate, sfi->GetBytecodeArray(isolate));
        }
    }

    if (v8::internal::IsFixedArray(obj)) {
        auto fixed_array = v8::internal::Cast<v8::internal::FixedArray>(obj);
        for (int i = 0; i < fixed_array->length(); ++i) {
            auto objn = fixed_array->get(i);
            if (v8::internal::IsHeapObject(objn)) {
              disassemble(isolate,objn);
            }else {
            // smi
            }
        }
    }

    if (v8::internal::IsArrayBoilerplateDescription(obj)) {
      auto abd = v8::internal::Cast<v8::internal::ArrayBoilerplateDescription>(obj);
      disassemble(isolate,abd->constant_elements());
    }

    if (v8::internal::IsObjectBoilerplateDescription(obj)) {
      auto obd = v8::internal::Cast<v8::internal::ObjectBoilerplateDescription>(obj);
      for (int i = 0; i < obd->capacity(); i++) {
        auto inner = obd->get(i);
        if (v8::internal::IsHeapObject(inner)) {
          auto shared = v8::internal::Cast<v8::internal::HeapObject>(inner);
          disassemble(isolate,shared);
        }else {
          // smi
          // v8::internal::Print(inner,os);
        }
    }}
    // os << "<-" << std::endl;
    fflush(stdout);
    return;
}

bool read_file_to_buffer(const char* file, std::vector<uint8_t>& buffer) {
  std::ifstream infile(file, std::ifstream::binary);
  if (!infile) return false;
  infile.seekg(0, infile.end);
  std::streamoff length = infile.tellg();
  infile.seekg(0, infile.beg);
  if (length <= 0) {
    buffer.clear();
    return true;
  }
  buffer.resize(static_cast<size_t>(length));
  infile.read(reinterpret_cast<char*>(buffer.data()), length);
  return true;
}

bool write_file_to_buffer(const char* file, const uint8_t* data, size_t len) {
  std::ofstream out(file, std::ios::binary);
  if (!out) return false;
  out.write(reinterpret_cast<const char*>(data), len);
  out.close();
  return true;
}

uint32_t read_u32_le(const std::vector<uint8_t>& data, uint32_t offset) {
  if (data.size() < offset + sizeof(uint32_t)) return 0;
  uint32_t value;
  memcpy(&value, data.data() + offset, sizeof(value));
  return value;
}

struct CacheHeader {
  uint32_t magic;
  uint32_t version_hash;
  uint32_t source_hash;
  uint32_t flags_hash;
  uint32_t ro_snapshot_checksum;
  uint32_t payload_length;
  uint32_t checksum;
};

CacheHeader parse_cache_header(const std::vector<uint8_t>& data) {
  return CacheHeader{
      read_u32_le(data, v8::internal::SerializedData::kMagicNumberOffset),
      read_u32_le(data, v8::internal::SerializedCodeData::kVersionHashOffset),
      read_u32_le(data, v8::internal::SerializedCodeData::kSourceHashOffset),
      read_u32_le(data, v8::internal::SerializedCodeData::kFlagHashOffset),
      read_u32_le(data, v8::internal::SerializedCodeData::kReadOnlySnapshotChecksumOffset),
      read_u32_le(data, v8::internal::SerializedCodeData::kPayloadLengthOffset),
      read_u32_le(data, v8::internal::SerializedCodeData::kChecksumOffset),
  };
}

struct CacheExpectations {
  uint32_t magic;
  uint32_t version_hash;
  uint32_t flags_hash;
  uint32_t ro_snapshot_checksum;
};

CacheExpectations current_cache_expectations(v8::internal::Isolate* isolate) {
  return CacheExpectations{
      v8::internal::SerializedData::kMagicNumber,
      v8::internal::Version::Hash(),
      v8::internal::FlagList::Hash(),
      v8::internal::Snapshot::ExtractReadOnlySnapshotChecksum(isolate->snapshot_blob()),
  };
}

size_t cache_header_payload_max_size(size_t data_size) {
  if (data_size < v8::internal::SerializedCodeData::kHeaderSize) return 0;
  return data_size - v8::internal::SerializedCodeData::kHeaderSize;
}

bool cache_header_payload_is_plausible(const CacheHeader& header,
                                       size_t data_size) {
  if (data_size < v8::internal::SerializedCodeData::kHeaderSize) return false;
  size_t max_payload = cache_header_payload_max_size(data_size);
  if (header.payload_length > max_payload) return false;
  if (max_payload > 0 && header.payload_length == 0) return false;
  return true;
}

bool cache_header_matches_current_v8(const CacheHeader& header,
                                     const CacheExpectations& expected,
                                     size_t data_size) {
  if (header.magic != expected.magic) return false;
  if (header.version_hash != expected.version_hash) return false;
  if (header.flags_hash != expected.flags_hash) return false;
  if (header.ro_snapshot_checksum != expected.ro_snapshot_checksum) return false;
  if (!cache_header_payload_is_plausible(header, data_size)) return false;
  return true;
}

void print_cache_header_report(FILE* out, const CacheHeader& header,
                               const CacheExpectations& expected,
                               size_t data_size) {
  fprintf(out, "Cached data header:\n");
  fprintf(out, "  magic: 0x%08x (expected 0x%08x)%s\n",
          header.magic, expected.magic, header.magic == expected.magic ? "" : " mismatch");
  fprintf(out, "  version_hash: 0x%08x (expected 0x%08x)%s\n",
          header.version_hash, expected.version_hash,
          header.version_hash == expected.version_hash ? "" : " mismatch");
  fprintf(out, "  source_hash: 0x%08x (informational)\n", header.source_hash);
  fprintf(out, "  flags_hash: 0x%08x (expected 0x%08x)%s\n",
          header.flags_hash, expected.flags_hash,
          header.flags_hash == expected.flags_hash ? "" : " mismatch");
  fprintf(out, "  read_only_snapshot_checksum: 0x%08x (expected 0x%08x)%s\n",
          header.ro_snapshot_checksum, expected.ro_snapshot_checksum,
          header.ro_snapshot_checksum == expected.ro_snapshot_checksum ? "" : " mismatch");
  fprintf(out, "  payload_length: %u (max %zu)%s\n",
          header.payload_length,
          cache_header_payload_max_size(data_size),
          cache_header_payload_is_plausible(header, data_size) ? "" : " mismatch");
  fprintf(out, "  checksum: 0x%08x\n", header.checksum);
}

struct VersionTuple {
  int major;
  int minor;
  int build;
  int patch;
};

VersionTuple bruteforce_v8_version(uint32_t target_hash,
                                   int max_major = 20,
                                   int max_minor = 20,
                                   int max_build = 500,
                                   int max_patch = 200) {
  for (int major = 0; major < max_major; ++major) {
    for (int minor = 0; minor < max_minor; ++minor) {
      for (int build = 0; build < max_build; ++build) {
        for (int patch = 0; patch < max_patch; ++patch) {
          uint32_t h = static_cast<uint32_t>(v8::base::hash_combine(major, minor,  build, patch));
          if (h == target_hash) {
            return VersionTuple{major, minor, build, patch};
          }
        }
      }
    }
  }
  return VersionTuple{-1, -1, -1, -1};
}

struct KnownVersionHash {
  uint32_t hash;
  VersionTuple version;
};

bool lookup_known_v8_version_hash(uint32_t target_hash,
                                  VersionTuple* cached_version) {
  static const KnownVersionHash known_versions[] = {
      {0x3569a082, VersionTuple{10, 2, 154, 26}},
      {0x00e4c20b, VersionTuple{11, 3, 244, 8}},
      {0x79dafe74, VersionTuple{12, 4, 254, 21}},
      {0x2135fe8d, VersionTuple{13, 4, 114, 21}},
      {0x2b2c7714, VersionTuple{13, 6, 233, 10}},
  };

  for (const KnownVersionHash& known_version : known_versions) {
    if (known_version.hash == target_hash) {
      if (cached_version != nullptr) {
        *cached_version = known_version.version;
      }
      return true;
    }
  }
  return false;
}

bool cache_header_is_known_cross_major(const CacheHeader& header,
                                       VersionTuple* cached_version) {
  if (header.version_hash == v8::internal::Version::Hash()) return false;
  VersionTuple known{-1, -1, -1, -1};
  if (lookup_known_v8_version_hash(header.version_hash, &known)) {
    if (cached_version != nullptr) *cached_version = known;
    return known.major != v8::internal::Version::GetMajor();
  }
  VersionTuple found = bruteforce_v8_version(header.version_hash, 20, 20, 500, 200);
  if (cached_version != nullptr) *cached_version = found;
  return found.major >= 0 && found.major != v8::internal::Version::GetMajor();
}

int do_checkversion(const char* filename, v8::Isolate* isolate) {
  std::vector<uint8_t> data;
  if (!read_file_to_buffer(filename, data)) {
    fprintf(stderr, "Error reading file: %s\n", filename);
    return 1;
  }

  const uint32_t offset = v8::internal::SerializedCodeData::kVersionHashOffset;
  if (data.size() < offset + sizeof(uint32_t)) {
    fprintf(stderr, "File too small to contain version hash at offset %u\n", offset);
    return 1;
  }

  uint8_t * version_addr = (uint8_t *) data.data() + offset;

  // read as little-endian uint32_t
  uint32_t version_hash = *(uint32_t *) version_addr;
  printf("Version hash: hex = %x%x%x%x , uint32 = 0x%08x (%u)\n", version_addr[0], version_addr[1], version_addr[2], version_addr[3], version_hash, version_hash);
  auto i_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);
  CacheHeader header = parse_cache_header(data);
  CacheExpectations expected = current_cache_expectations(i_isolate);
  print_cache_header_report(stdout, header, expected, data.size());
  VersionTuple known{-1, -1, -1, -1};
  if (lookup_known_v8_version_hash(version_hash, &known)) {
    printf("Known matching version: %d.%d.%d.%d\n",
           known.major, known.minor, known.build, known.patch);
    return 0;
  }

  printf("Starting brute-force search (0-20.0-20.0-500.0-200)...\n");
  VersionTuple found = bruteforce_v8_version(version_hash, 20, 20, 500, 200);
  if (found.major >= 0) {
    printf("Found matching version: %d.%d.%d.%d\n", found.major, found.minor, found.build, found.patch);
    return 0;
  } else {
    printf("No matching version found in the searched ranges.\n");
    return 0;
  }
}

int do_asm(int argc, char* argv[], v8::Isolate* isolate) {
  if (argc < 3) {
    fprintf(stderr, "Usage: %s asm input.js [-o out.jsc]\n", argv[0]);
    return 1;
  }
  const char* input_js = argv[2];
  std::string out_filename;
  // default out: input.js -> input.jsc
  {
    std::string in = input_js;
    size_t pos = in.rfind('.');
    if (pos == std::string::npos) out_filename = in + ".jsc";
    else out_filename = in.substr(0, pos) + ".jsc";
  }
  // parse optional -o
  for (int i = 3; i < argc - 1; ++i) {
    if (strcmp(argv[i], "-o") == 0) {
      out_filename = argv[i+1];
    }
  }

  std::string source_code;
  {
    std::ifstream infile(input_js);
    if (!infile) {
      fprintf(stderr, "Error opening input js: %s\n", input_js);
      return 1;
    }
    std::string tmp((std::istreambuf_iterator<char>(infile)),
                    std::istreambuf_iterator<char>());
    source_code.swap(tmp);
  }

  // Compile the source in current isolate and create code cache
  v8::Isolate::Scope isolate_scope(isolate);
  v8::HandleScope handle_scope(isolate);
  v8::Local<v8::Context> context = v8::Context::New(isolate);
  v8::Context::Scope context_scope(context);

  v8::Local<v8::String> src = v8::String::NewFromUtf8(isolate, source_code.c_str(),
                                          v8::NewStringType::kNormal,
                                          static_cast<int>(source_code.size()))
                         .ToLocalChecked();

  v8::ScriptOrigin origin(v8::String::NewFromUtf8Literal(isolate, "v8utils-asm"));
  v8::Local<v8::Script> script;
  if (!v8::Script::Compile(context, src).ToLocal(&script)) {
    fprintf(stderr, "Failed to compile source\n");
    return 1;
  }

  v8::Local<v8::UnboundScript> unbound = script->GetUnboundScript();
  std::unique_ptr<v8::ScriptCompiler::CachedData> cache(v8::ScriptCompiler::CreateCodeCache(unbound));
  if (!cache) {
    fprintf(stderr, "Failed to create code cache\n");
    return 1;
  }

  if (!write_file_to_buffer(out_filename.c_str(), cache->data, static_cast<size_t>(cache->length))) {
    fprintf(stderr, "Failed to write out file: %s\n", out_filename.c_str());
    return 1;
  }

  printf("Wrote %zu bytes to %s\n", static_cast<size_t>(cache->length), out_filename.c_str());
  return 0;
}


int do_disasm(const char* filename, v8::Isolate* isolate, bool force_incompatible) {
  std::vector<uint8_t> data;
  if (!read_file_to_buffer(filename, data)) {
    fprintf(stderr, "Error reading file: %s\n", filename);
    return 1;
  }
  v8::Isolate::Scope isolate_scope(isolate);
  v8::HandleScope handle_scope(isolate);
  auto i_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);

  if (data.size() < v8::internal::SerializedCodeData::kHeaderSize) {
    fprintf(stderr, "File too small to contain a V8 cached-data header.\n");
    return 1;
  }
  CacheHeader header = parse_cache_header(data);
  CacheExpectations expected = current_cache_expectations(i_isolate);
  bool plausible_payload = cache_header_payload_is_plausible(header, data.size());
  VersionTuple cached_version{-1, -1, -1, -1};
  bool known_cross_major =
      cache_header_is_known_cross_major(header, &cached_version);
  bool compatible =
      cache_header_matches_current_v8(header, expected, data.size());
  if (!compatible) {
    print_cache_header_report(stderr, header, expected, data.size());
    if (!force_incompatible) {
      fprintf(stderr,
              "Refusing to deserialize incompatible cached data. "
              "Use --force-incompatible for best-effort recovery.\n");
      return 1;
    }
    if (!plausible_payload) {
      fprintf(stderr,
              "Refusing to force cached data because this V8 build parses an "
              "impossible payload length. The cached-data header layout is "
              "probably from a different major V8; use a matching v8asm "
              "patch/build for direct recovery.\n");
      return 1;
    }
    if (known_cross_major) {
      fprintf(stderr,
              "Warning: forcing cached data from V8 %d.%d.%d.%d with this "
              "V8 %d.x build. Cross-major bytecode layouts are crash-prone; "
              "prefer the matching major v8asm patch/build when possible.\n",
              cached_version.major, cached_version.minor, cached_version.build,
              cached_version.patch, v8::internal::Version::GetMajor());
    }
    fprintf(stderr,
            "Forcing incompatible cached data; output may be partial.\n");
  }

  v8::internal::AlignedCachedData cached_data(data.data(), static_cast<int>(data.size()));
  auto source = i_isolate->factory()->NewStringFromAsciiChecked("source");
  v8::internal::ScriptDetails script_details(source);
  v8::internal::MaybeDirectHandle<v8::internal::SharedFunctionInfo> maybe_sfi =
      v8::internal::CodeSerializer::Deserialize(i_isolate, &cached_data, source, script_details);

  v8::internal::DirectHandle<v8::internal::SharedFunctionInfo> sfi_handle;
  if (!maybe_sfi.ToHandle(&sfi_handle)) {
    fprintf(stderr, "Failed to deserialize shared function info (maybe incompatible version).\n");
    return 1;
  }

  if (!sfi_handle->HasBytecodeArray()) {
    fprintf(stderr, "Deserialized SFI has no bytecode array.\n");
    return 1;
  }

  auto bytecode = sfi_handle->GetBytecodeArray(i_isolate);
  // disassemble(i_isolate, bytecode);
  V8ObjectExplorer explorer(i_isolate, force_incompatible && !compatible);
  explorer.Disassemble(bytecode);
  return 0;
}


void print_compiled_args() {
  #ifdef DEBUG
  printf("is_debug=true\n");
  #else
  printf("is_debug=false\n");
  #endif
  #ifdef OBJECT_PRINT
  printf("v8_enable_object_print=true\n");
  #else
  printf("v8_enable_object_print=false\n");
  #endif
  #ifdef ENABLE_DISASSEMBLER
  printf("v8_enable_disassembler=true\n");
  #else
  printf("v8_enable_disassembler=false\n");
  #endif
  #ifdef V8_COMPRESS_POINTERS
  printf("v8_enable_pointer_compression=true\n");
  #else
  printf("v8_enable_pointer_compression=false\n");
  #endif
}

struct StartupOptions {
  const char* snapshot_blob = nullptr;
  bool valid = true;
};

void print_usage(const char* program) {
  fprintf(stderr,
          "Usage: %s [--snapshot_blob file] "
          "<asm|disasm|checkversion|version|build-args> ...\n",
          program);
}

StartupOptions parse_startup_options(int argc, char* argv[],
                                     std::vector<char*>* command_argv) {
  StartupOptions options;
  command_argv->clear();
  command_argv->push_back(argv[0]);
  for (int i = 1; i < argc; ++i) {
    const char* arg = argv[i];
    if (strcmp(arg, "--snapshot_blob") == 0) {
      if (i + 1 >= argc) {
        fprintf(stderr, "--snapshot_blob requires a file path\n");
        options.valid = false;
        return options;
      }
      options.snapshot_blob = argv[i + 1];
      ++i;
      continue;
    }
    const char* snapshot_prefix = "--snapshot_blob=";
    size_t snapshot_prefix_len = strlen(snapshot_prefix);
    if (strncmp(arg, snapshot_prefix, snapshot_prefix_len) == 0) {
      options.snapshot_blob = arg + snapshot_prefix_len;
      continue;
    }
    command_argv->push_back(argv[i]);
  }
  if (command_argv->size() < 2) {
    options.valid = false;
  }
  return options;
}

bool command_requests_force_incompatible(int argc, char* argv[]) {
  for (int i = 1; i < argc; ++i) {
    if (strcmp(argv[i], "--force-incompatible") == 0 ||
        strcmp(argv[i], "--best-effort") == 0) {
      return true;
    }
  }
  return false;
}

constexpr size_t kV8AsmSnapshotVersionOffset = 16;
constexpr size_t kV8AsmSnapshotVersionLength = 64;

bool read_snapshot_version(const char* path,
                           char version[kV8AsmSnapshotVersionLength + 1]) {
  memset(version, 0, kV8AsmSnapshotVersionLength + 1);
  FILE* file = fopen(path, "rb");
  if (file == nullptr) {
    fprintf(stderr, "Failed to open snapshot blob '%s': %s\n", path,
            strerror(errno));
    return false;
  }
  bool ok = false;
  if (fseek(file, static_cast<long>(kV8AsmSnapshotVersionOffset), SEEK_SET) == 0) {
    ok = fread(version, 1, kV8AsmSnapshotVersionLength, file) ==
         kV8AsmSnapshotVersionLength;
  }
  if (!ok) {
    fprintf(stderr, "Failed to read snapshot version from '%s'\n", path);
  }
  fclose(file);
  return ok;
}

bool snapshot_matches_binary_base(const char* snapshot_version,
                                  const char* binary_version) {
  size_t binary_len = strlen(binary_version);
  if (strncmp(snapshot_version, binary_version, binary_len) != 0) {
    return false;
  }
  char next = snapshot_version[binary_len];
  return next == '\0' || next == '-' || next == '+';
}

bool allow_cross_version_snapshot_mismatch() {
  const char* value = getenv("V8ASM_ALLOW_CROSS_VERSION_SNAPSHOT_MISMATCH");
  return value != nullptr && strcmp(value, "0") != 0;
}

bool validate_snapshot_blob_version(const char* snapshot_blob,
                                    bool* version_mismatch) {
  *version_mismatch = false;
  char snapshot_version[kV8AsmSnapshotVersionLength + 1];
  if (!read_snapshot_version(snapshot_blob, snapshot_version)) {
    return false;
  }

  const char* binary_version = v8::V8::GetVersion();
  if (strcmp(snapshot_version, binary_version) == 0) {
    return true;
  }

  *version_mismatch = true;
  if (snapshot_matches_binary_base(snapshot_version, binary_version)) {
    fprintf(stderr,
            "Warning: forcing snapshot blob version tag mismatch.\n"
            "#   V8 binary version: %s\n"
            "#    Snapshot version: %s\n",
            binary_version, snapshot_version);
    return true;
  }

  fprintf(stderr,
          "Warning: forcing cross-version snapshot blob load.\n"
          "#   V8 binary version: %s\n"
          "#    Snapshot version: %s\n",
          binary_version, snapshot_version);
  return true;
}

int main(int argc, char* argv[]) {
  if (argc < 2) {
    print_usage(argv[0]);
    return 1;
  }

  std::vector<char*> command_argv;
  StartupOptions startup_options =
      parse_startup_options(argc, argv, &command_argv);
  if (!startup_options.valid) {
    print_usage(argv[0]);
    return 1;
  }

  int command_argc = static_cast<int>(command_argv.size());
  const char* cmd = command_argv[1];
  bool force_incompatible =
      command_requests_force_incompatible(command_argc, command_argv.data());

  v8::V8::SetFlagsFromString("--no-lazy --no-flush-bytecode");
  v8::V8::InitializeICUDefaultLocation(argv[0]);
  if (startup_options.snapshot_blob != nullptr) {
    bool snapshot_version_mismatch = false;
    if (!validate_snapshot_blob_version(startup_options.snapshot_blob,
                                        &snapshot_version_mismatch)) {
      return 1;
    }
    if (snapshot_version_mismatch) {
      setenv("V8ASM_ALLOW_SNAPSHOT_VERSION_MISMATCH", "1", 0);
    }
    if (force_incompatible) {
      setenv("V8ASM_ALLOW_SNAPSHOT_EXTERNAL_REFERENCE_MISMATCH", "1", 0);
    }
    v8::V8::InitializeExternalStartupDataFromFile(
        startup_options.snapshot_blob);
  } else {
    v8::V8::InitializeExternalStartupData(argv[0]);
  }
  std::unique_ptr<v8::Platform> platform = v8::platform::NewDefaultPlatform();
  v8::V8::InitializePlatform(platform.get());
  v8::V8::Initialize();

  v8::Isolate::CreateParams create_params;
  create_params.array_buffer_allocator = v8::ArrayBuffer::Allocator::NewDefaultAllocator();
  v8::Isolate* isolate = v8::Isolate::New(create_params);

  int ret = 0;
  if (strcmp(cmd, "version") == 0) {
    printf("%s\n", v8::V8::GetVersion());
    ret = 0;
    goto finish;
  }
  if (strcmp(cmd, "build-args") == 0) {
    print_compiled_args();
    goto finish;
  }
  if (strcmp(cmd, "checkversion") == 0) {
    if (command_argc < 3) {
      fprintf(stderr, "Usage: %s checkversion file.jsc\n", argv[0]);
      ret = 1;
      goto finish;
    }
    ret = do_checkversion(command_argv[2], isolate);
    goto finish;
  }
  if (strcmp(cmd, "asm") == 0) {
    ret = do_asm(command_argc, command_argv.data(), isolate);
    goto finish;
  }
  if (strcmp(cmd, "disasm") == 0) {
    if (command_argc < 3) {
      fprintf(stderr, "Usage: %s disasm file.jsc [--force-incompatible]\n", argv[0]);
      ret = 1;
      goto finish;
    }
    force_incompatible = false;
    for (int i = 3; i < command_argc; ++i) {
      if (strcmp(command_argv[i], "--force-incompatible") == 0 ||
          strcmp(command_argv[i], "--best-effort") == 0) {
        force_incompatible = true;
      } else {
        fprintf(stderr, "Unknown disasm option: %s\n", command_argv[i]);
        fprintf(stderr, "Usage: %s disasm file.jsc [--force-incompatible]\n", argv[0]);
        ret = 1;
        goto finish;
      }
    }
    ret = do_disasm(command_argv[2], isolate, force_incompatible);
    goto finish;
  }
  fprintf(stderr, "Unknown command: %s\n", cmd);
  print_usage(argv[0]);
  ret = 1;
finish:
  isolate->Dispose();
  v8::V8::Dispose();
  v8::V8::DisposePlatform();
  delete create_params.array_buffer_allocator;
  return ret;
}
