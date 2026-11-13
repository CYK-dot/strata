# strata

把配置项转换成带名字的 feature，供 CMake 与 C/C++ 读取。

配置项描述的是目标或产品——`board.has_ble_module`、`chip.pioc`、`tier.pro`；
feature 描述的是软件能做什么——`ctl.SUPPORT_WIRELESS_TUNNEL`。后者由前者推导而来，只推导一次；构建与代码只读后者。

最直接的做法是让两侧都去读配置项：源码里 `#ifdef`，CMake 里 `if()`。只有两个配置项时，这样没问题。可一旦多起来：

- 判断条件随配置项的数量与组合一起膨胀，同一条决定还会被复制到每一个需要它的地方；
- 代码开始说配置的词汇，于是新增一颗芯片、一个客户档位，就要去改那些本不该认识这些词的代码；
- 构建与源码各判各的，没有任何东西保证两边一致；
- 没人能回答「这次构建为什么开着它」，除非把两边都读一遍。

**理念：配置项之上的一切都不该直接读它们，该读推导出来的东西。**

strata 把这条推导做成独立的一层。每个组件声明它对外暴露的 feature，并为每一个写出从配置项推导它的函数。strata 把这些声明求值一次，产出两份东西：一份 CMake 文件，以及每一层一个 C 头文件。新增一颗芯片、一个档位或一个区域，就是一次新的推导，而不是去改那些本不该关心取值来源的代码。

硬件是最常见的第一个场景——几颗不同的芯片可以提供同一项能力——但 strata 里没有任何东西是硬件专属的。任何有多个答案的配置，都适用同一套形状。

一套源码要服务多套配置时，它划算；单目标、单开关时，它不划算——CMake 的 `option()` 更便宜。

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
├── configs/                配置项与预设
├── components/             feature 及其推导函数
└── CMakeLists.txt
```

依赖：

- CMake 3.20 及以上
- Python 3.11 及以上，仅用标准库。它由 CMake 在 configure 阶段调用，使用者不需要自己执行。

## 使用

产品在配置时选，不写在构建文件里，因此同一份 `CMakeLists.txt` 能构建所有产品：

```sh
cmake -B build/plb -DSTRATA_PRESET=daplink_plb
```

在 `CMakeLists.txt` 靠上的位置启用一次：

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

strata_add_project(
  SCHEMA  ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
)

strata_add_component(ctl ${CMAKE_CURRENT_SOURCE_DIR}/components/ctl)
strata_add_component(bsp ${CMAKE_CURRENT_SOURCE_DIR}/components/bsp)

add_executable(firmware src/ctlp.c)
strata_link_resolves(firmware ctl)

strata_get_feature("bsp.TUNNEL_BACKEND" backend)
target_sources(firmware PRIVATE bsp/tunnel_${backend}.c)
```

然后代码里 include 一个头文件、读 feature：

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

是哪个配置项让这项 feature 成立——蓝牙模组、可编程 I/O 控制器、还是某个客户档位——永远到不了这个文件。

## 概念

词汇是刻意做小的。下面这些词会出现在 strata 的文件、产物和报错里。

| 术语 | 定义 | 要点 |
| --- | --- | --- |
| **配置声明（schema）** | 配置项的全局词汇表：id、类型、取值范围、默认值与说明 | 组件只读不写；id 全局唯一 |
| **配置项（item）** | 声明出来的一条值，如 `chip.pioc`、`board.uart_count`、`tier.pro` | 有类型：`bool` / `int` / `float` / `string`。它的含义属于拥有它的那个领域 |
| **预设（preset）** | 一份完整的配置项取值：一款产品、一次部署、一个客户 | 没写到的项取声明的默认值 |
| **组件（component）** | 一个目录：`strata_features.toml` 是契约，`strata_features.py` 是求解函数 | 拥有自己的 feature，并声明一个 `layer` |
| **feature** | 由配置项推导出的、带名字带类型的值，构建与代码都能读，如 `ctl.SUPPORT_WIRELESS_TUNNEL` | 这是**软件的词汇**，不是配置的词汇。全局唯一；只依赖配置项，**绝不依赖别的 feature** |
| **resolver** | 算出一个 feature 的函数：`@feature("...")` 加上 `(config) -> value` | 一个 feature、一个函数、一个归属人 |
| **config 对象** | 传给 resolver 的配置视图（`config.chip.pioc`） | 每次读取都被记录——溯源就是从这里来的 |
| **层（layer）** | feature 的可见性边界 | 生成到该层自己的头文件里；跨层可行，但工具不把别层的宏递给你 |
| **视图（views）** | 生成物：一份 CMake 视图，每层一份 C 头文件 | 同一次运行产出，因此不可能不一致 |
| **清单（manifest）** | `strata_manifest.json`：值、归属、实际读到的配置项（`by`）、输入哈希 | 「为什么是开着的」的答案 |
| **逃生舱** | 全部配置项的导出，前缀 `STRATA_CONFIG_*` | 刻意提供、刻意不推荐：读了它就重新绑回原始词汇 |

