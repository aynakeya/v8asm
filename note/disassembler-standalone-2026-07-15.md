---
title: "不加载 V8 的 cached bytecode 反汇编器：格式、版本配置与验证"
date: 2026-07-15 00:00:00
tags:
  - v8
  - bytecode
  - electron
  - bytenode
  - reverse
categories:
  - Reverse
---

# 0x0 目标

原来的 `v8asm disasm` 会把 cached data 交回真实 V8 反序列化，再使用 V8
对象打印器输出 BytecodeArray。这种方式能够访问完整 isolate 和 startup
snapshot，但也带来三个问题：

1. 每个 V8 大版本都要维护和编译一套 patch，编译成本高。
2. Node/Electron 的 flags、pointer compression、sandbox、static roots 或
   startup snapshot 不一致时，进程可能在真正读取 `.jsc` 前就终止。
3. 放宽 header 检查只能允许 V8 尝试加载，不能让不同对象布局变得兼容。

新的 `disassembler` 不初始化 V8，也不链接 V8。它直接解析 code-cache
header、serializer object stream 和 Ignition bytecode，使用每个 V8 tag 的
JSON profile 解释版本差异。运行时只依赖 Python 标准库和仓库里的 profile。

# 0x1 使用方法

直接反汇编：

```bash
cd /home/aynakeya/workspace/v8asm
python3 -m disassembler input.jsc > /tmp/input.disasm.txt
```

继续交给现有 Python decompiler：

```bash
python3 decompiler/v8decompiler.py \
  /tmp/input.disasm.txt --level 4 --runtime \
  > /tmp/input.decompiled.js
```

正常情况下由 header 的 `version_hash` 选择 profile。自定义构建使用了未知
hash、但确认 bytecode/object layout 与某个 tag 相同时，可以显式指定：

```bash
python3 -m disassembler input.jsc --version 13.4.114.21
```

同一 numeric V8 版本可能因为 build flag 使用不同 Runtime ID 表。已知 flags
hash 会在 profile 中选择对应 variant；未知构建可以显式覆盖：

```bash
python3 -m disassembler input.jsc \
  --version 13.2.152.41 \
  --runtime-variant leaptiering
```

# 0x2 文件格式解析

## Code-cache header

工具支持两类 header：

- 旧版 24-byte header；
- 含 read-only snapshot checksum 的 32-byte header。

解析出的字段包括 magic、version hash、source hash、flags hash、RO snapshot
checksum、payload length 和 checksum。payload length 必须落在实际文件内；
离线工具不会为了“强制恢复”越界读取。

## Serializer object stream

payload 不是裸 BytecodeArray，而是 V8 serializer bytecode。解析器实现了：

- new object、backref、root、read-only heap ref 和 object cache ref；
- fixed/variable raw data 与 repeat root；
- weak、indirect、protected pointer prefix；
- self-indirect pointer 和 JS dispatch entry；
- pending forward-reference 注册、按 id 回填和 id 周期重置；
- V8 的 8-entry circular hot-object cache。

每个对象保存稀疏 raw image 和 tagged-slot reference 表。工具不构造 V8 heap，
也不解引用宿主进程地址，因此不会重现旧方案中错误对象地址导致的递归遍历
崩溃。这里不需要用 signal guard 隐藏 print；不能确定的对象保持显式占位。

## BytecodeArray

BytecodeArray 通过以下约束共同确认，而不是只搜索 opcode 字节：

1. 对象头内存在合理的 Smi bytecode length；
2. raw body 能被该版本 opcode profile 完整解码；
3. 最后一条指令是 Return、Throw、ReThrow、Abort 或 SuspendGenerator；
4. frame size、parameter encoding 和 metadata references 符合该版本布局。

恢复的元数据包括 parameter/register/frame size、constant pool、handler table
和 source-position table size。Wide/ExtraWide operand、register ABI、Runtime
ID、Intrinsic ID 以及 immediate/constant/backward jump target 都由 profile
驱动。

## SFI 与函数名

函数名不在 BytecodeArray 内。关联链为：

```text
SharedFunctionInfo -> trusted/function data -> BytecodeArray
SharedFunctionInfo -> name_or_scope_info -> ScopeInfo -> function name
```

