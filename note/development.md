# 开发约定

核心目标是改进 Python decompiler 的忠实语义恢复。字符串解混淆、业务对象命名与
用途分析不进入恢复流程；不能为了减少寄存器或让输出好看而改变求值顺序。

## 日常工作

- 使用 `uv sync --locked` 和 `uv run python -m ...`，Python 工具仅依赖标准库。
- 先读相关实现与已有测试，做最小修改；不为局部问题设计完整发布流程。
- 优先改进常用 if/else、循环、短路、提前返回及常见异常路径，再扩展较少使用的 JS
  特性。已复现的语义错误及时修复，但不为穷举边缘情况长期搁置主要恢复能力。
- 优先用真实 `.js`/`.jsc` fixture 复现，比较返回值、异常、receiver 与副作用顺序。
- 小修改只跑相关测试；已通过且相关代码没有变化的检查不重复执行。
- 修改共享后处理、闭包或 CFG 时，再使用已有多版本 cache 做轻量回归。
- 修改 profile、serializer、snapshot 或原生 patch 时，按影响选择 Node/Electron
  matrix；发布或声明完整兼容时才做完整矩阵。
- 不并行执行多个重型任务，不重建与改动无关的 V8 版本。
- 未证明的类型、控制流与引用保留低层形式或诊断；不吞错误、不伪造恢复结果。
- 代码质量整理与能力扩展分开：保留公开接口、已有恢复规则和执行顺序，复用现有行为
  测试；纯重构可对照同批 fixture 的前后输出，不能通过删功能或放宽断言获得通过。
- 不使用正则名称形状猜测 class 属性名，不把所有 `super` 属性读取当作方法调用。

测试入口与范围见[验证方法](validation.md)，语言特性覆盖见
[语义 fixture](semantic-fixtures.md)。

## 原生构建的固定约束

- 官方 checkout 与环境入口见[环境文档](environment-and-build.md)。
- 调用 V8 工具前加载 `start_env.md`；切换精确 tag 后执行
  `gclient sync --with_branch_heads --with_tags`，再 `git apply --3way --recount`。
- 构建显式使用 `autoninja -j10`，不能自动占满 CPU，也不能擅自调整并发。
- 不使用 `gclient sync -D`，不删除既有 `out/`、编译缓存或下载缓存。
- binary 的版本和 GN 参数以它自己的 `version`、`build-args` 为准。
- bin cache 只保留该构建生成的 snapshot；应用或 Electron snapshot 必须显式传入。

## 文档规则

- 根 `README.md` 只作项目介绍与快速入口，其他维护文档全部放在 `note/`。
- 按主题更新，不新增逐日实验日志或在各模块重复维护 README。
- 删除已被替代的操作说明和历史统计；待办只写未完成的工作。
- 原始研究稿单独标明历史背景，不能作为当前构建或验证依据。
- 自动生成的测试报告留在忽略的输出目录，不提交为长期文档。
- 技术标识符保留英文，说明正文使用中文。
