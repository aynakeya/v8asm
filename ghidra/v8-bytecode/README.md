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

3. 在 Ghidra 中安装该语言（两种方式任选其一）：

方式 A（开发期，直接放 GHIDRA_HOME）：
- 将 `ghidra/v8-bytecode/data/languages/*` 复制到 `GHIDRA_HOME/Ghidra/Processors/V8Bytecode/data/languages/`
- 用 Ghidra 自带 sleigh 编译 `v8bytecode.slaspec` 生成 `v8bytecode.sla`

方式 B（作为扩展打包）：
- 以 Ghidra 扩展形式打包 `data/languages`，安装后重启 Ghidra

4. 导入 `input.bytecode.bin`（Raw Binary）时选择语言：
- `V8Bytecode:LE:32:default`

## Opcode Coverage (current)

已覆盖（高频）：
- load/store: `LdaZero/LdaSmi/LdaConstant/LdaGlobal/Ldar/Star*/Mov/...`
- property/call: `GetNamedProperty/CallProperty0/CallProperty2/CallUndefinedReceiver*/CallRuntime`
- literals: `CreateArrayLiteral/CreateObjectLiteral/CreateClosure`
- flow: `Jump/JumpLoop/JumpIf*`
- compare: `TestReferenceEqual/TestEqualStrict/TestGreaterThan/TestLessThan`
- misc: `SetPendingMessage/ReThrow/Return/GetIterator/ToString`

## Limitations

- 目前是 **实验版**：偏重指令识别，不保证完整/精确 p-code 语义。
- V8 存在 `Wide/ExtraWide` 与版本差异，本规范暂未完整处理。
- 复杂异常路径、上下文槽、运行时调用语义仍需继续补全。

## Suggested Next Steps

- 为 `Jump/JumpIf` 增加精确分支 p-code。
- 完整建模寄存器/参数编码（含 `aN`/`rN` 与 short form）。
- 增加 `Wide/ExtraWide` 解码支持。
- 按 Node/V8 版本拆分 language variant。
