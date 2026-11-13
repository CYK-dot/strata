# strata

一个从目标描述推导软件特性的 CMake 配置生成器。

大多数有一定规模的项目，都把两类知识放在同一处：目标硬件**是什么**——哪颗芯片、哪块板、焊了哪些选配——以及这一次构建的软件**提供什么**。两者被焊进预处理表达式里，于是每加一款产品，都要去改那些本该与硬件无关的代码。

strata 把它们分开。目标被描述成数据；软件的特性由紧挨着所属组件的函数，从这份描述推导出来。推导只写一次，因此可以被评审、解释和测试，而不是被复制到每一个使用点。

推导出的特性是带类型的值，构建系统与 C/C++ 代码从同一批生成文件里读到它们。改动目标描述，就改掉了编什么、开什么，而两侧都不必知道硬件碰巧是怎么提供这项能力的。

一套源码要出多款产品时，它划算；单目标、单开关时，它不划算——CMake 的 `option()` 更便宜。

## 目录

- [安装](#安装)
- [使用](#使用)
- [概念](#概念)
- [它不是什么](#它不是什么)
- [诊断](#诊断)
- [接口](#接口)
- [参与](#参与)
- [许可证](#许可证)

## 安装

strata 不是一个要安装的软件包，而是一个随源码内嵌进工程的目录，并带着自己的版本历史。

```
your-project/
├── strata/                 本仓库
├── configs/                目标描述与预设
├── components/             特性及其推导函数
└── CMakeLists.txt
```

依赖：

- CMake 3.20 及以上
- Python 3.11 及以上，仅用标准库。它由 CMake 在 configure 阶段调用，使用者不需要自己执行。

## 使用

在 `CMakeLists.txt` 靠上的位置启用一次：

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

strata_add_project(
  SCHEMA     ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS    ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
  COMPONENTS ${CMAKE_CURRENT_SOURCE_DIR}/components
  PRESET     ${STRATA_PRESET}          # 例如 -DSTRATA_PRESET=...
)

strata_add_component(ctl LAYER ctl)
strata_add_component(bsp LAYER bsp)

add_executable(firmware src/ctlp.c)
strata_link_resolves(firmware ctl)

strata_get_feature("bsp.TUNNEL_BACKEND" backend)
target_sources(firmware PRIVATE bsp/tunnel_${backend}.c)
```

然后代码里 include 一个头文件、读特性：

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

特性背后是什么——蓝牙模组、可编程 I/O 控制器、还是 UART 适配器——永远到不了这个文件。

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

## 它不是什么

| 它不是 | 因为 |
| --- | --- |
| 配置管理器 | 它不负责值从哪来、怎么存、怎么分发 |
| Kconfig 的替代品 | Kconfig 的符号共用一个平坦命名空间，表达不了「哪一层拥有它」，而这正是 strata 的全部意义 |
| 构建系统 | 它不编译任何东西，只产出 CMake 消费的输入 |
| 运行时开关服务 | 它只覆盖构建期与编译期的决策，不涉及设备运行时的行为 |
| 强制机制 | 它提供分层这条路，并让另一条路可见；它不拦人 |

## 诊断

报错一律英文、纯 ASCII，形状对齐 CMake，编辑器和 CI 能直接跳到出错位置：

```
CMake Error at configs/presets/daplink_x.toml:2 (strata_add_project):
  Unknown variable "board.has_ble".

  Did you mean "board.has_ble_module"?
```

会被判为硬失败的情况：重复声明、前缀冲突、预设里的未知变量或缺失必填、类型与取值范围不符、声明了 feature 却没有 resolver（或反过来）、feature 重名、resolver 返回类型不符、resolver 抛异常。

## 接口

### CMake 函数

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

### 生成文件

```
build/generated/
├── strata_features.cmake     set(STRATA_FEATURE_<id> <值>)，覆盖全部 feature
├── <层>/strata_features.h    #define STRATA_FEATURE_<层>_<名> <值>
├── config/strata_config.h    #define STRATA_CONFIG_<ID> <值>
├── config/strata_config.cmake
└── strata_manifest.json      值、溯源、输入哈希
```

各层用同一个头文件名，所以 `strata_features.h` 到底解析到哪一份，由 include 路径决定：订阅了 `ctl` 的目标叫不出 `bsp` 的 feature，因为那份头文件不在它的路径上。

命名规则：`ctl.MAX_TUNNEL_SESSIONS` 在 C 侧是 `STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS`，在 CMake 侧是 `STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS`；问题域维度 `chip.pioc` 是 `STRATA_CONFIG_CHIP_PIOC`。两队前缀不交叉，光看前缀就知道手里拿的是**事实**还是**能力**。

## 参与

欢迎提 issue 和 pull request。测试用 pytest，除 Python 3.11 之外不需要别的：

```sh
python -m pytest -q
```

请保持生成物确定性：测试会逐字节比较两次运行的结果。

## 许可证

Copyright (C) 2026 CYK-Dot。

GPL-3.0-or-later——GNU 通用公共许可证第三版或更新版本。全文见 [LICENSE](LICENSE)。