12.x sandbox 过渡期和 13.x 的 SFI slot 不同；13.2 之后 ScopeInfo flags 从
Smi 改为 raw uint32，并把 position info 移入固定头。生成器把 SFI slot、
ScopeInfo flags bit、variable-part slot、module slot 和 local-name limit 写入
每版本 JSON。运行时代码没有按版本号分支。

输出的 SharedFunctionInfo 和 String 对象使用稳定 synthetic address，并引用
同一输出中的 BytecodeArray address。现有 decompiler 因而能恢复 `add`、
`listSum`、`calc` 等函数名以及 CreateClosure 常量。

# 0x3 版本 profile

当前 profile 包含以下 exact tags：

```text
10.2.154.4   10.2.154.26  10.8.168.25
11.3.244.8   11.4.183.14  11.9.169.7
12.4.254.12  12.4.254.21  12.9.202.28
13.2.152.41  13.4.114.14  13.4.114.21
13.6.233.8   13.6.233.10
```

每个 JSON 包含 opcode/operand 表、jump mode、serializer tags、BytecodeArray
layout、SFI/ScopeInfo layout、Runtime/Intrinsic names、root names 和可静态确定
的 read-only strings。

profile 生成属于维护流程，不是运行时依赖。生成器从本地官方 V8 git checkout
读取 exact tag，不切换当前 checkout：

```bash
python3 -m disassembler.generate_profiles \
  --v8-repo /home/aynakeya/workspace/tmp/v8test/v8 \
  --output-dir disassembler/profiles
```

内部读取方式等价于 `git show <tag>:<path>`。这避免切 branch、`gclient sync`
和重复编译，也不会破坏已有 build cache。只有需要新的原生 oracle binary 时，
才按官方 depot_tools 流程 checkout/sync，并固定使用 `autoninja -j10`。

# 0x4 验证结果

## Self-cache 大版本矩阵

仓库内 28 个 self-cache 目录中，26 个 header hash 能映射到 exact profile。
这些已知构建横跨 V8 10.2 到 13.6，并包含：

- pointer compression on/off；
- Node、Electron 和 vanilla build；
- 13.2 static-roots on/off；
- 13.4 Electron static-roots build。

26 个构建全部满足：

```text
native BytecodeArray count == offline count
native bytecode bytes == offline bytecode bytes
offline SFI count == BytecodeArray count
calc function name recovered
```

两个旧实验目录的 hash `0x3558f3a3` 和 `0x78824944` 不属于已配置的官方
tag，因此明确跳过。工具不会静默把未知 hash 当成“附近版本”。

## 真实 Electron cache

使用 Electron release 生成的 7 个 cache：

```text
Electron 19 / V8 10.2
Electron 22 / V8 10.8
Electron 25 / V8 11.4
Electron 30 / V8 12.4
Electron 34 / V8 13.2
Electron 35 / V8 13.4
Electron 36 / V8 13.6
```

每个文件的离线输出均与“对应 Electron context snapshot + 对应原生 v8asm”
得到的 3 个 BytecodeArray 字节完全一致，并恢复 3 条 SFI 关联和 `calc`。

## Bytenode cache

Node 18.20.8、20.20.2、22.17.0、24.7.0 的真实 bytenode cache 分别使用
对应 10.2、11.3、12.4、13.6 profile。4 个文件全部恢复 3/3 数组，字节与
对应 Node-aligned 原生 forced disassembly 完全一致。

## Static-roots 专用验证

static roots 是 build-time object-layout contract，不能靠跳过 cached-data
header 检查修复。验证使用缓存的专用 binary，其 metadata 为：

```text
version: 13.4.114.21-electron.0
v8_enable_pointer_compression=true
v8_enable_sandbox=true
v8_enable_static_roots=true
```

使用该构建自己的 `snapshot_blob.bin` 新生成 `01_arith.jsc` 后：

```text
native checkversion: exit 0
native disasm: exit 0, 2 arrays
offline disasm: exit 0, 2 arrays
native/offline bytecode: exact match
offline level-4 decompile: exit 0, 61 lines, calc recovered
```

因为正确的专用 binary 和 build cache 已存在，本轮没有重复编译。若缓存失效，
可以在 exact `13.4.114.21` checkout 上使用记录的 GN args 和
`autoninja -j10` 重建；普通 non-static-roots binary 不是有效替代品。

## Atom 大样本

离线工具直接读取用户提供的 `atom.compiled.dist.jsc`，不传 snapshot：

