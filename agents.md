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

流水线执行：

1. `v8asm asm` 编译 case
2. `bytenode` 编译 case（使用本机缓存路径）
3. `v8asm disasm`
4. `python decompiler/v8decompiler.py --level 4 --runtime`
5. 输出统计（`accu_lines/reg_refs/raw_goto/...`）

## Known Issues (as of latest run)

- 某些 bytenode 产物（尤其含 `try/catch` 或复杂 case）在 `v8asm disasm` 会出现段错误，这属于 `v8asm` 侧稳定性问题，不是 Python 反编译器崩溃。
- `level 4` 对复杂异常路径仍有低层状态机残留（例如 `HOLE`、部分上下文寄存器）。
- 复杂对象字面量/高级语法仍可能出现 `// raw line` 注释回退，需要继续补 opcode。

## Recent High-Impact Fixes

- 修复了 `BytecodeArray` 指令解析遗漏（支持带 `S>` 前缀的行），恢复了关键分支与 return 指令。
- 为结构器增加了递归/重入防护，降低了结构化爆栈概率。
- 增加 `TestEqualStrict/TestGreaterThan/TestLessThan` 翻译。
- `level 4` 新增/增强：
  - `for...of` 恢复（支持嵌套场景）
  - `switch` 两分支模式恢复（`if (x===1) return ...; if (x===2) return ...; return ...`）
  - `+=` 归并（含 `+1`）

## Collaboration Notes for Next Session

- 优先通过 `tests/decomp_rounds/run_round.sh` 验证改动，不要只跑 `samples/`。
- 回归优先看：
  - `raw_goto` 是否回升（结构化退化）
  - bytenode 路径是否出现新的 `disasm failed`
- 改动优先保持“语义正确 > 可读性美化”。
- 若结构化失败，应保持有 fallback 输出，避免整个批处理中断。
