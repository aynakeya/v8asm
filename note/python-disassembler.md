# Python 离线反汇编器

`disassembler` 是当前推荐的 `.jsc` 解析入口。它直接解释
`ScriptCompiler::CachedData` 和 serializer payload，不初始化 V8 isolate，因此不会在
加载 startup snapshot 时触发原生 `CHECK` 或段错误。

## 基本用法

人类阅读使用文本输出：

```bash
uv run python -m disassembler input.jsc > /tmp/input.disasm.txt
```

传给 Python decompiler 时优先使用结构化 JSON：

```bash
uv run python -m disassembler input.jsc \
  --format json > /tmp/input.disasm.json

uv run python -m decompiler /tmp/input.disasm.json
```

自定义 Electron 或 Node runtime 的版本哈希可能不在标准 profile 中。已经确认其对象
布局与某个精确 V8 tag 一致时，可以显式指定版本和匹配的 startup snapshot：

```bash
uv run python -m disassembler input.jsc \
  --version 13.4.114.21 \
  --snapshot-blob v8_context_snapshot.bin \
  --format json > /tmp/input.disasm.json
```

`--version` 只选择源码布局，不会让不同 build flags 自动兼容。snapshot 的选择规则见
[cached-data-and-snapshot.md](cached-data-and-snapshot.md)。

## 解析流程

当前离线路径按以下顺序工作：

1. 识别 cached-data header 布局，并从编码的 payload 长度反推实际 header 大小；
2. 用版本哈希自动选择 profile，或使用显式 `--version`；
3. 根据 profile 的 serializer tag 和对象布局遍历 payload；
4. 建立稳定的对象引用图，恢复 `BytecodeArray`、constant pool、
   `SharedFunctionInfo`、`ScopeInfo`、数组和字符串等已支持对象；
5. 如果提供了匹配 snapshot，从 read-only heap 页中补充可以严格识别的字符串；
6. 输出文本，或输出供 decompiler 直接消费的结构化 JSON。

解析器不会通过搜索“看起来合理”的 opcode 来猜 payload 起点，也不会把未知对象猜成
应用层名称。不能证明的引用会保留为显式占位符。

## 版本配置的来源

profile 位于 `disassembler/profiles/`。生成器通过 `git show <tag>:<path>` 直接读取
官方 V8 tag 中的源码，不要求切换当前 V8 checkout：

```bash
uv run python -m disassembler.generate_profiles \
  --v8-repo /home/aynakeya/workspace/tmp/v8test/v8 \
  --output-dir disassembler/profiles
```

生成内容包括：

- bytecode opcode、operand 类型和宽度；
- serializer tag；
- `BytecodeArray`、`SharedFunctionInfo`、`ScopeInfo` 和 literal 对象布局；
- runtime、intrinsic 和 root 名称；
- static-root map、静态字符串及 snapshot space 信息；
- header 是否包含 read-only snapshot checksum。
- 对象字面量和计算属性定义的语义 flag 掩码。

以下少量输入仍由生成器代码维护，而不是从单个源码宏中自动推导：

- 需要生成的精确版本列表；
- 通用 operand 编码分类；
- 已由真实 cache 证明的 `flags_hash` 到 runtime-ID variant 映射。

因此应修改 `generate_profiles.py` 后重新生成，不能直接手改某个 profile JSON。新增
flags-hash 映射时必须保留对应 runtime、cache 和验证结果作为依据。

当前 profile 覆盖：

```text
10.2.154.4     10.2.154.26    10.8.168.25
11.3.244.8     11.4.183.14    11.9.169.7
12.4.254.12    12.4.254.21    12.9.202.28
13.2.152.41    13.4.114.14    13.4.114.21
13.6.233.8     13.6.233.10
```

profile 存在只表示解析器掌握该 tag 的静态布局，不等于所有 Electron、Node 或 Chromium
构建形态都已经有真实样本验证。

## 运行时编号变体

相同 numeric V8 版本可能因编译开关使用不同的 runtime-ID 表。解析器先根据
`flags_hash` 查找已经验证的 variant；无法确定时使用 profile 的默认值。只有掌握目标
runtime 的确切 variant 时才手动覆盖：

```bash
uv run python -m disassembler input.jsc \
  --version 13.2.152.41 \
  --runtime-variant leaptiering
```

错误 variant 主要会把 runtime 调用命名错位。它不能通过 opcode 是否“像 JavaScript”
可靠猜出，必须由相同 runtime 生成的 cache 或源码配置确认。

## 结构化 JSON

`--format json` 输出 `v8asm.disassembly` schema，当前版本为 1。主要特征：

- `metadata.v8_version` 明确记录实际使用的 profile 版本；
- `metadata.runtime_variant` 记录 runtime-ID 表；
- `metadata.literal_flags` 保存源码生成的字面量 flag，供 decompiler 区分跨版本语义；
- `ScopeInfo` / `SharedFunctionInfo.function_kind` 保存从源码布局解码的函数类型，区分普通函数、访问器与对象方法；
- `ScopeInfo.context_locals[].needs_initialization` 和 `outer_scope_info` 保留初始化状态与外层词法引用；
- `metadata.header` 保存动态识别的 cache header；
- `objects` 是按稳定逻辑地址索引的对象图；
- `object_order` 保留确定性的输出顺序；
- 引用、Smi、opcode operand 和 jump target 都是有类型字段；
- `source.kind` 和 `source.id` 区分 serializer object、root、read-only heap、
  startup/read-only/shared object cache 与 attached reference；
