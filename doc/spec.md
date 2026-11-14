# strata · 规格与约束

> 状态：v1.1 ｜ 2026-11-14 ｜ 当前行为契约
>
> 本文描述系统**现在必须怎样**。为什么这么设计见 [value.md](value.md) / [goals.md](goals.md)；某个改动怎么来的见 [iterations/](iterations/README.md)。
>
> 规范用语：**必须** = 实现必须满足；**不得** = 禁止；**应当** = 推荐；**可以** = 可选。

---

## 1. 总览

- 配置项 → feature 的推导，以及 feature → feature 的声明式 DAG，由一次运行完成。
- `requires` 只声明**先后方向**，不提供可见性控制；所有 feature 仍然全局生成、全局可读。
- 求值顺序由声明的图决定；同层按 id 字典序；环在加载期失败。
- 生成物保持全局：一个 CMake 视图、一个 C 头文件、一份清单；没有 per-module header。

---

## 2. TOML 契约

### 2.1 组件声明

```toml
# components/ctl/strata_features.toml
component = "ctl"
requires  = ["bsp"]

[[feature]]
name = "ctl.SUPPORT_WIRELESS_TUNNEL"
type = "bool"
```

规则：

- `component`：必填，顶层字符串；组件身份只在这里声明。
- `requires`：可选，顶层字符串数组；每一项是本次构建里已加入的组件 id。
- `component` 和 `requires` 必须写在文件顶部、**任何表头之前**。TOML 的键值对属于最近一个表头；写在 `[[feature]]` 表里的 `requires` 是 feature 级，写在 `[meta]` 等其他表里的会被忽略。
- 组件 id 必须匹配 `[A-Za-z_][A-Za-z0-9_]*`，全局唯一，不含点或空白。
- 组件级 `requires` 不得未知、自指、重复；组件图必须无环。

### 2.2 feature 声明

```toml
[[feature]]
name = "bsp.TUNNEL_BACKEND"
type = "string"

[[feature]]
name = "bsp.HAS_WIRELESS_TUNNEL"
type = "bool"
requires = ["bsp.TUNNEL_BACKEND"]

[[feature]]
name = "bsp.MAX_SESSIONS"
type = "int"
requires = ["bsp.HAS_WIRELESS_TUNNEL", "bsp.TUNNEL_BACKEND"]
```

规则：

- `name`：必填，完整 feature id；格式为 `<component>.<segment>(.<segment>)*`，每段匹配 `[A-Za-z_][A-Za-z0-9_]*`，不得含空白；前缀必须等于所属组件 id。
- `type`：必填，`bool` / `int` / `float` / `string`。
- `requires`：可选，字符串数组；每一项是**同一组件**的完整 feature id。
- 不得跨组件、未知、自指、重复；每个组件的 feature 图必须无环。
- 被引用的 feature 可以声明在之前或之后；图负责排序。
- 每个 feature 恰好一条声明、一个 resolver、一个 owner。
- 同组件内读取另一个 feature 时，必须能通过 feature 级 `requires` 的传递闭包到达它。

### 2.3 校验顺序

多个错误同时存在时，按以下顺序报告；测试不应依赖未列出的顺序：

1. schema 加载与校验。
2. preset 加载与校验。
3. 组件目录、声明文件、resolver 文件存在。
4. 每个 TOML 的顶层 `component` 存在、类型合法、组件 id 合法；组件 id 唯一。
5. 顶层 `requires` 类型、未知组件、自指、重复。
6. `[[feature]]` 形状；feature id 格式与前缀、类型、重复；声明与 resolver 一一对应。
7. resolver 签名（一参或两参）。
8. 组件图无环。
9. feature 级 `requires` 形状；同组件、未知、自指、重复；每个组件的 feature 图无环。
10. 求值。

前 1–9 步都在**任何 preset 值被求值之前**完成。resolver 的 Python 代码在步骤 3–7 之间被导入，因此导入期异常仍按现有方式报在 resolver 文件上。

