# Ghidra SLEIGH 实验模块

`ghidra/v8-bytecode/` 提供一个 SLEIGH 处理器语言原型，用于分析 V8 Ignition bytecode。
以下命令从项目根目录执行。

> **状态**
>
> 当前 Ghidra 原型的反编译可读性和语义还原效果不如本仓库的 Python
> decompiler。该模块暂时停止开发，仅保留用于实验、验证和结果对比。

当前目标：
- 在 Ghidra 里识别常见 V8 bytecode 指令
- 为后续反编译增强建立可迭代基础
- 与本仓库 `v8asm disasm` 输出联动

## 文件

- `data/languages/v8bytecode.slaspec`: SLEIGH 指令定义（实验版，覆盖高频 opcode）
- `data/languages/v8bytecode.pspec`: processor spec
- `data/languages/v8bytecode.cspec`: compiler spec
- `data/languages/v8bytecode.ldefs`: language definition
- `tools/extract_bytecode_blob.py`: 从 `v8asm disasm` 文本提取原始 bytecode blob
- `tools/compare_decompilers.py`: 对同一 `BytecodeArray` 比较 Python 与 Ghidra 反编译结果
- `tools/compare_corpus.py`: 批量比较语料中的全部 `BytecodeArray`
- `ghidra_scripts/DumpV8Decompile.java`: headless listing/反编译导出脚本

## 基本使用

1. 生成 `.jsc` 与反汇编：

```bash
./v8asm asm input.js -o input.jsc
./v8asm disasm input.jsc > input.disasm.txt
```

2. 提取可导入的原始 bytecode：

```bash
uv run python ghidra/v8-bytecode/tools/extract_bytecode_blob.py input.disasm.txt -o input.bytecode.bin
```

如果一个 `disasm.txt` 里包含多个 `BytecodeArray`，可以先列出 block：

```bash
uv run python ghidra/v8-bytecode/tools/extract_bytecode_blob.py input.disasm.txt --list-blocks
```

再用 `-i/--block-index` 选择具体函数：

```bash
uv run python ghidra/v8-bytecode/tools/extract_bytecode_blob.py input.disasm.txt -i 1 -o input.bytecode.bin
```

3. 在 Ghidra 中安装该语言（两种方式任选其一）：

方式 A（开发期，直接放 GHIDRA_HOME）：
- 将 `ghidra/v8-bytecode/data/languages/*` 复制到 `GHIDRA_HOME/Ghidra/Processors/V8Bytecode/data/languages/`
- 用 Ghidra 自带 sleigh 编译 `v8bytecode.slaspec` 生成 `v8bytecode.sla`

方式 B（作为扩展打包）：
- 以 Ghidra 扩展形式打包 `data/languages`，安装后重启 Ghidra

4. 导入 `input.bytecode.bin`（Raw Binary）时选择语言：
- `V8Bytecode:LE:32:default`

## 无界面验证

可以直接用 Ghidra headless 跑导入、反汇编和反编译导出：

```bash
XDG_CONFIG_HOME=/tmp/ghidra-home/.config \
JAVA_HOME=/path/to/jdk \
$GHIDRA_HOME/support/sleigh \
ghidra/v8-bytecode/data/languages/v8bytecode.slaspec \
/tmp/v8bytecode.sla
```

把生成的 `v8bytecode.sla` 与 `data/languages/*` 同步到一个本地扩展目录后，可执行：

```bash
XDG_CONFIG_HOME=/tmp/ghidra-home/.config \
JAVA_HOME=/path/to/jdk \
$GHIDRA_HOME/support/analyzeHeadless /tmp gh-v8-demo \
  -import /tmp/input.bytecode.bin \
  -processor V8Bytecode:LE:32:default \
  -cspec default \
  -overwrite \
  -scriptPath ghidra/v8-bytecode/ghidra_scripts \
  -postScript DumpV8Decompile.java /tmp/out.txt \
  -deleteProject
```

导出的 `out.txt` 会同时包含 listing 和 decompile 结果。

## 对照 Python 反编译器

对比脚本接受 `.jsc` 或新版 disassembler 生成的结构化 JSON。它只读取
disassembler 的现有输出，不修改 disassembler，也不会写入 Ghidra 安装目录。

