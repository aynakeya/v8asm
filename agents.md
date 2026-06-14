# v8asm Agent Primer

codex resume 019c42ba-60e2-7cb0-905b-0edd833425d3

这个仓库是一个面向 V8 字节码（`.jsc`）的工具集，目标是：

1. `v8asm`：把 JS 编译成字节码、反汇编字节码。
2. `decompiler/`：把反汇编文本恢复成接近 JS 的伪代码（可选 runtime 前导，尽量可直接运行）。
3. `checkversion/`：根据版本哈希爆破 V8 版本。

## Current Environment Assumptions

- 仓库根目录存在可执行文件：`./v8asm`
- 当前已确认：`./v8asm version` 输出 `13.6.233.10`（对应 Node `v24.7.0`）
- 本地通过 `nvm` 可切换 Node 版本；回归测试默认使用 `v24.7.0`

## Repository Structure

- `decompiler/`: 反编译核心
  - `parser.py`: 解析对象块
  - `objects/`: V8 对象模型（BytecodeArray/FixedArray/SFI/String...）
  - `context.py`: 常量池、函数名、地址解析
  - `instruction.py`: 指令切分
  - `translator.py`: opcode -> 伪 JS
  - `cfg.py` + `structurer.py` + `statements.py`: CFG 与结构化输出
  - `postprocess.py`: level 3/4 的简化和结构恢复
  - `v8decompiler.py`: CLI 入口
- `v8patch/`: 构建 `v8asm` 的 patch/参考代码
- `checkversion/`: 独立版本检测小工具
- `tests/decomp_rounds/`: 真实回归流水线（新增）

## Decompile Levels (Current)

命令：`python3 decompiler/v8decompiler.py <disasm.txt> --level N [--runtime]`

- `level 1`: 线性指令视图（带 offset），用于核对 opcode 与跳转。
- `level 2`: CFG 结构化（`if/while`），保留低层细节。
- `level 3`: `level 2` + 保守表达式简化。
- `level 4`: `level 3` + 高层模式恢复（如 `for...of`、`+=`、部分 switch 模式）。

`--runtime` 会注入轻量 helper（`truthy/isNullish/isJSReceiver/...`）和上下文槽，方便直接运行伪代码。

## v8asm CLI

- 编译：`./v8asm asm input.js -o out.jsc`
- 反汇编：`./v8asm disasm out.jsc > out.txt`
- 版本：`./v8asm version`
- 编译参数：`./v8asm build-args`
- 版本哈希检测：`./v8asm checkversion file.jsc`

## Regression Workflow (Important)

目录：`tests/decomp_rounds`

- 用例：`tests/decomp_rounds/cases/*.js`
- 一键运行：`tests/decomp_rounds/run_round.sh`
- 报告：`tests/decomp_rounds/summary.md`
- 分析脚本：`tests/decomp_rounds/analyze_round.py`
- 版本元数据：summary 顶部会记录 `v8asm`、Node、Node V8、bytenode 版本。
  每个 case 也会输出 `*.checkversion.txt`，不要把不匹配的 bytenode 行当成
  对应 V8 版本验证。
- summary 表里的 `header_mismatch`/`ro_snapshot` 来自每个 case 的
  `*.checkversion.txt` 或 `*.disasm.err`。如果 bytenode 行还有
  `undefined_fallbacks` 且 `ro_snapshot=mismatch`，优先查 v8asm/Node
  embedder snapshot/RO heap 对象恢复，不要继续在 Python 层美化占位符。

流水线执行：

1. `v8asm asm` 编译 case
2. `bytenode` 编译 case（使用本机缓存路径）
3. `v8asm disasm`
4. `python decompiler/v8decompiler.py --level 4 --runtime`
5. 输出统计（`accu_lines/reg_refs/raw_goto/...`）

默认 bytenode 使用 `nvm use 24.7.0`。验证其他 V8 版本时应显式指定：

```bash
V8ASM_BIN=/path/to/v8/out/v8asm.12.9.x64.release/v8asm \
ROUND_NODE_VERSION=22.17.0 \
tests/decomp_rounds/run_round.sh
```

如果 summary 显示 Node V8 与 `v8asm_version` 不同，bytenode 路径只是
`--force-incompatible` 覆盖，不证明那个 V8 branch 已经匹配 bytenode。
`run_round.sh` 默认会使用 `V8ASM_BIN` 同目录下的 `snapshot_blob.bin`；
也可以用 `ROUND_SNAPSHOT_BLOB=/path/to/blob` 指定外部 snapshot。指定外部
snapshot 时，bytenode 的 `checkversion` 和 forced disasm 都会走
`--snapshot_blob ... --force-incompatible`，避免只在反汇编阶段加载 snapshot。

