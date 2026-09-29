---
title: "V8 Bytecode反编译不完全指南"
date: 2025-09-14 00:34:22
tags:
    - ctf
    - v8
    - javascript
    - reverse
    - bytecode
categories:
    - CTF
---

# 0x0 Introduction

> 历史原稿（2025）：保留最初研究过程，不代表当前能力。文中的构建命令、打印保护、
> 手工 header 偏移和补丁片段不应直接用于现在的版本；当前入口见
> [文档索引](../README.md)。原文配图属于已发布博客，不在此仓库中。

> V8! 兄弟们V8! 真男人就要用V8！

V8字节码反汇编与反编译过程中的实践与经验，涵盖构建 V8、分析 bytecode 格式、尝试绕过校验与反汇编/反编译的一些非官方方法瞄。

（如有错漏，敬请指正）

<!-- more -->

# 0x1 Brief && Why

反正总之我也不知道，因为Javascript在市面上用的越来越多了，与之相对的，开发者们对js的保护的需求也越来越多了。

但是因为Javascript是一门解释型语言，代码运行依赖与解释器，解释器又需要代码本身直接存在，所以从根源上来说js相比c相比编译型语言就更容易被反编译——至少门槛会高不少。

这叫什么来着——人民日益增长的 JS 代码保护需求，和 JavaScript 作为解释型语言先天裸奔、易反编译的“矛盾”。

举个栗子，你可能有一个非常核心的函数：

`core.js`
```javascript
function validate(license) {
    if (license === "lol_you_will_never_know") {
        console.log("valid")
        return true
    }
    console.log("not valid")
    return false;
}

module.exports = { validate };
```

我们可以通过另外一个js来调用这个函数

```javascript
const core = require("./core.js");

console.log(core.validate("aaaaa"));
```

但是在这种情况下，即便你的 validate 函数再怎么复杂、高级、noble，fancy。如果你把这个文件打包进去随应用一起发布，那么`core.js`相当于对用户是明文的。

一些“逆向爱好者(比如我)”可能会打开 core.js，然后直接找到你的验证函数，恭喜你，验证逻辑直接暴露了。

更别说如果你是写 Electron 应用、或者做的是类似客户端验证这种场景——那基本是毫无遮掩地把验证逻辑送到了攻击者面前，这样就很不安全。

## Bytenode

所以为了保护我们可爱的js代码，最近（并非最近）有一种方式开始慢慢流行起来了，那就是把你的核心js代码编译成字节码，然后通过vm加载，这样子你的核心代码就不容易被反编译啦。

实现这个方式，有一个工具可以用 —— [bytenode](https://github.com/bytenode/bytenode)。

一句话介绍：

> **Bytenode 是一个可以把 JavaScript 源码编译成 V8 字节码的工具。**

它的主要用途就是把你的 `.js` 编译成 `.jsc` 文件，然后你用 Node.js 或 Electron 的 `vm` 模块去加载这个字节码，而不是原始代码。

那么接下来我们就可以尝试把上面那段代码保护起来了

首先我们需要安装一下 `bytenode`：

```bash
pnpm install bytenode
```

然后把那个 `core.js` 编译成字节码。注意，bytenode 的编译目标是 `.jsc` 文件，里面包含的就是Js Bytecode。

```bash
bytenode --compile core.js
```

运行完之后，你会得到一个 `core.jsc` 文件，但是这个文件不能直接通过`require()`导入。因为 Node.js 不知道怎么处理 `.jsc`。

所以我们得写个引导程序，比如说 `main.js`：

```javascript
require("bytenode");
const core = require("./core.jsc");

console.log(core.validate("aaaaa"));
```

然后再运行，你就会得到如下输出

```
not valid
false
```

但这次不一样的是，`core.jsc`并不包含原始代码。打开`core.jsc`，看到的也只是一些神必字节流。

不赖，安全感++。

```bash
03:57:21 $ xxd core.jsc
00000000: 8806 dec0 1477 2c2b 1701 0000 9b61 7c1c  .....w,+.....a|.
00000010: 4243 1cd3 b803 0000 0000 0000 0000 0000  BC..............
00000020: 0124 5403 2407 b460 0000 0000 0600 0000  .$T.$..`........
00000030: 0108 07bd 0e04 0421 030c 0785 0161 0000  .......!.....a..
00000040: 0000 0700 0000 0104 0200 0adc 0800 2107  ..............!.
00000050: 4111 2103 0c07 7d01 6000 0000 0001 0000  A.!...}.`.......
00000060: 0001 2454 032c 9060 0000 0000 1800 0000  ..$T.,.`........
00000070: 0108 9104 1821 0310 9362 0000 0000 0d00  .....!...b......
00000080: 0000 012c 0300 0aac 070f 4c0d 0f0a 4000  ...,......L...@.
00000090: 0000 2194 2103 1895 6000 0000 0004 0000  ..!.!...`.......
```