```bash
uv run python ghidra/v8-bytecode/tools/compare_decompilers.py \
  samples/main.d8.jsc \
  --function listSum \
  --ghidra-home "$GHIDRA_HOME" \
  --java-home "$JAVA_HOME" \
  -o /tmp/v8asm-compare-listSum
```

也可以直接输入结构化 JSON：

```bash
uv run python -m disassembler samples/main.d8.jsc --format json \
  > /tmp/main.disasm.json

uv run python ghidra/v8-bytecode/tools/compare_decompilers.py \
  /tmp/main.disasm.json \
  --function add \
  --ghidra-home "$GHIDRA_HOME" \
  --java-home "$JAVA_HOME" \
  -o /tmp/v8asm-compare-add
```

可以使用 `--bytecode-index N` 代替函数名。两者都不指定时，默认选择字节数
最多的 `BytecodeArray`。输出目录包含：

- `comparison.md`: 两边结果与输入元数据
- `python.js`: 手写 Python decompiler 的单函数输出
- `ghidra.c`: Ghidra decompiler 输出
- `ghidra-full.txt`: Ghidra listing 与完整反编译输出
- `comparison.diff`: 文本差异
- `ghidra-*.log` 和 `sleigh.log`: 编译、导入和反编译诊断

对于异常处理表和 generator/switch jump table，比较脚本会从结构化反汇编中
提取额外入口。Ghidra 输出会把主 CFG 之外的入口追加为独立函数，例如
`safeJson_handler_12` 或 `seq_switch_27`，避免静默丢失 catch/恢复路径。

## 语料对照

一次 Ghidra headless 进程可以比较目录中的所有 `.v8asm.jsc`：

```bash
uv run python ghidra/v8-bytecode/tools/compare_corpus.py \
  tests/decomp_rounds/out \
  --ghidra-home "$GHIDRA_HOME" \
  --java-home "$JAVA_HOME" \
  -o /tmp/v8asm-ghidra-corpus
```

总览位于 `/tmp/v8asm-ghidra-corpus/summary.md`。每个函数在 `results/`
下分别保存 `python.js`、`ghidra.c`、完整 listing 和两者的 diff。命令在任何
Ghidra 输出缺失、反编译失败或出现 bad instruction 时返回非零状态。

## 指令范围

已覆盖（高频）：
- load/store: `LdaZero/LdaSmi/LdaConstant/LdaGlobal/Ldar/Star*/Mov/...`
- arithmetic/compare: `Add/AddSmi/SubSmi/MulSmi/Inc/Test*`
- property/call: `Get/Set/Define*Property`、`Call*`、`Construct*`、`InvokeIntrinsic`、`CallRuntime`
- literals/context: `Create*Literal/CreateClosure/Create*Context/CreateRestParameter/PushContext/PopContext`
- flow: `Jump/JumpLoop/JumpIf*`、`SwitchOn*`、`Throw/ReThrow/Return`
  - `Jump/JumpLoop/JumpIf*` 已带基础 branch p-code，可在 Ghidra 中形成控制流边
  - `Wide/ExtraWide` 已覆盖 example2 中出现的高频 flow/load/store/call/literal opcode
- generator: `SwitchOnGeneratorState/SuspendGenerator/ResumeGenerator`
- misc: `SetPendingMessage/GetIterator/ToString`

## 限制

- 目前是 **实验版**：偏重高频指令与控制流，不保证完整/精确 p-code 语义。
- 当前 opcode 表按 V8 13.x 构建；V8 10/11/12 等旧版本需要独立 language variant。
- `Wide/ExtraWide` 仍只覆盖当前样例实际使用的指令，其他宽前缀指令需继续补全。
- Ghidra raw binary 无法直接解析 V8 constant pool，属性名/字符串等仍显示为索引；
  Python decompiler 在这方面通常更易读。
- 异常处理和 generator/switch 续体会作为额外入口函数导出，不会自动还原为
  原生 JavaScript `try/catch`、`async/await` 或 generator 语法。
- 复杂异常 CFG 仍可能出现 `Removing unreachable block` 警告。

## 后续实验方向

- 完整建模寄存器/参数编码（含 `aN`/`rN` 与 short form）。
- 扩展 `Wide/ExtraWide` 到 load/store/call 家族。
- 细化 `JumpIfUndefinedOrNull` / `JumpIfJSReceiver` 的 p-code 条件语义。
- 按 Node/V8 版本拆分 language variant。
