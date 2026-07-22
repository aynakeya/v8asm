# 缓存数据与启动快照兼容性

本文解释 `.jsc` header、serializer payload、startup snapshot 和 V8 binary
之间的关系。很多“header 不匹配”“加载 snapshot 崩溃”“字符串缺失”看起来相近，
但发生在不同层，修复方式不能混用。

## 三个兼容层次

### 缓存数据头和负载

`ScriptCompiler::CachedData` 由 header、对齐 padding 和 serializer payload 组成。
常见字段包括：

```text
magic
version_hash
source_hash
flags_hash
read_only_snapshot_checksum（部分版本没有）
payload_length
checksum
```

当前 Python parser 支持两种字段布局：

- 旧布局最少 24 字节，不包含 RO checksum；
- 新布局最少 28 字节，包含 RO checksum。

V8 会为了对齐在字段后加入零 padding，所以实际 `header_size` 可以是 28、32 或
更大的 4 字节对齐值。不能把新 header 永久写死成 32。parser 会从
`文件总长 - payload_length` 推导候选 header 大小，并要求 padding 全部为零且布局
唯一；无法唯一确认时直接报错。

### 启动快照

V8 binary 初始化 isolate 时先加载 startup snapshot。snapshot 包含 read-only heap、
startup roots、builtins、external-reference 索引等数据。`.jsc` serializer 可以引用
snapshot 中的对象，但不会把这些对象内容再次复制到 `.jsc`。

因此即使 cached-data payload 本身可解析，错误的 startup snapshot 仍可能在读取
`.jsc` 前让原生 V8 终止。

### 二进制文件的对象布局

pointer compression、sandbox、static roots、external code space 和 embedder 改动会
改变 tagged pointer、root 表或对象布局。跳过 header 检查不会使两种布局变得兼容。

完整兼容判断至少包含：

```text
V8 精确版本和 embedder suffix
cache magic
Version::Hash()
FlagList::Hash()
read-only snapshot checksum
pointer compression
sandbox
static roots
startup external-reference 表
```

## 两类 snapshot 文件

### 构建输出的 `snapshot_blob.bin`

V8 `out/<build>/snapshot_blob.bin` 与该目录的 binary 配套。它用于 self-cache 和构建
验证，也必须原样复制到相应 bin cache。

### Electron 或应用快照

Electron release 常同时提供：

```text
snapshot_blob.bin
v8_context_snapshot.bin
```

应用的 `.jsc` 可能在某个 context 中生成，因此实际匹配的文件经常是
`v8_context_snapshot.bin`。文件名不构成证据，应该比较：

1. snapshot 版本字符串；
2. `.jsc` header 的 RO checksum；
3. snapshot read-only section 的 magic/checksum；
4. 实际加载结果。

在原生矩阵里两种 Electron snapshot 都要测试。在 Python 离线解析中，传入与 cache
RO checksum 匹配的那个文件即可。

## 四种“绕过”不是一回事

### 缓存数据头与完整性检查绕过

作用位置：读取 `.jsc` 和进入 `CodeSerializer` 时。

它允许 magic、flags hash、RO checksum 等不一致的 cache 进入真实 V8 deserializer。
只在显式 `--force-incompatible` 下启用。payload 长度仍必须合理，不能因为强制模式
越界读取。

### 快照版本绕过

作用位置：`SnapshotImpl::CheckVersion`。

它处理类似：

```text
binary:   13.4.114.21
snapshot: 13.4.114.21-electron.0
```

这只表示允许同一 baseline 的 suffix 差异继续尝试，不解决内部 root 或对象布局差异。

### 外部引用表差异绕过

作用位置：startup snapshot 反序列化 external-reference table 时。

snapshot 中的 C++ 地址不会直接持久化，而是保存 table 索引。Electron 和 vanilla V8
可能拥有不同的 alias 数量或 sentinel。13.4 Atom 路径的 Electron snapshot table
大小为 1671，vanilla 13.4 binary 为 1672；仅跳过版本字符串仍会在 V8 初始化阶段
失败。

`v8asm-13.4.patch` 在 forced 模式下对这一条已验证差异做受控处理，并保留 stderr
诊断。该逻辑不是所有版本都必须有的通用兼容层，也不能解决 cross-major startup
root 差异。

### 静态根不能绕过

错误：

```text
Check failed: true == fixed_offset
Check failed: false == fixed_offset
```

来自 read-only deserializer 对 `V8_STATIC_ROOTS_BOOL` 和 snapshot 编码形态的检查。
正确处理是编译 `v8_enable_static_roots=true` 或 `false` 的匹配 binary。不要 patch 掉
这一对象布局检查。

## `--force-incompatible` 的边界

原生 `v8asm` 默认严格拒绝不兼容 cache：

```bash
./v8asm disasm input.jsc
```

研究模式：

```bash
./v8asm \
  --snapshot_blob /path/to/matching-snapshot.bin \
  disasm input.jsc \
  --force-incompatible
```

