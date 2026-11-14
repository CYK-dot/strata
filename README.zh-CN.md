# strata

简体中文 | [English](README.md)

[![CI](https://github.com/CYK-dot/strata/actions/workflows/ci.yml/badge.svg)](https://github.com/CYK-dot/strata/actions/workflows/ci.yml)

## 问题

一套源码要服务多款产品——多颗芯片、多个档位、多种部署——每次构建都得决定软件能做什么。最直接的做法是在需要的地方直接读那些事实：源码里 `#ifdef`，CMake 里 `if()`。只有两个事实时没问题；一旦多起来：

- 判断条件随事实的数量与组合一起膨胀，同一条决定还会被复制到每一个需要它的地方；
- 代码开始说配置的词汇，于是新增一颗芯片、一个客户档位，就要去改那些本不该认识这些词的代码；
- 构建与源码各判各的，没有任何东西保证两边一致；
- 没人能回答「这次构建为什么开着它」，除非把两边都读一遍。

## 理念

配置项之上的一切都不该直接读它们，一切该读推导出来的东西。目标的事实与软件的能力是两套词汇，中间的推导只有一跳——这条推导就该自成一独立的一层，只写一次，可评审、可测试、可解释。而一项能力可以建立在别的能力之上，所以这一层是一张图，不是一张清单。

## strata 是什么

strata 就是这一层。**配置项**是声明出来的、关于目标或产品的事实——板上装了什么硬件、芯片提供什么、档位承诺什么。**feature** 是软件能做什么：一个带名字、带类型的值，构建与代码都读它。每个组件声明它对外暴露的 feature，并为每一个写出求解函数——从配置项推导，或从它用 `requires` 声明的那些组件的 feature 推导。这些声明构成一张有向图；strata 按确定的顺序求值，产出一份 CMake 文件、一个 C 头文件，以及记录每条推导的清单。两侧读的是同一批值，构建与源码因此不会各说各话；feature id 自带归属组件前缀（控制面用 `ctl.`，板级支持用 `bsp.`），每个值都写明它出自哪个组件。

硬件是最常见的第一个场景——几颗不同的芯片可以提供同一项能力——但 strata 里没有任何东西是硬件专属的。任何有多个答案的配置，都适用同一套形状。

一套源码要服务多套配置时，它划算；单目标、单开关时，它不划算——CMake 的 `option()` 更便宜。

## 安装

strata 就住进它服务的那个工程里，所以推荐用 git submodule 引入：每个工程在自己的历史里钉住它构建时用的版本。

```sh
cd your-project
git submodule add https://github.com/CYK-dot/strata.git strata
git commit -m "add strata"
```

克隆时带上子模块，或之后再拉：

```sh
git clone --recurse-submodules <your-project>   # 克隆时
git submodule update --init --recursive        # 普通克隆之后
git submodule update --remote strata           # 升到更新的 strata
```

它落在工程根目录下：

```
your-project/
├── strata/                 子模块
├── configs/                配置项与预设
├── components/             feature 及其推导函数
└── CMakeLists.txt
```

依赖：

- CMake 3.20 及以上
- Python 3.11 及以上，仅用标准库。它由 CMake 在 configure 阶段调用，使用者不需要自己执行。

## 使用

示例工程是一台 USB 调试探针。它的固件可以打开一条*无线调试隧道*——通过 BLE 而不是线缆把调试通道送到目标板——能不能打开，取决于装了什么硬件、产品档位是什么。

产品在配置时选，不写在构建文件里，因此同一份 `CMakeLists.txt` 能构建所有产品：

```sh
cmake -B build/ble -DSTRATA_PRESET=daplink_ble
```

预设是 presets 目录里的一个文件，给一款产品定下全部配置项的取值；`daplink_ble` 就是焊了 BLE 模组的那台探针。

在 `CMakeLists.txt` 靠上的位置启用一次：

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

strata_project(
  SCHEMA  ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
)

strata_add_component_path(${CMAKE_CURRENT_SOURCE_DIR}/components/ctl)
strata_add_component_path(${CMAKE_CURRENT_SOURCE_DIR}/components/bsp)

# 由构建决定编哪一套 BSP 实现
strata_get_feature("bsp.TUNNEL_BACKEND" backend)

add_executable(firmware
  src/ctlp.c
  bsp/tunnel_${backend}.c
)
strata_link_resolves(firmware)   # 订阅后，全部 feature 对这个目标可见
```

`backend` 的取值是 `ble` / `plb` / `uart_ble` / `none`——隧道分别由焊着的 BLE 模组、芯片的 I/O 控制器、UART 外接的 BLE 适配器承载，或者根本不承载。这里用它决定编哪个 BSP 文件。这个决定属于构建，不属于 strata——strata 只保证取到的值是对的。

然后代码里 include 一个头文件、读 feature：

```c
#include "strata_features.h"

int main(void)
{
#if STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL            /* 这次构建可以打开隧道 */
    tunnel_start(STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS); /* 最多同时这么多会话 */
#else
    tunnel_start(0);                                      /* 有线构建：无可打开 */
#endif
    return 0;
}
```

`tunnel_start` 是 BSP 唯一的入口：带着会话上限打开隧道，有线构建传零。是哪个配置项让这项 feature 成立——焊着的 BLE 模组、芯片的 I/O 控制器、产品档位——永远到不了这个文件。

## 从别的 feature 推导 feature

控制面的 feature 可以由 BSP 的 feature 推导，硬件词汇——芯片上的可编程 I/O 控制器（`chip.pioc`）、板上焊着的 BLE 模组（`board.has_ble_module`）——就停在 `bsp` 内部。BSP 先把原始事实翻译成能力——`bsp.TUNNEL_BACKEND` 指出隧道由谁承载，`bsp.HAS_WIRELESS_TUNNEL` 说明是否承载得了，`bsp.MAX_SESSIONS` 给出这种方式支持的并发会话数——控制面再组合这些能力：

```toml
# components/bsp/strata_features.toml
component = "bsp"

[[feature]]
name = "bsp.HAS_WIRELESS_TUNNEL"
type = "bool"
requires = ["bsp.TUNNEL_BACKEND"]
```

```toml
# components/ctl/strata_features.toml
component = "ctl"
requires  = ["bsp"]

[[feature]]
name = "ctl.MAX_TUNNEL_SESSIONS"
type = "int"
requires = ["ctl.SUPPORT_WIRELESS_TUNNEL"]
```

```python
# components/ctl/strata_features.py
@feature("ctl.MAX_TUNNEL_SESSIONS")
def max_tunnel_sessions(config, features):
    if not features.ctl.SUPPORT_WIRELESS_TUNNEL:
        return 0
    return features["bsp.MAX_SESSIONS"]
```

规则是：一个组件能读它顶层 `requires` 传闭包内的组件的全部 feature（锥）；一个 feature 能读自己的 `requires` 链能到达的同组件 feature；越界读在读取时硬失败；两张图有环都在加载期报出完整路径。求值顺序固定且可推导：依赖在前，同层按 id。每次 feature 读取记入清单的 `from`，配置项读取记入 `by`。resolver 应当是入参的纯函数——strata 不检查这一点，但不纯的求解会让推导值不可预测。

## 概念

词汇是刻意做小的。下面这些词会出现在 strata 的文件、产物和报错里。

| 术语 | 定义 | 要点 |
| --- | --- | --- |
| **配置声明（schema）** | 配置项的全局词汇表：id、类型、取值范围、默认值与说明 | 组件只读不写；id 全局唯一 |
| **配置项（item）** | 声明出来的一条值，如 `board.has_ble_module`——板上焊着 BLE 模组 | 有类型：`bool` / `int` / `float` / `string`。它的含义属于拥有它的那个领域 |
| **预设（preset）** | 一份完整的配置项取值：一款产品、一次部署、一个客户 | 没写到的项取声明的默认值 |
| **组件（component）** | 一个目录：`strata_features.toml` 是契约，`strata_features.py` 是求解函数 | 拥有自己的 feature。顶层 `component = "..."` 一行是它的身份与归属标签；顶层 `requires` 一行列出它要读的组件 |
| **feature** | 由配置项或其他 feature 推导出的、带名字带类型的值，构建与代码都能读，如 `ctl.SUPPORT_WIRELESS_TUNNEL`（这次构建可以打开隧道） | 这是**软件的词汇**，不是配置的词汇。全局唯一，任何订阅了它的目标都看得见；一个 feature 只能读它所在组件的 `requires` 锥内的 feature，以及自己的 `requires` 链能到达的同组件 feature |
| **resolver** | 算出一个 feature 的函数：`@feature("...")` 加上 `(config) -> value` 或 `(config, features) -> value` | 一个 feature、一个函数、一个归属人 |
| **config 对象** | 传给 resolver 的配置视图（`config.chip.pioc`） | 每次读取都被记录——溯源就是从这里来的 |
| **features 视图** | 只读的已求值 feature 视图（`features.bsp.HAS_WIRELESS_TUNNEL`、`features["bsp.MAX_SESSIONS"]`） | 每次读取先按声明图校验，再记入 `from` |
| **视图（views）** | 生成物：一份 CMake 文件，一个 C 头文件 | 同一次运行产出，因此不可能不一致 |
| **清单（manifest）** | `strata_manifest.json`：值、归属、实际读到的配置项（`by`）、实际读到的 feature（`from`）、输入哈希 | 「为什么是开着的」的答案 |
| **逃生舱** | 全部配置项的导出，前缀 `STRATA_CONFIG_*` | 刻意提供、刻意不推荐：读了它就重新绑回原始词汇 |

## 它不是什么

| 它不是 | 因为 |
| --- | --- |
| 配置管理器 | 它不负责值从哪来、怎么存、怎么分发 |
| Kconfig 的替代品 | Kconfig 不说明符号对软件意味着什么，也不从别的符号推导符号；strata 的主题是这条推导，不是值的存放 |
| 构建系统 | 它不编译任何东西，只产出 CMake 消费的输入 |
| 运行时开关服务 | 它只覆盖构建期与编译期的决策，不涉及设备运行时的行为 |
| 强制机制 | 它强制声明出来的 feature 图——锥与 sibling 闭包之外的 feature 读是硬错误——但配置项的读取不被拦，分层好坏仍由人评审 |
| 硬件工具 | 硬件只是最常见的第一个场景，不是主题。任何有多个答案的配置，都适用同一套形状 |

## 接口

### CMake 函数

| 接口 | 签名 | 作用 |
| --- | --- | --- |
| `strata_project` | `(SCHEMA <目录> PRESETS <目录> [OUT <目录>])` | 声明配置项与预设的位置；从缓存变量 `STRATA_PRESET` 读取产品 |
| `strata_add_component_path` | `(<目录>)` | 声明一个组件目录；身份与 `requires` 来自目录里 `strata_features.toml` 的顶层声明 |
| `strata_link_resolves` | `(<目标>)` | 让目标订阅生成结果 |
| `strata_get_feature` | `(<feature-id> <输出变量>)` | 供构建逻辑读取 feature 值，中间量也可以读 |
| `strata_get_config` | `(<config-id> <输出变量>)` | 读取原始配置项（不推荐） |

四点要注意：

- **预设不是参数。** 它是缓存变量，用 `-DSTRATA_PRESET=<名称>` 或 CMake preset 设定。`CMakeLists.txt` 里不出现任何产品名，切换产品不需要改构建文件。
- **组件名也不是参数。** `strata_add_component_path` 只传目录；该目录 `strata_features.toml` 顶层的 `component` 与 `requires` 两行说明它是谁、它读谁。
- **生成推迟到第一次真正需要取值时**，因为组件是在 `strata_project` 之后声明的。`strata_project` 与各消费者都是 macro，就是为了这一点：生成的 `.cmake` 在调用者作用域里 `include`，值在读取它的地方可见。
- **顺序有意义**：先工程、再组件、最后目标。每一次 `strata_add_component_path` 都必须出现在第一个消费者之前；生成时图里不认识的 `requires` 引用是硬错误。
- **改动即重配**：声明、预设或 resolver 文件一变，CMake 自动重新配置（`CMAKE_CONFIGURE_DEPENDS`），值不会过期。

### 生成文件

```
build/generated/
├── strata_features.cmake     set(STRATA_FEATURE_<id> <值>)，覆盖全部 feature
├── strata_features.h         #define STRATA_FEATURE_<ID> <值>
├── config/strata_config.h    #define STRATA_CONFIG_<ID> <值>
├── config/strata_config.cmake
└── strata_manifest.json      值、溯源、输入哈希
```

所有 feature 都在同一个头文件里。调用过 `strata_link_resolves` 的目标拿得到它，没调用过的拿不到。

命名规则：`ctl.MAX_TUNNEL_SESSIONS` 在 C 侧是 `STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS`，在 CMake 侧是 `STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS`；配置项 `chip.pioc` 是 `STRATA_CONFIG_CHIP_PIOC`。两队前缀不交叉，光看前缀就知道手里拿的是**配置项**还是**feature**。

## 许可证

Copyright (C) 2026 CYK-Dot。

GPL-3.0-or-later——GNU 通用公共许可证第三版或更新版本。全文见 [LICENSE](LICENSE)。