---

## 3. 求值

### 3.1 两张图

- 组件级 `requires` A→B：A 依赖 B；求值时 B 先于 A。
- feature 级 `requires` F→G：F 依赖 G；求值时 G 先于 F。
- 排序时使用依赖边的反向（求值边）：Kahn 拓扑，入度为 0 表示没有未完成的依赖；同层按组件 id / feature id 字典序。
- 有环则在加载期失败，并给出完整路径。

### 3.2 可读集合

对组件 C 中的 feature F：

```text
cone(C)     = C 的组件级 requires 传递闭包，不含 C
siblings(F) = F 的 feature 级 requires 传递闭包，限定在 C 内，不含 F
allowed(F)  = { X | owner(X) ∈ cone(C) } ∪ siblings(F)
```

- `owner(X)` 是声明 X 的组件。
- F 可以读 `allowed(F)` 里的任何 feature；cone 内的读取不需要逐条列在 `requires` 里。
- F 读同组件 sibling，必须能通过 feature 级 `requires` 直接或传递到达。
- F 不得读：自己、上层组件、cone 外组件、未在 sibling 闭包里的同组件 feature、未声明的 feature。
- 越界读在读取时硬失败，错误要同时指出读取方和被读取方。

### 3.3 求值顺序

```text
for C in component_topo_order:              # 依赖在前，同层按 id
    for F in feature_topo_order(C):         # 依赖在前，同层按 feature id
        view  = FeatureView(已求值, cone(C), siblings(F))
        value = resolver(config_view, view) # 一参 resolver 只传 config
        记录 by / from，校验类型，写入已求值
```

- 所有 feature 都会被求值并生成，即使没有人读。
- `from`：实际读到的 feature，首次读取顺序、去重。
- `by`：实际读到的 config，首次读取顺序、去重。

### 3.4 resolver 签名

- `def f(config)` 或 `def f(config, features)`。
- 恰好 1 或 2 个可按位置传入的参数；不支持 `*args` / `**kwargs` / keyword-only 第二参数。
- `features` 是只读视图：
  - `features["bsp.TUNNEL_BACKEND"]` 始终可用。
  - `features.bsp.TUNNEL_BACKEND` 仅在 feature id 恰好一个点时可用；多段后缀用下标访问。
  - 每次读取记入 `from`。

示例：

```python
@feature("ctl.SUPPORT_WIRELESS_TUNNEL")
def support_wireless_tunnel(config, features):
    return config.product.wireless_debug and features.bsp.HAS_WIRELESS_TUNNEL


@feature("ctl.MAX_TUNNEL_SESSIONS")
def max_tunnel_sessions(config, features):
    if not features.ctl.SUPPORT_WIRELESS_TUNNEL:
        return 0
    return features["bsp.MAX_SESSIONS"]
```

---

## 4. 生成物

- CMake 视图：`set(STRATA_FEATURE_<id> <value>)`，包含所有 feature，按 id 排序。
- C 头文件：一个 `strata_features.h`，`#define STRATA_FEATURE_<ID> <value>`，包含所有 feature，按 id 排序；宏名大写、点替换为下划线。
- 清单包含两个与依赖相关的字段：
  - `features.<id>.from`：实际读到的 feature，`[]` 表示没有。
  - `components.<id>.requires`：组件级 `requires`，字典序，`[]` 表示没有。
- `by` 记录 config 读取；清单还包含 `engine`、`preset`、`config`、`schema`、`inputs` 等字段。

JSON 节选：

```json
{
  "features": {
    "ctl.SUPPORT_WIRELESS_TUNNEL": {
      "value": true,
      "type": "bool",
      "owner": "ctl",
      "by": ["product.wireless_debug"],
      "from": ["bsp.HAS_WIRELESS_TUNNEL"]
    }
  },
  "components": {
    "ctl": {
      "features": ["ctl.MAX_TUNNEL_SESSIONS", "ctl.SUPPORT_WIRELESS_TUNNEL"],
      "requires": ["bsp"]
    }
  }
}
```

