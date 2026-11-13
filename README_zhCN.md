# strata

> **strata 把「目标是什么」推导成「软件提供什么」，并把这条推导保存为唯一一份可评审的产物。**

这句话压着三个主张，每个都带一个设计后果。

**一、「目标是什么」是一个独立的模型。**
硬件是什么——哪颗芯片、哪块板、哪个产品档位——被写成数据：有名字、有类型、有取值范围、有默认值。它由懂硬件的人拥有，按硬件的节奏变化，并且不描述软件。

**二、「推导」是一份产物，不是一种习惯。**
两侧的对应关系——「有 PIOC 或 PLB 就够软卸载 JTAG」——只写一次、只放一处，因而可评审、可解释、可测试。今天它躺在预处理表达式里：没有名字，被复制多份，从未被验证过。

**三、结果被两个消费者共享。**
推导产出带类型的 **feature**。构建系统读它决定编什么、链什么；C/C++ 读它决定开什么。两边读的是同一次运行的同一份值，所以构建期裁剪与编译期分支不可能各说各话。

本文其余部分，都是这三条的推论。

---

## 这个定义改变了什么

```c
/* 之前：控制面在读它本不该知道的硬件事实。
 * 三个事实、一项能力，决策发生在错误的层。 */
#if defined(MCU_HAS_PIOC) || defined(BOARD_HAS_BLE_MODULE) || defined(BOARD_HAS_AT_ADAPTER)
    tunnel_start(2);
#endif

/* 之后：同一个控制面读的是一项能力。
 * 由什么硬件提供隧道，已经被封在抽象之下。 */
#if STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL
    tunnel_start(STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS);
#endif
```

第二版不会以同样的方式腐烂：多一条硬件路径，是映射文件里的一行，而不是控制面代码的一次改动。变的不是语法，是**知识住在哪里**。

---

## 它不是什么

| 它不是 | 因为 |
| --- | --- |
| 配置管理器 | 它不负责值从哪来、怎么存、怎么分发 |
| Kconfig 的替代品 | Kconfig 的符号共用一个平坦命名空间，表达不了「哪一层拥有它」，而这正是 strata 的全部意义 |
| 构建系统 | 它不编译任何东西，只产出 CMake 消费的输入 |
| 运行时开关服务 | 它只覆盖构建期与编译期的决策，不涉及设备运行时的行为 |
| 强制机制 | 它提供分层这条路，并让另一条路可见；它不拦人 |

---

## 什么时候需要它

- **一套源码、多款产品**，差别在于某项能力**由谁提供**，而不在于软件要不要提供它。
- **`#if` 里混着几个硬件事实**（`BOARD_HAS_BLE || MCU_HAS_PIOC`），每加一个目标就要再改一遍。
- **构建逻辑与源码各走各的**：CMake 用一套开关挑源文件，C 代码用另一套宏分支。
- **没人答得上来「这次构建为什么有这个功能」**，除非去翻代码和芯片手册。
- **映射本身值得评审**：硬件结论值得写下来一次、给它一个名字，而不是抄到每一个使用点。

## 什么时候不需要它

- 只有一个目标、一个开关——CMake 的 `option()` 更便宜也更清楚。
- 驱动内部。那里 strata 只能买到「一堆互相约束的宏有了求解与校验」；真正的收益出现在**承诺与硬件无关**的层：控制面、协议栈、应用逻辑。
- 没有变体可切——没有映射可做。

---

## 概念

词汇是刻意做小的。下面这些词会出现在 strata 的文件、产物和报错里。

| 术语 | 定义 | 要点 |
| --- | --- | --- |
| **问题域声明（schema）** | 目标的全局词汇表：维度的 id、类型、取值范围、默认值与说明 | 组件只读不写；维度 id 全局唯一 |
| **维度（dimension）** | 词汇表里的一条事实或参数，如 `chip.pioc`、`board.uart_count` | 有类型：`bool` / `int` / `float` / `string` |
| **预设（preset）** | 一份完整的维度取值，代表一款产品 | 没写的维度取声明的默认值 |
| **组件（component）** | 一个目录：`strata_features.toml` 是契约，`strata_features.py` 是求解函数 | 拥有自己的 feature，并声明一个 `layer` |
| **feature** | 由问题域推导出的带类型值，构建与代码都能读，如 `ctl.SUPPORT_WIRELESS_TUNNEL` | 全局唯一；只依赖问题域值，**绝不依赖别的 feature** |
| **resolver** | 算出一个 feature 的函数：`@feature("...")` 加上 `(config) -> value` | 一个 feature、一个函数、一个归属人 |
| **config 对象** | 传给 resolver 的问题域视图（`config.chip.pioc`） | 每次读取都被记录——溯源就是从这里来的 |
| **层（layer）** | feature 的可见性边界 | 生成到该层自己的头文件里；跨层可行，但工具不把别层的宏递给你 |
| **视图（views）** | 生成物：一份 CMake 视图，每层一份 C 头文件 | 同一次运行产出，因此不可能不一致 |
| **清单（manifest）** | `strata_manifest.json`：值、归属、实际读到的变量（`by`）、输入哈希 | 「为什么是开着的」的答案 |
| **逃生舱** | 全部问题域值的导出，前缀 `STRATA_CONFIG_*` | 刻意提供、刻意不推荐：读了它就重新焊回硬件 |