```bash
python3 -m disassembler atom.compiled.dist.jsc \
  > /tmp/atom.compiled.dist.offline.disasm.txt
```

与 13.4 static-roots 原生 binary 加 `v8_context_snapshot.bin` 的输出比较：

```text
native arrays:  794
offline arrays: 794
exact order and bytes: yes
native/offline metadata signature: exact match
missing arrays: 0
extra arrays: 0
offline SFI associations: 794
```

离线 disassembly 继续进入现有 level-4 decompiler 后：

```text
functions: 809
raw_goto: 0
unknown opcode comments: 0
undefined print fallbacks: 0
ACCU residue: 1928
```

现有原生 static-roots 结果同样是 809 functions、0 raw goto、0 unknown、
0 undefined fallback，ACCU residue 为 1941。核心反汇编和结构化质量达到现有
基线。

初次细粒度对照时，第 370 个数组的 constant pool/source table 分别被误报为
0/0，而原生值是 2/15。根因不是对象打印，而是 serializer parser 注册
`RegisterPendingForwardRef` 后没有在 `ResolvePendingForwardRef` 回填旧 slot。
按 V8 deserializer 的 id 生命周期实现回填后，794 个数组的 parameter、
register、frame、constant pool、handler、source size、Runtime name 和 jump
target 签名全部一致。该行为另有独立的 synthetic serializer 单元测试。

# 0x5 startup snapshot 字符串恢复

`.jsc` serializer 可以引用 startup snapshot 中的 read-only object，但不会把
该对象内容再次写入 cache。仅凭 `.jsc` 可以确定 `(space, offset)`，不能总是
恢复字符串内容。Atom 样本中有 134 个函数名属于这种情况。

现在可以显式传入匹配的 startup snapshot：

```bash
python3 -m disassembler atom.compiled.dist.jsc \
  --version 13.4.114.21 \
  --snapshot-blob v8context/v8_context_snapshot.bin \
  > /tmp/atom.offline.snapshot.disasm.txt
```

实现仍然是纯 Python，不加载或链接 V8。reader 解析外层 `SnapshotImpl` 容器、
read-only `SnapshotData` 和页镜像 bytecode，并把 `.jsc` 的 `(page,
object_chunk_offset)` 映射到 snapshot segment。只有 map 明确属于 sequential
one-byte/two-byte string 时才读取内容；Cons、External、Sliced、Thin string 和
未映射页洞不会按可打印字节猜测。

加载前会检查：

- snapshot V8 numeric version 与所选 profile 一致；
- read-only section magic 与 cached-data magic 一致；
- snapshot RO checksum 与 `.jsc` header 的 RO checksum 一致。

支持 V8 11.9 至 13.6 的 read-only page-image 格式，包括 11.9/12.4 的旧 opcode、
12.9 起的新 opcode、static-roots fixed pages 和普通 relocation pages。10.x 与
11.3 的旧通用 serializer snapshot 尚未支持，传入时会明确报错。

Atom 13.4 实测：

- 未传 snapshot：1102 次 `<read_only_...>`，其中 134 次是函数名；
- 传入 `v8context/v8_context_snapshot.bin`：两项均降为 0；
- 恢复出的值包括 `setTimeout`、`forEach`、`exports` 和压缩后的单字符函数名；
- 794 个 BytecodeArray 的 byte stream 与 metadata 签名保持不变。

另外用现有 build cache 的 15 组真实 `snapshot_blob.bin` 验证了 11.9、12.4、
12.9、13.2、13.4 和 13.6，覆盖 Electron、Node、13.2 non-static-roots 以及
13.4 static-roots。加载 snapshot 前后的 bytecode 和 metadata 均一致。

不传 `--snapshot-blob` 时仍输出稳定占位符：

```text
<read_only_0,61552>
```

decompiler 会生成稳定的 `read_only_0_61552` 名称。它不会漏 print，也不会
根据调用位置猜测这是 `log`。static-roots.h 中有确定映射的字符串仍会由
profile 正常恢复。

# 0x6 回归命令

```bash
python3 -m compileall -q disassembler
python3 -m unittest tests.test_disassembler -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

`tests.test_disassembler` 固化了 tracked sample、26-build self-cache matrix、
7 个真实 Electron cache 和 4 个 bytenode cache 的原生字节对照。验证比较的是
完整 instruction byte stream，而不是只检查进程 exit code 或输出中是否存在
`BytecodeArray` 字样。