所以, 这个神必字节流到底是什么呢，这其实就是 **V8 Bytecode**。


# 0x2 The V8 Engine

所以，什么是 V8 呢？

你说的对，但是《[**V8**](https://v8.dev/)》是由 Google 自主研发的一款高性能 JavaScript 引擎。它运行在一个被称作「堆（Heap）」的内存世界，在这里，被即时编译器（JIT）选中的函数将被授予「优化编译」的加护，导引处理器的力量。你将扮演一位名为「脚本（Script）」的神秘角色，在解释执行与优化编译之间来回穿梭，邂逅性格各异、职责独特的伙伴们 (**Ignition**、**TurboFan**、**Orinoco**、等）。和他们一起击败延迟与瓶颈，找回丢失的性能——同时，逐步发掘**V8**的真相。

而所谓的v8 bytecode就是一种Ignition解释器能够读得懂的代码，**V8 bytecode 本质上就是 V8 自己序列化出来的一段数据**。

## 先尝试编译编译 V8

我们关心它的原因很简单：bytenode 生成的 `.jsc` 其实就是 V8 的字节码格式。

所以在我们更加深入v8之前，我们首先要能够拿到v8的代码，并且能够编译，毕竟如果不能编译运行，那么一切对字节码的分析、调试就会非常困难。

构建流程本身不复杂，具体可以参照官方文档，[Building V8 from source](https://v8.dev/docs/build)

简单来说，编译一个适合node的v8可以这么做

```bash
cd your_working_dir
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
export PATH="$PWD/depot_tools:$PATH"

fetch v8
cd v8

gn gen out/node.x64.release --args='is_debug=false v8_enable_disassembler=true v8_enable_object_print=true v8_enable_pointer_compression=false'


# compile may takes years if your computer sucks
ninja -C out/debug d8
```

## 关于选用正确 V8 版本这一件事

首先要注意到的是V8 bytecode的内部结构不是固定的。

不同版本的V8，在很多底层实现细节上都可能完全不一样，尤其是字节码层面：

- 不同版本的 V8 使用的opcode集合可能不同
- 同一个 opcode 的编号、参数含义也可能不同
- 内部使用的寄存器布局（register allocation） 会随着优化器改动而改变

这就意味着，不同版本编译出来的字节码结构也不一样。甚至有时候只升级一个小版本，字节码也会有很大的不同。

如果你需要切换 V8 版本，可以这样做：

```bash
git checkout <version_tag>
gclient sync -D
```

常用的 tag 长这样（例）：

```bash
git tag -l | grep ^11.
# 11.8.172.13
```

然后重新走一遍 `gn gen ...` + `ninja -C out/...` 的构建流程。

如果你想知道你现在使用的 Node.js 用的是哪一版 V8，可以直接执行`node -p process.versions.v8`：

```bash
00:01:14 $ node -p process.versions.v8
12.4.254.21-node.26
```

如果你想查询其他 Node.js 版本对应的 V8 版本，也可以去
[Node.js 旧版本列表](https://nodejs.org/en/about/previous-releases) 页面，点击对应版本后面的 **details**，就能看到它内置的 V8 版本号。

![](https://www.aynakeya.com/images/ctf/a-quick-guide-to-disassemble-v8-bytecode/Screenshot_20250915_235655.png)


## 关于 build args 的一些坑

还有一个非常容易被忽略的点：V8 bytecode的内部结构不仅不同版本不一样，在不同编译编译参数（build args）下，也就是前面`--args=`里面的内容，v8 bytecode的内部结构也不一样。

简单来说就是，如果你build v8时所用的build args和实际生成bytecode时所用的v8不一致，那你得到的字节码结构和真实环境里的结构可能会完全对不上，从而导致反编译、反汇编失败。

几个需要注意的点：

- `v8_enable_pointer_compression`
    - 详情可看[https://v8.dev/blog/pointer-compression](https://v8.dev/blog/pointer-compression)
    - 控制是否启用指针压缩（Pointer Compression）
    - 默认在`true`
    - Node.js 构建时是禁用压缩指针，选`false`（见 [Node 源码 common.gypi](https://github.com/nodejs/node/blob/main/common.gypi#L68)）
    - Electron 则需要 `true`（见 [Electron Blog](https://www.electronjs.org/blog/v8-memory-cage)）
- `is_debug`
    - 注意正式反编译不要开 debug 模式，不然大概率报错
    - Debug 模式下很多结构体会多出额外字段、填充、调试信息
    - node, electron等用户使用的一般都是在release下模式build的，所以我们也得release
- `v8_enable_disassembler`, `v8_enable_object_print`
    - 开着就完事了

**但是node.js和electron和原版的v8还是有一些区别的，因为这两个都因为自身的需要对v8做了patch。**

*electron用了node，electron也对node做了一定的patch。*

如果环境不匹配就有可能导致反编译失败，因为内部的结果会不一样。

所以如果想要一比一复刻node.js环境的话，需要根据[nodejs/node](https://github.com/nodejs/node)自己修改

相对应的如果想要一比一符合electron环境，需要根据[electron patches](vhttps://github.com/electron/electron/blob/main/patches/node/.patches)，先打好对应的补丁。

# 0x3 V8 Bytecode结构

**注意：为了方便，使用的node版本为`v24.7.0`, 对应v8版本`13.6.233.10-node.26`，不同版本bytecode结构可能不同**


我们注意到，v8 bytecode实际上是在编译 JavaScript 脚本时，由 `CodeSerializer::Serialize` 生成的。

所以我们想分析v8字节码，最好也是最直接的方式就是去翻源码看看它是怎么“打包”的。

在 `src/snapshot/code-serializer.cc` 中可以找到 `CodeSerializer::Serialize` 的实现：

`CodeSerializer::Serialize` 会把一段 JavaScript 函数编译出的字节码（BytecodeArray）以及它依赖的各种上下文（常量池、对象字面量、跳转表、源信息等）打包进一段连续的二进制流中。

`src/snapshot/code-serializer.cc`
![](https://www.aynakeya.com/images/ctf/a-quick-guide-to-disassemble-v8-bytecode/Screenshot_20250917_225432.png)

这段序列化出来的二进制流，会被包裹在一个 `AlignedCachedData` 对象里，来生成最终的字节码，并作为`CachedData` 返回。

而`AlignedCachedData` 又使用了`SerializedCodeData`来生成字节码。

```cpp
// 'src/snapshot/code-serializer.cc'
AlignedCachedData* CodeSerializer::SerializeSharedFunctionInfo(
    Handle<SharedFunctionInfo> info) {
  DisallowGarbageCollection no_gc;

  VisitRootPointer(Root::kHandleScope, nullptr,
                   FullObjectSlot(info.location()));
  SerializeDeferredObjects();
  Pad();

  SerializedCodeData data(sink_.data(), this);

  return data.GetScriptData();
}

```


所以，查看`SerializedCodeData`的实现和header文件我们可以大致知道字节码的格式。

## SerializedCodeData 头部结构

`SerializedCodeData` 是整个字节码的最外层数据结构，位于 `src/snapshot/code-serializer.h` 中。

```cpp
// 'src/snapshot/code-serializer.h'
class SerializedCodeData : public SerializedData {
 public:
  // The data header consists of uint32_t-sized entries:
  static const uint32_t kVersionHashOffset = kMagicNumberOffset + kUInt32Size;
  static const uint32_t kSourceHashOffset = kVersionHashOffset + kUInt32Size;
  static const uint32_t kFlagHashOffset = kSourceHashOffset + kUInt32Size;
  static const uint32_t kReadOnlySnapshotChecksumOffset =
      kFlagHashOffset + kUInt32Size;
  static const uint32_t kPayloadLengthOffset =
      kReadOnlySnapshotChecksumOffset + kUInt32Size;
  static const uint32_t kChecksumOffset = kPayloadLengthOffset + kUInt32Size;
  static const uint32_t kUnalignedHeaderSize = kChecksumOffset + kUInt32Size;
  static const uint32_t kHeaderSize = POINTER_SIZE_ALIGN(kUnalignedHeaderSize);
//
// some code ignored
// ...
}


// 'src/snapshot/code-serializer.cc'
SerializedCodeData::SerializedCodeData(const std::vector<uint8_t>* payload,
                                       const CodeSerializer* cs) {
  DisallowGarbageCollection no_gc;

  // Calculate sizes.
  uint32_t size = kHeaderSize + static_cast<uint32_t>(payload->size());
  DCHECK(IsAligned(size, kPointerAlignment));

  // Allocate backing store and create result data.
  AllocateData(size);

  // Zero out pre-payload data. Part of that is only used for padding.
  memset(data_, 0, kHeaderSize);

  // Set header values.
  SetMagicNumber();
  SetHeaderValue(kVersionHashOffset, Version::Hash());
  SetHeaderValue(kSourceHashOffset, cs->source_hash());
  SetHeaderValue(kFlagHashOffset, FlagList::Hash());
  SetHeaderValue(kReadOnlySnapshotChecksumOffset,
                 Snapshot::ExtractReadOnlySnapshotChecksum(
                     cs->isolate()->snapshot_blob()));
  SetHeaderValue(kPayloadLengthOffset, static_cast<uint32_t>(payload->size()));

  // Zero out any padding in the header.
  memset(data_ + kUnalignedHeaderSize, 0, kHeaderSize - kUnalignedHeaderSize);

  // Copy serialized data.
  CopyBytes(data_ + kHeaderSize, payload->data(),
            static_cast<size_t>(payload->size()));
  uint32_t checksum =
      v8_flags.verify_snapshot_checksum ? Checksum(ChecksummedContent()) : 0;
  SetHeaderValue(kChecksumOffset, checksum);
}
```


从实现可以看到，它的整体结构分为两部分：

1. **Header（头部）**
   位于文件最前方，长度固定，包含若干个 `uint32_t` 字段，用来存放版本号、校验信息、payload 长度等。
2. **Payload（主体数据）**
   紧随在 header 之后，存放真正的字节码及相关数据。

头部大致长这样：

| 偏移量         | 含义                          |
| ----------- | --------------------------- |
| 0           | Magic number                |
| +4          | Version hash（版本哈希）          |
| +8          | Source hash（源码哈希）           |
| +12         | Flag hash（编译参数哈希）           |
| +16         | Read-only snapshot checksum |
| +20         | Payload length           |
| +24         | code checksum             |
| +28 \~ 对齐填充 | Padding                     |
| +HeaderSize | Payload 开始位置                |

这些字段是在 `SerializedCodeData::SerializedCodeData` 构造函数中被依次写入的。

最后，还会将 `payload` 拷贝到 header 后面，并计算 checksum。

## 暴力搜索bytecode对应的v8版本

在前文中提到，知道v8版本对于反编译v8字节码至关重要。

但如果我们手上只有一个 `.jsc` 文件，又不知道它是用哪个版本编译的，该怎么办？

答案藏在 Header 里的 **`VersionHash`** 字段。

### VersionHash 是什么

注意到，在 `SerializedCodeData` 的构造流程中，会把当前 V8 的版本信息写入 Header。

这个版本号不是直接存文本，而是经过哈希函数压缩成一个 `uint32_t`：

- `major`（主版本）
- `minor`（次版本）
- `build`（构建号）
- `patch`（补丁号）

这四个整数会被 `Version::Hash()` 计算成一个 32 位整数，写入 Header 的 `kVersionHashOffset` 位置。

`Version::Hash()` 的实现可以在 `src/utils/hash.h` 里找到，它调用了 `base::hash_combine()`，而 `hash_combine` 的底层实现在 `src/base/hashing.h` 中。

**Version Hash的生成方式**: `src/utils/hash.h`
```cpp
// src/utils/hash.h

// ...
class V8_EXPORT Version {
 public:
// ...
  static uint32_t Hash() {
    return static_cast<uint32_t>(
        base::hash_combine(major_, minor_, build_, patch_));
  }
// ...
 private:
  static int major_;
  static int minor_;
  static int build_;
  static int patch_;
```


**Hash的具体实现**: `src/base/hashing.h`
```cpp
// src/base/hashing.h

V8_INLINE size_t hash_combine(size_t seed, size_t hash) {
#if V8_HOST_ARCH_32_BIT
  const uint32_t c1 = 0xCC9E2D51;
  const uint32_t c2 = 0x1B873593;

  hash *= c1;
  hash = bits::RotateRight32(hash, 15);
  hash *= c2;

  seed ^= hash;
  seed = bits::RotateRight32(seed, 13);
  seed = seed * 5 + 0xE6546B64;
#else
  const uint64_t m = uint64_t{0xC6A4A7935BD1E995};
  const uint32_t r = 47;

  hash *= m;
  hash ^= hash >> r;
  hash *= m;

  seed ^= hash;
  seed *= m;
#endif  // V8_HOST_ARCH_32_BIT
  return seed;
}

// ...

template <typename T>
V8_INLINE size_t hash_value_unsigned_impl(T v) {
  switch (sizeof(T)) {
    case 4: {
      // "32 bit Mix Functions"
      v = ~v + (v << 15);  // v = (v << 15) - v - 1;
      v = v ^ (v >> 12);
      v = v + (v << 2);
      v = v ^ (v >> 4);
      v = v * 2057;  // v = (v + (v << 3)) + (v << 11);
      v = v ^ (v >> 16);
      return static_cast<size_t>(v);
    }
    case 8: {
      switch (sizeof(size_t)) {
        case 4: {
          // "64 bit to 32 bit Hash Functions"
          v = ~v + (v << 18);  // v = (v << 18) - v - 1;
          v = v ^ (v >> 31);
          v = v * 21;  // v = (v + (v << 2)) + (v << 4);
          v = v ^ (v >> 11);
          v = v + (v << 6);
          v = v ^ (v >> 22);
          return static_cast<size_t>(v);
        }
        case 8: {
          // "64 bit Mix Functions"
          v = ~v + (v << 21);  // v = (v << 21) - v - 1;
          v = v ^ (v >> 24);
          v = (v + (v << 3)) + (v << 8);  // v * 265
          v = v ^ (v >> 14);
          v = (v + (v << 2)) + (v << 4);  // v * 21
          v = v ^ (v >> 28);
          v = v + (v << 31);
          return static_cast<size_t>(v);
        }
      }
    }
  }
  UNREACHABLE();
}

// ...

template <typename... Ts>
V8_INLINE size_t hash_combine(Ts const&... vs) {
  return Hasher{}.Combine(vs...);
}

// ...
```


### 暴力破解 VersionHash

知道了算法，就可以反推版本号。

思路也很简单：对一堆可能的 `(major, minor, build, patch)` 组合做哈希，看看有没有等于我们提取到的那个 hash 值的。

由于V8的版本号有限，且范围并不大（major/minor 一般 0\~20，build 也就几百），所以穷举搜索完全可行，跑一会儿就能出来。

代码如下

```cpp
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
```

当然我们也可以手动实现hash函数

```c
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

// refer to v8/src/utils/version.h
//          v8/src/utils/version.cc

typedef struct {
    int major;
    int minor;
    int build;
    int patch;
} Version;


uint32_t hash_value_unsigned_32(uint32_t v) {
    v = ~v + (v << 15);
    v = v ^ (v >> 12);
    v = v + (v << 2);
    v = v ^ (v >> 4);
    v = v * 2057;
    v = v ^ (v >> 16);
    return v;
}

static size_t hash_combine(size_t seed, size_t hash) {
    const uint64_t m = 0xC6A4A7935BD1E995ULL;
    const uint32_t r = 47;

    hash *= m;
    hash ^= hash >> r;
    hash *= m;

    seed ^= hash;
    seed *= m;
    return seed;
}

uint32_t calculate_version_hash(int major, int minor, int build, int patch) {
    uint32_t seed = 0;
    seed = hash_combine(seed, hash_value_unsigned_32((uint32_t)major));
    seed = hash_combine(seed, hash_value_unsigned_32((uint32_t)minor));
    seed = hash_combine(seed, hash_value_unsigned_32((uint32_t)build));
    seed = hash_combine(seed,  hash_value_unsigned_32((uint32_t)patch));
    return (uint32_t)seed;
}

Version bruteforce_v8_version(uint32_t hash) {
    for (int major = 0; major < 20; ++major) {
        for (int minor = 0; minor < 20; ++minor) {
            for (int build = 0; build < 500; ++build) {
                for (int patch = 0; patch < 200; ++patch) {
                    if (calculate_version_hash(major, minor, build, patch) == hash) {
                        Version found_version = {major, minor, build, patch};
                        return found_version;
                    }
                }
            }
        }
    }
    Version not_found_version = {-1, -1, -1, -1};
    return not_found_version;
}
```

到了这里我们就可以通过hash暴力破解版本号，比如

![](https://www.aynakeya.com/images/ctf/a-quick-guide-to-disassemble-v8-bytecode/Screenshot_20250917_232152.png)

可以看到暴力破解出来的版本号为`13.4.114.21`

这样一来，即便我们拿到的是一份完全未知的 `.jsc` 文件，也能先定位它是哪个V8版本生成的，然后再去寻找对应源码版本进行反汇编分析。


## [ReWrite](https://bgm.tv/subject/147568)  Code Checksum

todo

# 0x4 Disassembly 反汇编

**注意：这里使用的node版本为`v24.7.0`, 对应v8版本`13.6.233.10-node.26`，不同版本的api可能不同**

在前面我们已经成功解析出了v8字节码的整体格式，现在要做的就是让V8帮我们把这堆 bytecode 重新“读”出来。

好消息是：V8 本身就内置了反汇编功能。

## 内置的 `--print-bytecode`

如果你曾经尝试过在Node.js中使用 `--print-bytecode` 参数运行任意js文件，你就会发现在运行之前，程序会输出一大段的文本，而这正是反汇编的结果。

![](https://www.aynakeya.com/images/ctf/a-quick-guide-to-disassemble-v8-bytecode/Screenshot_20250918_231622.png)

也就是说，**V8 其实已经自带了一个完整的字节码反汇编器**，我们要做的就是想办法“绕过源码编译阶段”，让它直接把v8字节码打印出来

## BytecodeArray::Disassemble → Object::Print

跟踪 `--print-bytecode` 的执行流程，可以发现它最终会调用 `BytecodeArray::Disassemble` 来输出字节码。
进一步跟进去，这个函数内部又会调用 `Print`，而 `Print` 则是定义在 `src/diagnostics/objects-printer.cc` 里的。

这个文件可以说是 V8 所有对象（`Object`）调试输出的总控制中心，几乎所有类型对象的打印逻辑都定义在这里。
换句话说，只要你手上拿到了任意一个 V8 对象实例（`Object`），就可以直接调用它的 `Print()` 方法，然后 V8 就会自动打印出它的字节码、寄存器、常量池等调试信息。

![](https://www.aynakeya.com/images/ctf/a-quick-guide-to-disassemble-v8-bytecode/Screenshot_20250918_232401.png)

## CodeSerializer::Deserialize

问题来了：我们手上只有v8字节码，这些字节码要怎么才能变成一个`Object`呢？

答案还是在 `CodeSerializer`中，它有一个非常关键的函数：`CodeSerializer::Deserialize`。

这个函数接收一段 `AlignedCachedData`，会尝试把其中的字节码反序列化回一个 `SharedFunctionInfo` 对象。

而这个 `SharedFunctionInfo`，就是一个实实在在的 V8 Object，拿到它之后我们就可以直接 `Print()` 输出它的字节码。

```cpp
// 'src/snapshot/code-serializer.cc'

MaybeDirectHandle<SharedFunctionInfo> CodeSerializer::Deserialize(
    Isolate* isolate, AlignedCachedData* cached_data,
    DirectHandle<String> source, const ScriptDetails& script_details,
    MaybeDirectHandle<Script> maybe_cached_script) {
// ...
    const SerializedCodeData scd = SerializedCodeData::FromCachedData(
          isolate, cached_data,
          SerializedCodeData::SourceHash(source, wrapped_arguments,
                                         script_details.origin_options),
          &sanity_check_result);
      if (sanity_check_result != SerializedCodeSanityCheckResult::kSuccess) {
        if (v8_flags.profile_deserialization) {
          PrintF("[Cached code failed check: %s]\n", ToString(sanity_check_result));
        }
        DCHECK(cached_data->rejected());
        isolate->counters()->code_cache_reject_reason()->AddSample(
            static_cast<int>(sanity_check_result));
        return MaybeDirectHandle<SharedFunctionInfo>();
      }

// ...
}
```

## 绕过 SanityCheck 校验

当然，`CodeSerializer::Deserialize`也有一些限制。

`CodeSerializer::Deserialize` 内部会调用 `SerializedCodeData`来初始化v8字节码数据， SerializedCodeData内部会调用 `SerializedCodeData::SanityCheck`、`SanityCheckJustSource` 和 `SanityCheckWithoutSource`，对传入的
v8字节码做关于版本、快照、hash 等一堆东西的验证。

如果任何一项没通过，它会直接 reject 掉这份缓存，返回空对象。

为了反汇编，我们可以选择最简单粗暴的方法：

**把这些检查全删掉。**

![](https://www.aynakeya.com/images/ctf/a-quick-guide-to-disassemble-v8-bytecode/muzimi.png)

做法也很简单，把这三个 `SanityCheck*` 函数的返回值硬改为 `kSuccess`，让它无条件通过即可。

```cpp
SerializedCodeSanityCheckResult SerializedCodeData::SanityCheck(
    uint32_t expected_ro_snapshot_checksum,
    uint32_t expected_source_hash) const {
  return SerializedCodeSanityCheckResult::kSuccess;
}

SerializedCodeSanityCheckResult SerializedCodeData::SanityCheckJustSource(
    uint32_t expected_source_hash) const {
  uint32_t source_hash = GetHeaderValue(kSourceHashOffset);
  return SerializedCodeSanityCheckResult::kSuccess;
}

SerializedCodeSanityCheckResult SerializedCodeData::SanityCheckWithoutSource(
    uint32_t expected_ro_snapshot_checksum) const {
  return SerializedCodeSanityCheckResult::kSuccess;
}
```
> 全~都 删掉！

## Print Everything

一旦v8字节码成功被反序列化成 `SharedFunctionInfo`，剩下的事情就很简单了

遍历整个对象图，把字节码内所有还原出来的对象都按内存地址顺序 `Print()` 一遍就ok了。


```cpp
class V8ObjectExplorer {
public:
    explicit V8ObjectExplorer(v8::internal::Isolate* isolate) : isolate_(isolate) {}

    void Disassemble(v8::internal::Tagged<v8::internal::Object> start_obj) {
        // printf("before traversal\n");
        DiscoverReachableObjects(start_obj);
        // printf("traversal done!\n");
        PrintDiscoveredObjects();
        // printf("disassemble done!\n");
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
```

# 0x5 Decompilation 反编译

我们主要参照[View8](https://github.com/suleram/View8)，来实现我们的反编译功能

todo

# 0x6 Some thoughts

好吧，实际上最开始我只是想破解一下typora，因为最新的typora是通过bytecode加载核心代码的。所以最开始就是想反编译这个，但是目前还是没有成功的反编译出来。感觉可能是electron的vanilla v8的区别有点大吧。

虽然我尝试了使用node中的v8，但是node中的v8也不能反编译typora的jsc文件。

总的来说就是为了一碗醋包了个饺子，虽然到最后也没能沾上醋。。。

但是至少吃上饺子了，不是么。

anyway，这里是项目代码[aynakeya/v8asm](https://github.com/aynakeya/v8asm)，喜欢的可以点个star。

# 0x7 Reference && Further Reading

- [V8 字节码反编译 还原bytenode保护的js代码](https://rce.moe/2025/01/07/v8-bytecode-decompiler/)
- [xqy2006/jsc2js](https://github.com/xqy2006/jsc2js)
- [某知笔记服务端docker镜像授权分析](https://guage.cool/wiz-license.html)
- [Pointer Compression in V8](https://v8.dev/blog/pointer-compression)
- [n1ctf 2022 Desktop-Apps write-up](https://github.com/Nu1LCTF/n1ctf-2022/blob/main/Re/Desktop-Apps/README.md)
- [nodejs/node](https://github.com/nodejs/node)
- [JSC字节码反编译初探](https://www.52pojie.cn/thread-2054765-1-1.html)
- [d2大会 - 如何通过逆向工程从v8进程中复活node的内容记录与读后感](https://juejin.cn/post/6844903808699629575)
- [通过字节码保护Node.js源码之原理篇](https://zhuanlan.zhihu.com/p/359235114)
- [理解 V8 的字节码「译」](https://zhuanlan.zhihu.com/p/28590489)
- [基于 Node.js Addon 和 v8 字节码的 Electron 代码保护解决方案](https://zhuanlan.zhihu.com/p/376638202)

# 0x9 Extra

node build args
```bash
gn gen out/node.x64.release --args='is_debug=false v8_enable_disassembler=true v8_enable_object_print=true v8_enable_handle_zapping=false v8_enable_pointer_compression=false v8_enable_31bit_smis_on_64bit_arch=false v8_enable_hugepage=false v8_enable_fast_mksnapshot=false v8_win64_unwinding_info=true v8_enable_map_packing=false v8_enable_pointer_compression_shared_cage=false v8_enable_external_code_space=false v8_enable_sandbox=false v8_enable_v8_checks=false v8_enable_zone_compression=false v8_use_perfetto=false is_cfi=false'
```


## Build Node.js patched V8

todo

## Building Electron patched V8

todo