forced 模式意味着：

- 保留并打印所有已知 mismatch；
- 允许进入 V8 的真实 deserializer；
- 对对象发现和打印启用有限保护；
- 仍拒绝不可能的 payload 长度；
- 不承诺输出完整，也不承诺进程不会在更深的布局差异处终止。

以下结果不能由 forced 模式修复：

- pointer compression 不一致；
- static-roots 编码不一致；
- 不同 V8 baseline 的 startup root stream；
- serializer tag 或对象布局真正不同；
- 应用在传给 V8 前自行解密、解压或改写 `.jsc`。

最后一种情况应在应用的 `vm.Script` 边界捕获实际 `cachedData`，见
[python-disassembler.md](python-disassembler.md)。

## Atom 13.4 当前案例

当前示例输入：

```text
JSC：example2/atom.compiled.dist.jsc
numeric V8：13.4.114.21
snapshot：example2/v8_context_snapshot.bin
snapshot version：13.4.114.21-electron.0
static roots：true
```

当前 Python JSON 中的 header：

```text
magic：0xc0de0687
version_hash：0x2135fe8d
flags_hash：0x59eeb3ef
read_only_snapshot_checksum：0x4e6b3214
header_size：32（28 字节字段加 4 字节 padding）
payload_length：379616
```

这里必须使用 `v8_context_snapshot.bin`。示例目录中的 snapshot version、magic 和
RO checksum 都与 `.jsc` 对应。Python 路径不初始化 V8，可直接解析：

```bash
python3 -m disassembler example2/atom.compiled.dist.jsc \
  --version 13.4.114.21 \
  --snapshot-blob example2/v8_context_snapshot.bin \
  --format json > /tmp/atom.disasm.json
```

需要原生 oracle 时，使用 13.4 static-roots build：

```text
tests/decomp_rounds/bin_cache/
  v8asm.13.4.114.21.electron.staticroots.x64.release/
```

plain 或 Electron-suffix binary 是否能加载某个外部 context snapshot，仍取决于其
build shape 和 external-reference table；不能只看 `v8asm version`。

13.6 binary 即使加入更多 forced 探针，也不能稳定加载这个 13.4 startup snapshot。
它会在 read-only pages、string table、external refs 或 startup roots 的后续阶段分歧。
目标是可用输出时必须回到 13.4 baseline。

## Electron 34 与 V8 13.2 案例

Electron 34.3.0 对应：

```text
V8：13.2.152.41-electron.0
pointer compression：true
static roots：true
```

匹配 binary：

```text
tests/decomp_rounds/bin_cache/
  v8asm.13.2.152.41.electron.x64.release/v8asm
```

该 binary 已用于 `snapshot_blob.bin` 和 `v8_context_snapshot.bin` 两条 focused
路径。`electron.nostaticroots` 目录是反向诊断探针，对 Electron 34.3.0 使用时出现
`Check failed: false == fixed_offset` 是预期失败，不应继续 monkey patch。

## V8 10.8 案例

Electron 22.3.27 对应 `10.8.168.25-electron.0`。这个版本需要
`v8asm-10.8.patch`，并分别构建 Node 和 Electron 形态。验证 Electron cache 时，
必须让 `check_electron_version_matrix.py` 读取 Electron 自己的
`process.versions.v8` 后选择 exact binary，不能拿 10.2 或附近小版本替代。

## 不传 snapshot 会发生什么

Python disassembler 仍能恢复 `.jsc` 中自带的对象和 BytecodeArray，但对只存在于
read-only heap 的对象只能输出稳定引用，例如：

```text
<read_only_0,61552>
```

这不会漏掉 BytecodeArray，但会影响：

- 函数名；
- 属性名和方法名；
- 字符串常量；
- 后续 decompiler 的 method-call、字符串数组和对象字面量恢复。

不能根据调用形状把 unresolved 对象猜成 `push`、`JSON` 或应用字符串。传入匹配
snapshot 后，工具只在 map 明确是 sequential one-byte/two-byte string 时读取内容；
Cons、External、Sliced、Thin string 和未映射页洞仍保持显式占位。

## 排错顺序

1. 用 `checkversion` 或 Python profile 确认 exact numeric V8。
2. 检查 cache header 的 magic、flags hash、RO checksum 和动态 header size。
3. 比较目标 runtime 的 pointer compression、sandbox、static roots。
4. 对 Electron 同时测试两个 release snapshot，但按 RO checksum 判断哪个匹配。
5. `fixed_offset` 先换 build flag，不改 header 或 object-layout CHECK。
6. startup external-reference 报错只在已证明 table 差异时做窄 patch。
7. cache 能被应用接受但磁盘文件无法解析时，在实际 V8 API 边界捕获 normalized cache。
8. forced disasm 后仍检查 crash signature、占位符数量和 decompiler 质量，不能只看退出码。
