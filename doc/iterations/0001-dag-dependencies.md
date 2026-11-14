# 迭代 0001 · feature 推导依赖（DAG）

> 状态：已交付 ｜ 2026-11-14
>
> 当前契约见 [../spec.md](../spec.md)；价值与目标见 [../value.md](../value.md) / [../goals.md](../goals.md)。

---

## 1. 为什么做

平铺推导把架构树压平了：

- 上层必须重新推导下层已经知道的事实。demo 里 `bsp.TUNNEL_BACKEND` 已经知道 ble/plb/uart，`ctl.SUPPORT_WIRELESS_TUNNEL` 仍要重新读 `board.has_ble_module`、`chip.pioc`、`board.has_uart_ble_adapter`。
- “上层依赖多个下层”只存在于链接图，不存在于推导里；strata 看到的是一组平铺的兄弟 feature。
- 同一条领域结论复制到 N 个使用点，任意一处漂移都不会被发现。

目标不是给 feature 加可见性，而是给推导加方向：

1. 叶子组件把 config 翻译成能力；
2. 上层只组合下层暴露的能力；
3. 方向写在 TOML 里，可评审、可静态查环、求值确定。

---

## 2. 改了什么

**TOML**

```toml
component = "ctl"
requires  = ["bsp"]

[[feature]]
name = "ctl.SUPPORT_WIRELESS_TUNNEL"
type = "bool"
```

- 组件身份从 CMake 参数移到 TOML 顶层 `component`。
- 组件依赖用顶层 `requires`；组件内先后用 `[[feature]].requires`。
- feature id 必须以所属组件 id 开头；组件图与 feature 图都必须无环。

**resolver**

```python
@feature("ctl.SUPPORT_WIRELESS_TUNNEL")
def support_wireless_tunnel(config, features):
    return config.product.wireless_debug and features.bsp.HAS_WIRELESS_TUNNEL
```

- 一参 resolver 只收 `config`；两参 resolver 收 `config` 与只读 `features` 视图。
- 视图支持 `features["bsp.X"]` 与 `features.bsp.X`（后者仅单点 id）。

**CMake**

```cmake
strata_project(SCHEMA ... PRESETS ...)
strata_add_component_path(.../components/ctl)
strata_add_component_path(.../components/bsp)
```

- `strata_add_component` → `strata_project`（一个构建只有一个 project）。
- 组件只传目录，名称与依赖都在 TOML。

**生成物**

- 仍是一个 CMake 视图、一个 C 头文件、一份清单；C/C++ 读取方式不变。
- 清单新增 `features.<id>.from` 与 `components.<id>.requires`；`by` 语义不变。

---

## 3. 设计决策

| 编号 | 决策 | 理由 | 否决后的后果 |
| --- | --- | --- | --- |
| D1 | 组件级 + 同组件 feature 级 `requires` | 模块内天然有“派生自派生”；否则只能复制谓词或拆组件 | 退回纯组件级；demo 的 `bsp.MAX_SESSIONS` 要复制判断 |
| D2 | 允许读整个传递 cone，不只直接邻居 | `requires` 只声明方向；A→B→C 已说明 C 在 A 下方 | 每个跨层读取都要补直接边，图更大 |
| D3 | cone 外/未声明 sibling 的读硬失败 | 否则顺序无定义，`requires` 退化成提示 | 改为惰性补算；环可能只在某个 preset 暴露 |
| D4 | 输出全局；不做可见性 / per-module header | C 预处理器对未定义宏的 `#if` 静默算 0，按 target 裁剪会制造“看着是关闭”的坑 | 需要按 target 生成头文件目录，重新引入 layer 的机械成本 |
| D5 | 求值顺序由声明图决定，不做惰性 | 失败前置、可静态查环、可解释 | 运行时发现依赖；环可能延迟暴露 |
| D6 | 不做 config 归属；config 仍全局可读 | 本次只解决 feature → feature 的方向 | 上层仍可能直接读底层 config；留给后续迭代 |
| D7 | 不做跨组件 feature 级边 | 一张跨组件图会与组件图重复；跨组件方向只认顶层 `requires` | 同一方向有两处声明，容易漂移 |