- 确定性：相同输入逐字节一致；组件路径声明顺序、TOML 条目顺序、`requires` 条目顺序不影响产物。
- 依赖关系不写进 CMake 视图或 C 头文件；只在 TOML 和清单里。

---

## 5. CMake

| 函数 | 签名 | 行为 |
| --- | --- | --- |
| `strata_project` | `(SCHEMA <dir> PRESETS <dir> [OUT <dir>])` | 声明唯一的 project：schema 与 preset 目录 |
| `strata_add_component_path` | `(<directory>)` | 加入组件目录；组件名来自 TOML 的 `component` |
| `strata_link_resolves` | `(<target>)` | 让 target 看到全部 feature |
| `strata_get_feature` | `(<feature-id> <out-var>)` | 读任意 feature，包括中间量 |
| `strata_get_config` | `(<config-id> <out-var>)` | 读原始 config 项（逃生舱） |

```cmake
strata_project(
  SCHEMA  ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
)

strata_add_component_path(${CMAKE_CURRENT_SOURCE_DIR}/components/ctl)
strata_add_component_path(${CMAKE_CURRENT_SOURCE_DIR}/components/bsp)

strata_get_feature("bsp.TUNNEL_BACKEND" backend)

add_executable(firmware
  src/ctlp.c
  bsp/tunnel_${backend}.c
)
strata_link_resolves(firmware)
```

- CMake 只接收目录；组件身份和 `requires` 都在 TOML。
- 一个构建只有一个 project；`strata_add_component_path` 可以多次调用，因为有多个组件。
- 组件路径声明顺序不影响求值或产物；所有 `strata_add_component_path` 必须在第一次消费之前完成。生成延迟到第一次消费。
- 构建是集成者，可以读任意 feature，不在推导图里。
- 内部 CLI `strata generate --component <dir>` 也只传目录。

---

## 6. C/C++

```c
#include "strata_features.h"

int main(void)
{
#if STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL
    tunnel_start(STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS);
#else
    tunnel_start(0);
#endif
    return 0;
}
```

- 一个头文件、一个命名空间；所有 feature（包括中间量）都定义。
- feature 是否由别的 feature 推导而来，对 C/C++ 完全透明；值就是值。
- 没有 per-module header，没有按 target 裁剪，没有额外的 include 约定。
- 不做 C 侧隔离的原因：未定义宏在 `#if` 里**静默算 0**，不是编译错误；靠“不定义宏”做可见性会制造“看着是关闭”的坑。按 target 生成头文件目录会把 layer 的机械成本重新引进来。

---

## 7. 诊断

全部英文、纯 ASCII、CMake 同形、正文两空格缩进。CLI 失败返回 1；CMake 侧 `FATAL_ERROR`。

| 场景 | 正文要点 |
| --- | --- |
| 缺失 `component` | `Component declaration has no "component" name.` |
| 重复组件 | `Component "ctl" is declared twice: <file1>, <file2>.` |
| 未知 `requires` | `Component "ctl" requires "bsp", which is not declared.` |
| 组件环 | `Component dependency cycle: ctl -> tunnel -> ctl.` |
| feature 环 | `Feature dependency cycle: ctl.A -> ctl.B -> ctl.A.` |
| 未知 feature | `Unknown feature "bsp.MISSING".` |
| feature 级跨组件 | `Feature "ctl.X" requires "bsp.Y"; feature-level requires may reference only features of the same component.` |
| feature 前缀不匹配 | `Feature "bsp.X" is declared by component "ctl"; feature ids must start with "ctl.".` |
| 读 cone 外 | `Feature "ctl.X" reads "ui.Y", but component "ctl" does not depend on "ui".` |
| 读未声明 sibling | `Feature "ctl.X" reads "ctl.Y", but "ctl.X" does not require "ctl.Y".` |
| resolver 参数错 | `Resolver for "ctl.X" must take (config) or (config, features).` |