轻量版本矩阵：

```bash
tests/decomp_rounds/run_version_matrix.sh
```

它只用一个 case 检查本机可用的 `v8asm` 二进制和 nvm Node 版本：

- `v8asm asm` 自生成 cache 必须能 strict disasm + level-4 decompile。
- bytenode cache 先记录 `checkversion`；只有 Node V8 数字版本等于
  `v8asm version`，且 Node 与 `v8asm` 的 pointer compression 布局一致时，
  才尝试 `--force-incompatible`。
- bytenode 的 `checkversion` 会带 `--force-incompatible`，因此设置
  `VERSION_MATRIX_SNAPSHOT_BLOB=/path/to/blob` 时 header 对比会基于加载后的
  snapshot checksum。
- pointer compression 不匹配时不强跑 force，因为这会把不同对象布局的
  serializer 数据喂给 V8，容易在反序列化阶段崩溃。

## Known Issues (as of latest run)

- bytenode 行默认是 Node `24.7.0` / V8 `13.6.233.10-node.26` 产物。即使数字版本接近，仍要看
  `checkversion` 里的 `magic`、`flags_hash`、read-only snapshot checksum；不匹配时只能视为
  `--force-incompatible` 研究覆盖。
- Node `24.7.0` 的 nvm 二进制使用 `node_use_node_snapshot=true`，安装目录没有
  可直接传给 `v8asm --snapshot_blob` 的外部 `snapshot_blob.bin` 或
  `v8_context_snapshot.bin`。当前 bytenode 剩余的对象名缺失对应
  `read_only_snapshot_checksum` mismatch，需要 Node-aligned v8asm/Node snapshot
  恢复方向继续查。
- Node `22.17.0` 的 bytenode 对应 V8 `12.4.254.21-node.26`，并且是
  `v8_enable_pointer_compression=0`。普通 pointer-compression 版 V8 12.4
  不是这个 bytenode 的对应版本；要用
  `out/v8asm.12.4.node22.x64.release/v8asm`。
- `v8asm disasm` 默认拒绝不兼容 cached data；只有显式 `--force-incompatible` 时才启用 best-effort
  反汇编和对象打印保护。不要把缺失 print 当成 Python decompiler 问题。
- `level 4` 对复杂异常/async handler 路径仍有低层状态机残留（例如 `HOLE`、pending message、reject
  handler 片段）。
- 当前 round 的 `unknown` 和 `raw_goto` 应保持为 0；如果回升，优先看 translator opcode 覆盖或
  level-4 pipeline 顺序是否破坏了已有结构恢复。

## Recent High-Impact Fixes

- 修复了 `BytecodeArray` 指令解析遗漏（支持带 `S>` 前缀的行），恢复了关键分支与 return 指令。
- 为结构器增加了递归/重入防护，降低了结构化爆栈概率。
- 增加 `TestEqualStrict/TestGreaterThan/TestLessThan` 翻译。
- `level 4` 新增/增强：
  - `for...of` 恢复（支持嵌套场景）
  - `switch` 两分支模式恢复（`if (x===1) return ...; if (x===2) return ...; return ...`）
  - `+=` 归并（含 `+1`）
  - bound method call 恢复可进入简单二元表达式，例如
    `return (r3 + r4.call(r1))` -> `return (r3 + r1.sum())`
  - 删除已被高层表达式吸收的纯临时寄存器赋值，但保留 call/new 等 effectful 表达式
  - 文件级 level-4 后处理会用同函数内 `script_context[n] = create_closure(name)`
    和 `ensureDefined("Name")` 的局部证据，把部分 `context_slot[n]` 恢复成闭包名；
    不做跨函数全局替换，避免误改闭包变量或私有字段槽。

## Collaboration Notes for Next Session

- 优先通过 `tests/decomp_rounds/run_round.sh` 验证改动，不要只跑 `samples/`。
- 回归优先看：
  - `raw_goto` 是否回升（结构化退化）
  - bytenode 路径是否出现新的 `disasm failed`
- 改动优先保持“语义正确 > 可读性美化”。
- 若结构化失败，应保持有 fallback 输出，避免整个批处理中断。