---

## 4. 实现落点

| 文件 | 作用 |
| --- | --- |
| `engine/graph.py` | Kahn 拓扑、稳定排序、传递闭包、环路径 |
| `engine/components.py` | TOML 解析、名称/前缀/图校验、resolver 签名 |
| `engine/resolve.py` | 两张图的求值顺序、`FeatureView`、`by` / `from` |
| `engine/emit.py` | 清单新增 `from` / `requires` |
| `engine/__init__.py` | `components` 改为目录列表 |
| `__main__.py` | `--component <dir>`，只传目录 |
| `cmake/strata.cmake` | `strata_project`、`strata_add_component_path`、包定位 |
| `demo/components/*` | 新 TOML、resolver 链 |
| `demo/CMakeLists.txt` | 新 API |
| `tests/test_dag.py` | 引擎级 DAG 用例 |
| `tests/test_cmake_integration.py` | CMake 集成用例 |
| `demo/tests/` | 四款预设与真实构建 |

---

## 5. demo

目标图：

```text
config -> bsp.TUNNEL_BACKEND -> bsp.HAS_WIRELESS_TUNNEL -> bsp.MAX_SESSIONS
                                      |                         |
                                      v                         v
                          ctl.SUPPORT_WIRELESS_TUNNEL -> ctl.MAX_TUNNEL_SESSIONS
```

- `bsp`：叶子组件；`HAS`、`MAX` 用 feature 级 `requires` 串起来。
- `ctl`：`requires = ["bsp"]`；`MAX` 同时读 sibling（`ctl.SUPPORT`）与 cone（`bsp.MAX`）。

| 预设 | backend | bsp.HAS | bsp.MAX | ctl.SUPPORT | ctl.MAX |
| --- | --- | --- | --- | --- | --- |
| `daplink_ble` | `ble` | true | 2 | true | 2 |
| `daplink_plb` | `plb` | true | 1 | true | 1 |
| `daplink_uart` | `uart_ble` | true | 1 | true | 1 |
| `daplink_wired` | `none` | false | 0 | false | 0 |

验收：

- `cd demo && python -m pytest -q` 全绿。
- 四款预设分别 configure/build/run，输出与上表一致。
- 清单里 `ctl.MAX_TUNNEL_SESSIONS.from` 含 `ctl.SUPPORT_WIRELESS_TUNNEL` 与 `bsp.MAX_SESSIONS`（wired 下只有前者）。
- `strata_features.h` 同时包含 `STRATA_FEATURE_BSP_*` 与 `STRATA_FEATURE_CTL_*` 五个宏。

---

## 6. 测试设计

用例分四层：引擎单测（契约、图、求值、视图、清单）、端到端（demo 四款预设）、CMake 集成（`strata_project`、路径接口、头文件、构建期读取）、确定性与回归。

下表是最小覆盖矩阵；实现中的 `test_dag.py` / `test_cmake_integration.py` 还包含若干变体。编号对应 [../spec.md](../spec.md) §8 的 C* / R*。

