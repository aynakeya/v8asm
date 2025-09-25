#include <stdio.h>
#include <stdlib.h>
#include <fstream> 
#include <string.h>

#include "include/libplatform/libplatform.h"
#include "include/v8-context.h"
#include "include/v8-initialization.h"
#include "include/v8-isolate.h"
#include "include/v8-local-handle.h"
#include "include/v8-primitive.h"
#include "include/v8-script.h"

#include "src/objects/managed-inl.h"
#include "src/objects/literal-objects-inl.h"
#include "src/snapshot/code-serializer.h"
#include "src/utils/ostreams.h"

#include <csignal>
#include <csetjmp>
#include <unistd.h>


class V8ObjectExplorer {
public:
    explicit V8ObjectExplorer(v8::internal::Isolate* isolate) : isolate_(isolate) {}

    void Disassemble(v8::internal::Tagged<v8::internal::Object> start_obj) {
        // printf("before traversal\n");
        DiscoverReachableObjects(start_obj);
        // printf("traversal done!\n");
        PrintDiscoveredObjects();
    }
private:
    void DiscoverReachableObjects(v8::internal::Tagged<v8::internal::Object> obj) {
        if (v8::internal::IsHeapObject(obj)) {
            Traverse(v8::internal::Cast<v8::internal::HeapObject>(obj));
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

    void PrintDiscoveredObjects() {
        v8::internal::OFStream os(stdout);

        void (*old_handler)(int);
        
        old_handler = signal(SIGSEGV, segfault_jumper);

        for (const auto& pair : discovered_objects_) {
            auto obj = pair.second;
            if (sigsetjmp(jump_buffer_, 1) == 0) {
              currently_printing_obj_addr_ = pair.first;
              v8::internal::Print(obj, os);
              currently_printing_obj_addr_ = 0;
            } else {
              fflush(stdout);
              os << std::endl << "!" <<v8::internal::AsHex::Address(currently_printing_obj_addr_) << ": segmentfault, disassemble stop" << std::endl;
              currently_printing_obj_addr_ = 0;
            }
            fflush(stdout);
        }
        signal(SIGSEGV, old_handler);
        fflush(stdout);
    }
private:
    static sigjmp_buf jump_buffer_;
    static volatile v8::internal::Address currently_printing_obj_addr_;
    v8::internal::Isolate* isolate_;
    std::map<v8::internal::Address, v8::internal::Tagged<v8::internal::HeapObject>> discovered_objects_;
};
volatile v8::internal::Address V8ObjectExplorer::currently_printing_obj_addr_ = 0;
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

int do_checkversion(const char* filename) {
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


int do_disasm(const char* filename, v8::Isolate* isolate) {
  std::vector<uint8_t> data;
  if (!read_file_to_buffer(filename, data)) {
    fprintf(stderr, "Error reading file: %s\n", filename);
    return 1;
  }
  v8::Isolate::Scope isolate_scope(isolate);
  v8::HandleScope handle_scope(isolate);
  auto i_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);

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
  V8ObjectExplorer explorer(i_isolate);
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

int main(int argc, char* argv[]) {
  if (argc < 2) {
    fprintf(stderr, "Usage: %s <asm|disasm|checkversion|version|build-args> ...\n", argv[0]);
    return 1;
  }

  const char* cmd = argv[1];

  v8::V8::SetFlagsFromString("--no-lazy --no-flush-bytecode");
  v8::V8::InitializeICUDefaultLocation(argv[0]);
  v8::V8::InitializeExternalStartupData(argv[0]);
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
    if (argc < 3) {
      fprintf(stderr, "Usage: %s checkversion file.jsc\n", argv[0]);
      ret = 1;
      goto finish;
    }
    ret = do_checkversion(argv[2]);
    goto finish;
  } 
  if (strcmp(cmd, "asm") == 0) {
    ret = do_asm(argc, argv, isolate);
    goto finish;
  }
  if (strcmp(cmd, "disasm") == 0) {
    if (argc < 3) {
      fprintf(stderr, "Usage: %s disasm file.jsc\n", argv[0]);
      ret = 1;
      goto finish;
    }
    ret = do_disasm(argv[2], isolate);
    goto finish;
  }
  fprintf(stderr, "Unknown command: %s\n", cmd);
  fprintf(stderr, "Usage: %s <asm|disasm|checkversion> ...\n", argv[0]);
  ret = 1;
finish:
  isolate->Dispose();
  v8::V8::Dispose();
  v8::V8::DisposePlatform();
  delete create_params.array_buffer_allocator;
  return ret;
}