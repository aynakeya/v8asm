# 可复用的生成资产

生成与验证分开：日常只更新修改到的样例，不自动下载运行时、不编译 V8、不启动完整矩阵。
所有命令在项目根目录执行。Python 使用 uv，Node 可由 nvm 切换，也可直接传 executable。

## JavaScript 行为样例

固定入口：`tests/generate_semantic_fixtures.py`。
配方和生成记录：`tests/semantic_fixtures/manifest.json`。

清单定义精确 Node/V8 组合、编译参数、文件后缀和各 runtime 的样例范围。生成器先
读取 `process.versions`，不匹配就退出，不能用当前 Node 给其他版本写 cache。
`NODE_OPTIONS` 非空时拒绝生成，避免未记录的启动配置混入；此时先取消该变量。

```bash
nvm use 24.7.0
uv run python tests/generate_semantic_fixtures.py conversion-boundaries iterable-spread

# 使用已有 runtime，不改变当前 shell 的 Node。
uv run python tests/generate_semantic_fixtures.py \
  --node "$HOME/.nvm/versions/node/v20.20.2/bin/node" \
  conversion-boundaries iterable-spread

# 只有迁移整个 runtime 的样例时才显式使用 --all。
uv run python tests/generate_semantic_fixtures.py --all
```

依次选择 Node 18.20.8、20.20.2、22.17.0、24.7.0，即可重建本轮两个样例的四版本
cache；没有额外编译并行度，也不要求安装 bytenode。生成 `.jsc` 使用 `vm.Script`
和 `--no-lazy`，不会执行 fixture 源码。

每次成功生成会更新对应 artifact 的源码/cache SHA-256、实际 Node/V8 版本、平台、
架构和编译参数。行为测试验证已记录的校验值，并用实际完整 V8 版本选择 profile。
V8 cache 的字节可能随进程或编译环境变化，因此这些哈希是产物溯源和过期检测，不是
跨机器逐字节可重现的承诺。正确性仍由源码与恢复代码的可观察行为比较决定。

新增样例的最短路径：添加 `.js` 和行为断言；默认 Node 24 自动包含新文件；需覆盖旧版
时把名称加入该 runtime 的 `fixtures` 列表，再选择相应 Node 生成。语料范围见
[语义 fixture](semantic-fixtures.md)。不要手工修改 `.jsc` 或伪造 `artifacts` 记录。

## V8 Profile

标准 profile 继续由同一个生成器读取精确 V8 tag，不切换 checkout、不改构建缓存：

```bash
uv run python -m disassembler.generate_profiles \
  --v8-repo /path/to/v8 --output-dir disassembler/profiles
```

embedder root 布局的源码来源固定在 `generate_profiles.py` 的 `ROOT_LAYOUT_SOURCES`。
当前 `11.3.244.8-node.38` 对应 [Node 官方 v20.20.2 源码](https://github.com/nodejs/node/tree/v20.20.2/deps/v8)。
有该 tag 的本地 Node Git 仓库时：

```bash
uv run python -m disassembler.generate_profiles \
  --v8-repo /path/to/node \
  --root-layout-version 11.3.244.8-node.38 \
  --output-dir disassembler/profiles
```

也可以读取同版本源码包中解压出的 `deps/v8`：

```bash
uv run python -m disassembler.generate_profiles \
  --v8-source /path/to/node-v20.20.2/deps/v8 \
  --root-layout-version 11.3.244.8-node.38 \
  --output-dir disassembler/profiles
```

此路径读取 `heap-symbols.h`、`accessors.h`、`roots.h`、`static-roots.h`。输出位于
`disassembler/profiles/root_layouts/`，包含源码仓库/revision、四个文件的 SHA-256，
以及源码解析得到的 root 名称、字符串、静态地址和 map。需要本机 C/C++ 预处理器。
使用源码目录时必须由调用者确认其来源；记录的哈希可与已提交产物比较，生成器不把
目录名字当成版本证明。修改来源或生成规则后重新生成，不直接编辑 layout JSON。

root 变体只补充这一组元数据，不宣称整个 Node/Electron 的 flags、serializer 和
对象布局都与标准 V8 相同。必须用真实 runtime cache 验证。运行时显式使用完整版本：

```bash
uv run python -m disassembler input.jsc \
  --version 11.3.244.8-node.38 --format json > input.disasm.json
```

cache 的数字版本哈希不能区分这种源码回移，不能自动猜测偏移。JSON 中
`metadata.v8_version` 表示基础布局，`metadata.root_layout_version` 表示选中的 root 布局。

## 完整应用诊断

`tests/run_application_fixture.py` 固定了 Taskboard 的生成和对比流程，记录实际
runtime、编译参数、源码/cache 哈希、snapshot 元数据、完整和隔离场景的结果。
它使用同一 executable 编译与执行，不把源代码拼回反编译结果，也不依赖原生 v8asm。
匹配 Electron snapshot 的命令和未支持特性见 [Taskboard 说明](application-fixture.md)。
运行产物放在忽略目录 `tests/decomp_rounds/out/`，不把大份诊断输出混入维护文档。