- 契约、图、名称、签名错误在求值前失败；越界读、未知读在读取时失败。
- 类型不符、resolver 抛异常使用同一套诊断；都发生在求值期。
- 未执行分支里的越界读不保证被发现；这是动态读取的固有限制（R16）。

---

## 8. 能力与约束

### 8.1 能力

| 编号 | 能力 | 行为 |
| --- | --- | --- |
| C1 | 组件声明内聚 | TOML 顶层 `component` 声明身份；`strata_add_component_path(<dir>)` 只传目录 |
| C2 | 组件间多步推导 | 顶层 `requires` 形成组件 DAG；上层可读 cone 内 feature |
| C3 | 组件内链式推导 | feature 级 `requires` 形成组件内 DAG；可读 sibling 闭包 |
| C4 | 确定性求值 | 稳定拓扑，依赖在前，同层按 id / feature id 字典序 |
| C5 | 静态环检测 | 两张图有环，加载期失败并给完整路径 |
| C6 | 越界读拦截 | cone 外、未声明 sibling、未知 feature，读取时失败 |
| C7 | 全局输出 | 一个 CMake 视图、一个 C 头文件，所有 feature 可见 |
| C8 | 清单可追溯 | `features.*.from`、`components.*.requires`；`by` 记录 config |
| C9 | resolver 两种签名 | 一参只给 config；两参给 config + view |
| C10 | 构建期读取 | `strata_get_feature` 可读任意 feature，含中间量 |

### 8.2 约束

| 编号 | 类型 | 约束 | 违反时 |
| --- | --- | --- | --- |
| R1 | 设计原则 | `requires` 只定先后，不做可见性；feature 仍全局 | 不属于错误；不存在“越权” |
| R2 | 硬约束 | `component` 必填、顶层、任何表头之前 | 加载失败 |
| R3 | 硬约束 | 组件 id 合法且全局唯一 | 加载失败 |
| R4 | 硬约束 | feature id 合法，前缀 = 组件 id | 加载失败 |
| R5 | 硬约束 | feature 级 `requires` 只能同组件 | 加载失败 |
| R6 | 硬约束 | 每个 feature 一声明、一 resolver、一 owner | 加载失败 |
| R7 | 硬约束 | 组件图与 feature 图无环 | 加载失败，给路径 |
| R8 | 硬约束 | 所有 `strata_add_component_path` 在第一次消费前 | 生成失败/图不完整 |
| R9 | 硬约束 | 读只能在 cone ∪ sibling 闭包内 | 读取时失败 |
| R10 | 硬约束 | resolver 1/2 个可按位置传入的参数 | 加载失败 |
| R11 | 约定 | resolver 必须是纯函数 | 不检查；结果不确定 |
| R12 | 硬约束 | 组件级 `requires` 只能引用已加入组件，不得未知/自指/重复 | 加载失败 |
| R13 | 范围外 | config 全局可读，不做 config 归属 | 无此行为 |
| R14 | 范围外 | 不做 per-module header、惰性求值、自动推断 | 无此行为 |
| R15 | 已知限制 | C 宏名碰撞未校验 | 可能同名宏：`ctl.A_B` 与 `ctl.A.B` 都映射为 `STRATA_FEATURE_CTL_A_B` |
| R16 | 已知限制 | 未执行分支的越界读不可静态证明 | 可能延迟暴露：加载期查不到，执行到才报 |

类型说明：**硬约束** = 必须校验并有用例；**约定** = 文档要求但不自动检查；**范围外** = 本规格不提供；**已知限制** = 接受并记录。R13/R14 不提供对应行为，R15/R16 不进入用例矩阵。