| 编号 | 覆盖 | 场景 | 期望 |
| --- | --- | --- | --- |
| T01 | C1, C7 | 叶子组件：只写 `component` | 值/视图正常；`from`、`requires` 为空 |
| T02 | C2 | 组件级 `requires` 直接依赖 | 上层 feature 由下层 feature 推导 |
| T03 | C2 | 传递 cone 读取（A→B→C，A 读 C） | 允许；值正确 |
| T04 | C6, R9 | 读 cone 外组件 | 失败；提示加顶层 `requires` |
| T05 | C6, R9 | 读同组件 sibling 但未声明 | 失败；提示加 feature 级 `requires` |
| T06 | C3 | 读同组件 sibling 且已声明 | 允许；值正确 |
| T07 | C3 | sibling 传递读取（F→G→H，F 读 H） | 允许；值正确 |
| T08 | R5 | feature 级 `requires` 跨组件 | 加载期失败；提示用组件级 |
| T09 | C6, R9 | 读未知 feature | 读取时失败；给最近邻建议 |
| T10 | C5, R7 | feature 级自指/环 | 加载期失败；含完整路径 |
| T11 | C5, R7 | 组件级自指/环 | 加载期失败；含完整路径 |
| T12 | R12 | 组件级 `requires` 引用未知组件 | 加载期失败 |
| T13 | R12 | 组件级/feature 级 `requires` 重复项 | 加载期失败 |
| T14 | R4 | feature 前缀与组件 id 不匹配 | 加载期失败 |
| T15 | R2, R3, R4 | 缺失/非法 `component`、非法 feature id | 加载期失败 |
| T16 | R3 | 两个目录声明同一个 `component` | 加载期失败，列出两个 TOML |
| T17 | C9 | 一参 resolver | 只收到 config，值正确 |
| T18 | C9 | 两参 resolver | 收到 config 与视图，值正确 |
| T19 | R10 | 0 个/3 个位置参数、`*args`、keyword-only | 加载期失败 |
| T20 | C8 | `from` 去重与首次读取顺序 | 清单顺序符合 |
| T21 | C4 | 打乱组件路径声明/TOML 条目/`requires` 顺序 | 产物逐字节一致 |
| T22 | C8 | 清单 `from` / `requires` 字段 | 值、顺序、空数组都正确 |
| T23 | C1 | CMake 集成：`strata_project` + 只传路径 | 成功；名称来自 TOML |
| T24 | C7 | 生成头文件包含中间 feature | `STRATA_FEATURE_BSP_HAS_WIRELESS_TUNNEL` 等在 |
| T25 | C10 | 构建期读中间 feature | `strata_get_feature` 成功 |
| T26 | — | 失败诊断形状 | `CMake Error at ...`、英文 ASCII、退出码 1 |
| T27 | R6 | 声明无 resolver / resolver 无声明 / 同组件重复 feature | 加载期失败 |
| T28 | R2 | `component` 写在 `[[feature]]` 之后 | 加载期失败（顶层缺失） |
| T29 | R8 | 先消费、后 `strata_add_component_path` | 生成失败或报未知 required 组件 |

**当前结果（2026-11-14）**：79 项自包含测试、14 项 demo/CMake 端到端测试，共 93 项通过。

---

## 7. 交付状态与后续

**已交付**：DAG 契约、求值、清单字段、CMake API、demo 四款预设、引擎与 CMake 集成测试。

**已知缺口 / 后续**：

1. **R8 的晚加组件**：第一次消费之后调用 `strata_add_component_path`，当前会被静默忽略（生成已完成，新目录没有进入图）。规格要求失败；`strata_add_component_path` 应检查 `STRATA_GENERATED` 并 `FATAL_ERROR`，同时补一条“晚加独立组件”的用例。
2. **T21 的测试有效性**：当前 `project()` fixture 每次复用同一个临时目录，T21 的两次 `project()` 实际指向同一个 root，比较恒等。实现本身确定（已用两个独立工程复现），但测试需要改成两个独立目录。
3. **`strata_project` 的 `PRESET` 参数**：规格与 README 都写“preset 不是参数”，实现仍接受 `PRESET`；应对齐为只读缓存变量。
4. **版本**：当前 `__version__` 仍是 `0.1.0`；若本次迭代作为 0.2.0 发布，需要升版。
5. **C 宏名碰撞**（R15）：`ctl.A_B` 与 `ctl.A.B` 仍可能撞成同一个宏，尚未加校验。