---

## 目录

strata 通常内嵌在它服务的工程里，只占一个目录：

```
project/
├── strata/                 工具本体：引擎、CMake 模块、自己的版本历史
├── configs/schema/         问题域声明，可多份、任意命名
├── configs/presets/        一款产品一个文件
├── components/<名称>/feature/strata_features.{toml,py}
├── src/                    读 feature 的代码
└── CMakeLists.txt
```

---

## 使用方式

没有需要运行的命令，也没有需要安装的东西：strata 就工作在 `CMakeLists.txt` 里，发生在 configure 阶段。

### 在 CMake 里

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

# 一、配置期生成一次
strata_add_project(
  SCHEMA     ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS    ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
  COMPONENTS ${CMAKE_CURRENT_SOURCE_DIR}/components
  PRESET     ${STRATA_PRESET}          # 例如 -DSTRATA_PRESET=...
)

# 二、登记本工程用到的组件
strata_add_component(ctl LAYER ctl)
strata_add_component(bsp LAYER bsp)

# 三、让目标订阅某一层
add_executable(firmware src/ctlp.c)
strata_link_resolves(firmware ctl)

# 四、构建系统自己要决策时取值
strata_get_feature("bsp.TUNNEL_BACKEND" backend)
target_sources(firmware PRIVATE bsp/tunnel_${backend}.c)

strata_get_feature("ctl.SUPPORT_WIRELESS_TUNNEL" has_tunnel)
if(has_tunnel)
  target_link_libraries(firmware PRIVATE tunnel_client)
endif()
```

| 接口 | 签名 | 作用 |
| --- | --- | --- |
| `strata_add_project` | `(SCHEMA <目录> PRESETS <目录> COMPONENTS <目录> PRESET <名称> [OUT <目录>])` | 配置期生成一次，并把 feature 值读进当前作用域 |
| `strata_add_component` | `(<名称> [LAYER <层>])` | 登记组件，建立导入目标 `strata::<名称>`，其 include 路径指向该层的头文件目录 |
| `strata_link_resolves` | `(<目标> <组件>...)` | 让目标订阅生成结果 |
| `strata_get_feature` | `(<feature-id> <输出变量>)` | 供构建逻辑读取 feature 值 |
| `strata_get_config` | `(<config-id> <输出变量>)` | 读取问题域原始值（不推荐） |

三点要注意：

- **`strata_add_project` 是 macro 而不是 function**。生成的 `.cmake` 必须在调用者的作用域里 `include`，否则 `STRATA_FEATURE_*` 只活在函数局部，后面的 `strata_get_feature` 根本看不见。其余四个是 function。
- **顺序有意义**：先工程、再组件、最后目标。在 `strata_add_project` 之前调用 `strata_get_feature` 是报错，不是返回空值。
- **改动即重配**：声明、预设或 resolver 文件一变，CMake 自动重新配置（`CMAKE_CONFIGURE_DEPENDS`），值不会过期。

### 在 C / C++ 里

`strata_link_resolves(firmware ctl)` 会把 `ctl` 层的头文件放进该目标的 include 路径，其余什么都不用做：

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

各层用同一个头文件名，所以 `strata_features.h` 到底解析到哪一份，由 include 路径决定：订阅了 `ctl` 的目标叫不出 `bsp` 的 feature，因为那份头文件不在它的路径上。

### 生成物

```
build/generated/
├── strata_features.cmake     set(STRATA_FEATURE_<id> <值>)，覆盖全部 feature
├── <层>/strata_features.h    #define STRATA_FEATURE_<层>_<名> <值>
├── config/strata_config.h    #define STRATA_CONFIG_<ID> <值>
├── config/strata_config.cmake
└── strata_manifest.json      值、溯源、输入哈希
```

命名规则：`ctl.MAX_TUNNEL_SESSIONS` 在 C 侧是 `STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS`，在 CMake 侧是 `STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS`；问题域维度 `chip.pioc` 是 `STRATA_CONFIG_CHIP_PIOC`。两队前缀不交叉，光看前缀就知道手里拿的是**事实**还是**能力**。

---

## 诊断

报错一律英文、纯 ASCII，形状对齐 CMake，编辑器和 CI 能直接跳到出错位置：

```
CMake Error at configs/presets/daplink_x.toml:2 (strata_add_project):
  Unknown variable "board.has_ble".

  Did you mean "board.has_ble_module"?
```

会被判为硬失败的情况：重复声明、前缀冲突、预设里的未知变量或缺失必填、类型与取值范围不符、声明了 feature 却没有 resolver（或反过来）、feature 重名、resolver 返回类型不符、resolver 抛异常。

---

## 环境要求

- CMake 3.20 及以上。
- Python 3.11 及以上，仅用标准库。它由 CMake 在 configure 阶段调用，使用者不需要自己执行。

---

## 许可证

Copyright (C) 2026 CYK-Dot。

strata 是自由软件，采用 **GNU 通用公共许可证第三版或更新版本**（GPL-3.0-or-later）。全文见 [LICENSE](LICENSE)。

含义是：你可以使用、研究、修改、再分发它，包括商业用途；条件是衍生作品同样以 GPLv3 分发，且接收者能拿到源码。没有担保。