- `resolution` 明确表示对象来自 serialized payload、profile、匹配 snapshot、
  external identity，还是仍未解析；
- `type_evidence` 记录类型来自 bytecode layout、literal operand、字符串布局或
  profile root map。

逻辑地址不是 V8 进程中的 heap pointer。消费者必须跟随 `address` 引用，不能根据地址
前缀推导对象类型。字段统一使用 `under_score` 命名。完整兼容规则见
[JSON schema](disassembly-schema.md)。

当前 profile 没有完整的 V8 `InstanceType` 数值表。解析器只输出已有证据支持的类型；
对 object cache、attached reference 或 map 未知的对象保留 `unresolved`，不会从 object
ID、出现频率或调用位置猜测类型。

结构化路径避免 decompiler 再从人类可读文本中猜地址、参数或 jump target。文本格式仍
保留给人工检查和旧输入，但不再是新功能的主要接口。

## 固定数组和序列化对象

离线 parser 已直接恢复 serializer payload 中的 `FixedArray`、
`TrustedFixedArray`、array/object boilerplate 以及它们的元素引用。这个能力有独立回归
测试，不依赖原生 `v8asm` 的打印结果。

需要区分两种情况：

- 数组及字符串实际位于 `.jsc` payload 中时，离线 parser 可以恢复；
- 元素只引用 startup snapshot 的 read-only 对象时，仍需要匹配 snapshot 才能得到字符串。

原生 `v8asm` 可以作为补充对照，但不是正确性的唯一标准。原生对象 printer 本身也有
版本差异、截断和崩溃风险。

## 快照字符串恢复

当前 snapshot reader 支持 V8 11.9 至 13.6 使用的 page-image 格式，包括 static-roots
和 relocatable snapshot。只会解码 map 已明确证明为 sequential one-byte 或 two-byte
string 的对象。

以下对象不会被猜测展开：

- Cons、External、Sliced 和 Thin string；
- 未映射页洞或越界对象；
- map 不能可靠识别的 read-only 引用；
- V8 10.x 和 11.3 的旧 generic serializer snapshot 中尚未实现的字符串路径。

不传 snapshot 时仍会完整解析 payload，只是把这些引用保留为
`<read_only_空间,偏移>`。这比输出错误字符串更安全。

## 捕获应用实际提交给 V8 的数据

应用可能在磁盘 `.jsc` 外再包一层 header、加密、压缩或重写。只要应用最终通过
`vm.Script` 提交 `cachedData`，可以在该边界预加载捕获脚本：

```bash
V8_CACHE_DUMP_DIR=/tmp/v8-cache-dump \
NODE_OPTIONS="--require=/absolute/path/to/v8asm/disassembler/capture_cached_data.cjs" \
/path/to/electron-app
```

每个进程写入独立 PID 目录：

```text
0000.input.jsc       应用实际传入 vm.Script 的 buffer
0000.normalized.jsc  接受后由相同 runtime 重新生成的标准 cache
0000.payload.bin     从 normalized cache 精确切出的无 header payload
0000.json            V8 版本、文件名、大小和 rejected 状态
```

JSON 元数据中的 `v8_version` 来自 `process.versions.v8`，可用于确认捕获数据的实际
runtime。V8 接受输入后脚本会输出 normalized cache；只有该 cache 的 header 布局
唯一时才继续输出 raw payload。脚本不会猜 offset。

若应用禁用 `NODE_OPTIONS`，可在 Electron 主进程 `--inspect-brk` 暂停后通过调试器
加载脚本，或在复制出的应用 loader 中、`new vm.Script(...)` 之前显式 `require`。
具体 Windows 命令、ASAR 完整性限制和成功判据见[缓存捕获](capture-cached-data.md)。

## 直接解析原始负载

已从匹配 runtime 获得无 header serializer 数据时，使用：

```bash
uv run python -m disassembler 0000.payload.bin \
  --version 13.2.152.41 \
  --payload-offset 0 \
  --format json > /tmp/input.disasm.json
```

payload 位于更大容器中的已知偏移也可以显式给出：

```bash
uv run python -m disassembler wrapped.bin \
  --version 13.2.152.41 \
  --payload-offset 0x20
```

该模式必须提供 `--version`，因为 raw payload 已经没有 magic、版本哈希、flags hash、
RO checksum 和 payload 长度字段。offset 必须来自接受该数据的 runtime 或 wrapper
实现；工具不会暴力扫描整个文件。

## 新增版本的最小流程

1. 在 `generate_profiles.py` 的版本列表中加入精确 tag。
2. 从官方 V8 checkout 重新生成全部 profile，并审查 JSON diff。
3. 添加该版本 cache fixture 或由对应 runtime 生成测试输入。
4. 验证 header、serializer tag、对象布局、constant pool 和 jump target。
5. 有匹配 page-image snapshot 时，再验证 read-only 字符串恢复。
6. 用结构化 JSON 运行 decompiler，检查原始 `goto`、未知 opcode 和未解析对象指标。

不要为了让单个样本“能跑”而放宽全局 parser。出现
`payload length ... exceeds available ...` 时，先判断磁盘文件是否是标准 cached data，
再检查动态 header 和实际 `vm.Script` 输入；只有 runtime 已确认接受的 raw stream 才使用
`--payload-offset`。
