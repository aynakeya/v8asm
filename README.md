# v8asm

面向 V8 cached bytecode（`.jsc`）的离线反汇编与 JavaScript 反编译工具集。

Python `disassembler` 直接解析缓存数据、对象图和 Ignition 指令，无需启动 V8；
`decompiler` 消费结构化 JSON，恢复函数、闭包和控制流。目标是忠实保留程序逻辑，
不是猜测业务含义或自动解混淆。项目仍在开发，输出是便于审计的 JavaScript 风格
伪代码，不保证任意输入都能还原成可直接执行的源码。

## 快速开始

在仓库根目录使用 uv 创建 Python 环境：

```bash
uv sync --locked
uv run python -m disassembler samples/main.d8.jsc --format json > /tmp/main.disasm.json
uv run python -m decompiler /tmp/main.disasm.json
```

自定义 Node/Electron 缓存可能需要精确版本和匹配的 snapshot：

```bash
uv run python -m disassembler input.jsc \
  --version 13.4.114.21 --snapshot-blob v8_context_snapshot.bin \
  --format json > /tmp/input.disasm.json
uv run python -m decompiler /tmp/input.disasm.json > /tmp/input.decompiled.js
```

snapshot 按 read-only checksum 匹配，不能只看文件名。版本、对象布局不兼容或缺少
snapshot 中的字符串时，工具会报错或保留未解析引用，不会猜测内容。

## 项目组成

- `disassembler/`：离线解析器、源码生成的版本 profile、应用缓存捕获脚本。
- `decompiler/`：指令翻译、CFG、闭包及表达式恢复。
- `checkversion/`：Python 多进程版本哈希搜索。
- `v8patch/`：原生 V8 对照工具的版本补丁。
- `tests/`：行为测试、缓存 fixture 与按需运行的版本矩阵。
- `ghidra/`：暂停开发的 SLEIGH 实验模块。

## 文档

使用方法、开发约定、测试和研究资料统一放在 **[note/](note/README.md)**。

- [反汇编](note/python-disassembler.md) / [反编译](note/decompiler.md)
- [uv 与原生构建环境](note/environment-and-build.md)
- [JS 语义 fixture](note/semantic-fixtures.md) / [验证与版本矩阵](note/validation.md)
- [开发约定](note/development.md) / [待办事项](note/TODO.md)
