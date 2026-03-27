# V8 Bytecode SLEIGH (Experimental)

这个目录提供一个 **Ghidra SLEIGH 处理器语言原型**，用于分析 V8 Ignition bytecode。

当前目标：
- 在 Ghidra 里识别常见 V8 bytecode 指令
- 为后续反编译增强建立可迭代基础
- 与本仓库 `v8asm disasm` 输出联动

## Files

- `data/languages/v8bytecode.slaspec`: SLEIGH 指令定义（实验版，覆盖高频 opcode）
- `data/languages/v8bytecode.pspec`: processor spec
- `data/languages/v8bytecode.cspec`: compiler spec
- `data/languages/v8bytecode.ldefs`: language definition
- `tools/extract_bytecode_blob.py`: 从 `v8asm disasm` 文本提取原始 bytecode blob

## Quick Start

1. 生成 `.jsc` 与反汇编：

```bash
./v8asm asm input.js -o input.jsc
./v8asm disasm input.jsc > input.disasm.txt
```

2. 提取可导入的原始 bytecode：

```bash
python3 ghidra/v8-bytecode/tools/extract_bytecode_blob.py input.disasm.txt -o input.bytecode.bin
```

如果一个 `disasm.txt` 里包含多个 `BytecodeArray`，可以先列出 block：

```bash
python3 ghidra/v8-bytecode/tools/extract_bytecode_blob.py input.disasm.txt --list-blocks
```

再用 `-i/--block-index` 选择具体函数：

```bash
python3 ghidra/v8-bytecode/tools/extract_bytecode_blob.py input.disasm.txt -i 1 -o input.bytecode.bin
```

3. 在 Ghidra 中安装该语言（两种方式任选其一）：

方式 A（开发期，直接放 GHIDRA_HOME）：
- 将 `ghidra/v8-bytecode/data/languages/*` 复制到 `GHIDRA_HOME/Ghidra/Processors/V8Bytecode/data/languages/`
- 用 Ghidra 自带 sleigh 编译 `v8bytecode.slaspec` 生成 `v8bytecode.sla`

方式 B（作为扩展打包）：
- 以 Ghidra 扩展形式打包 `data/languages`，安装后重启 Ghidra

4. 导入 `input.bytecode.bin`（Raw Binary）时选择语言：
- `V8Bytecode:LE:32:default`

## Headless Validation

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

## Opcode Coverage (current)

已覆盖（高频）：
- load/store: `LdaZero/LdaSmi/LdaConstant/LdaGlobal/Ldar/Star*/Mov/...`
- property/call: `GetNamedProperty/CallProperty0/CallProperty1/CallProperty2/CallUndefinedReceiver*/CallRuntime`
- literals/context: `CreateArrayLiteral/CreateObjectLiteral/CreateClosure/CreateCatchContext/CreateFunctionContext/PushContext/PopContext`
- flow: `Jump/JumpLoop/JumpIf*`
  - `Jump/JumpLoop/JumpIf*` 已带基础 branch p-code，可在 Ghidra 中形成控制流边
  - `Wide/ExtraWide` 已补上 flow opcode 的显式解码（当前聚焦分支类）
- compare: `TestReferenceEqual/TestEqualStrict/TestGreaterThan/TestLessThan`
- misc: `SetPendingMessage/ReThrow/Return/GetIterator/ToString`

## Limitations

- 目前是 **实验版**：偏重高频指令与控制流，不保证完整/精确 p-code 语义。
- `Wide/ExtraWide` 目前优先覆盖 flow opcode；其余宽前缀指令仍需继续补全。
- 复杂异常路径、上下文槽、运行时调用语义仍需继续补全。

## Suggested Next Steps

- 完整建模寄存器/参数编码（含 `aN`/`rN` 与 short form）。
- 扩展 `Wide/ExtraWide` 到 load/store/call 家族。
- 细化 `JumpIfUndefinedOrNull` / `JumpIfJSReceiver` 的 p-code 条件语义。
- 按 Node/V8 版本拆分 language variant。