## 它不是什么

| 它不是 | 因为 |
| --- | --- |
| 配置管理器 | 它不负责值从哪来、怎么存、怎么分发 |
| Kconfig 的替代品 | Kconfig 的符号共用一个平坦命名空间，表达不了「哪一层拥有它」，而这正是 strata 的全部意义 |
| 构建系统 | 它不编译任何东西，只产出 CMake 消费的输入 |
| 运行时开关服务 | 它只覆盖构建期与编译期的决策，不涉及设备运行时的行为 |
| 强制机制 | 它提供分层这条路，并让另一条路可见；它不拦人 |
| 硬件工具 | 硬件只是最常见的第一个场景，不是主题。任何有多个答案的配置，都适用同一套形状 |

## 诊断

报错一律英文、纯 ASCII，形状对齐 CMake，编辑器和 CI 能直接跳到出错位置：

```
CMake Error at configs/presets/daplink_x.toml:2 (strata_add_project):
  Unknown variable "board.has_ble".

  Did you mean "board.has_ble_module"?
```

会被判为硬失败的情况：重复声明、前缀冲突、预设里的未知项或缺失必填、类型与取值范围不符、声明了 feature 却没有 resolver（或反过来）、feature 重名、resolver 返回类型不符、resolver 抛异常。

## 接口

### CMake 函数

| 接口 | 签名 | 作用 |
| --- | --- | --- |
| `strata_add_project` | `(SCHEMA <目录> PRESETS <目录> [OUT <目录>])` | 声明配置项与预设的位置；从缓存变量 `STRATA_PRESET` 读取产品 |
| `strata_add_component` | `(<名称> <目录>)` | 声明一个组件，建立导入目标 `strata::<名称>`，其 include 路径指向该组件所在层的目录 |
| `strata_link_resolves` | `(<目标> <组件>...)` | 让目标订阅生成结果 |
| `strata_get_feature` | `(<feature-id> <输出变量>)` | 供构建逻辑读取 feature 值 |
| `strata_get_config` | `(<config-id> <输出变量>)` | 读取原始配置项（不推荐） |

四点要注意：

- **预设不是参数。** 它是缓存变量，用 `-DSTRATA_PRESET=<名称>` 或 CMake preset 设定。`CMakeLists.txt` 里不出现任何产品名，切换产品不需要改构建文件。
- **生成推迟到第一次真正需要取值时**，因为组件是在 `strata_add_project` 之后声明的。`strata_add_project` 与三个消费者都是 macro，就是为了这一点：生成的 `.cmake` 在调用者作用域里 `include`，值在读取它的地方可见。
- **顺序有意义**：先工程、再组件、最后目标。在组件声明之前调用 `strata_get_feature` 是报错，不是返回空值。
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

命名规则：`ctl.MAX_TUNNEL_SESSIONS` 在 C 侧是 `STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS`，在 CMake 侧是 `STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS`；配置项 `chip.pioc` 是 `STRATA_CONFIG_CHIP_PIOC`。两队前缀不交叉，光看前缀就知道手里拿的是**配置项**还是**feature**。

## 参与

欢迎提 issue 和 pull request。测试用 pytest，除 Python 3.11 之外不需要别的：

```sh
python -m pytest -q
```

请保持生成物确定性：测试会逐字节比较两次运行的结果。

## 许可证

Copyright (C) 2026 CYK-Dot。

GPL-3.0-or-later——GNU 通用公共许可证第三版或更新版本。全文见 [LICENSE](LICENSE)。
