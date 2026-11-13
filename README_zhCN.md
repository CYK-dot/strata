# strata

**在配置上把问题域与解域分开。**

strata 把「这块板子上焊了蓝牙模组」这类**问题域事实**，转换成「本次构建提供无线隧道」这类**解域能力**，并把两者之间的对应关系留在唯一一份可评审的文件里。CMake 与 C/C++ 读到的是同一次推导的结果，构建系统与源码不可能对「这台设备支持什么」各执一词。

```c
/* 之前：控制面在读它本不该知道的硬件事实 */
#if defined(MCU_HAS_PIOC) || defined(BOARD_HAS_BLE_MODULE) || defined(BOARD_HAS_AT_ADAPTER)
    tunnel_start(2);
#endif

/* 之后：控制面读一项能力 */
#if STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL
    tunnel_start(STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS);
#endif
```

隧道底下走的是蓝牙、片上可编程逻辑还是 UART 适配器，被封在抽象之下——BSP 实现同一个接口，上层不必知道。

---

## 什么时候需要它

- **一套源码、多款产品**，差别在于某项能力**由谁提供**，而不在于软件要不要提供它。
- **`#if` 里混着几个硬件事实**（`BOARD_HAS_BLE || MCU_HAS_PIOC`），每加一颗芯片就要再改一遍。
- **构建逻辑与源码各走各的**：CMake 用一套开关挑源文件，C 代码用另一套宏分支，靠人同步。
- **没人答得上来「这次构建为什么有这个功能」**，除非去翻代码和芯片手册。
- **映射本身值得评审**：「有 PIOC 或 PLB 就够软卸载 JTAG」是一条硬件结论，今天它躺在预处理表达式里，没有名字，也没有被验证过。

## 什么时候不需要它

- 只有一个目标、一个开关——CMake 的 `option()` 更便宜也更清楚。
- 驱动内部。那里 strata 只能买到「一堆互相约束的宏有了求解与校验」；真正的收益出现在**承诺与硬件无关**的层：控制面、协议栈、应用逻辑。
- 没有变体可切——没有映射可做。

---

## 概念

strata 的词汇是刻意做小的。下面这些词会出现在它的文件、产物和报错里。

**问题域 / 声明（schema）**：目标是**什么**——芯片、板卡、产品档位的事实与数值。声明文件里定义**维度**：id、类型（`bool` / `int` / `float` / `string`）、可选取值范围、可选默认值、一行说明。声明是全局的：组件只读，不得扩展。

**预设（preset）**：一份完整的取值——哪颗芯片、哪块板、哪个档位。一个预设文件就是一款产品；没写的维度取声明的默认值。

**config 对象**：resolver 拿到的东西，`config.chip.pioc` 或 `config["board.has_ble_module"]`。它同时是探针：每次读取都被记录，于是 strata 事后能说出「是哪几条事实让它成立」。

**组件（component）**：一个目录，里面 `strata_features.toml` 是契约（有哪些 feature、什么类型、什么说明），`strata_features.py` 是求解函数。组件拥有自己的 feature，并声明一个 `layer`。

**feature**：构建系统与源码都能读到的带类型值，例如 `ctl.SUPPORT_WIRELESS_TUNNEL`。名字全局唯一。feature **只从问题域值推导，绝不引用别的 feature**——这让求值顺序无关紧要，环也不可能出现。

**resolver（求解函数）**：算出一个 feature 的那个函数。

```python
@feature("ctl.SUPPORT_WIRELESS_TUNNEL")
def support_wireless_tunnel(config):
    return config.product.wireless_debug and (
        config.board.has_ble_module
        or config.chip.pioc
        or config.board.has_uart_ble_adapter
    )
```

一个 feature，一个 resolver，一个归属人。

**层（layer）**：可见性的边界。feature 按层生成到各自的头文件里，因此只链接了 `ctl` 层的控制面目标，连 `bsp.TUNNEL_BACKEND` 这个名字都拿不到。strata 不禁止跨层，只是**不把别层的宏递给你**。

**视图（view）**：生成物——一份 CMake 视图（`strata_features.cmake`）与按层的 C 视图（`<layer>/strata_features.h`）。同一次运行产出，因此不可能不一致。

**清单（manifest）**：`strata_manifest.json`，记录每个 feature 的值、归属组件、**实际读到**的问题域变量（`by`），以及全部输入的哈希。它就是「为什么是开着的」的答案。

**逃生舱**：每个问题域值同时导出为 `STRATA_CONFIG_*`，供那些找不到诚实 feature 名的场合使用（主频、Flash 容量）。**它被刻意提供，也被刻意不推荐**：读它等于把代码重新焊回硬件。生成物顶部会写明，除此以外只有评审能拦你。

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

### 命令行

```bash
python -m strata generate \
  --schema     configs/schema \
  --presets    configs/presets \
  --components components \
  --preset     daplink_plb \
  --out        build/generated
```

跑一个预设的完整流程，产出两侧视图与清单。需要 Python 3.11 及以上，无第三方运行时依赖。

### CMake

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
| `strata_add_component` | `(<名称> [LAYER <层>] [DIR <目录>])` | 登记组件，建立导入目标 `strata::<名称>`，其 include 路径指向该层的头文件目录 |
| `strata_link_resolves` | `(<目标> <组件>...)` | 让目标订阅生成结果 |
| `strata_get_feature` | `(<feature-id> <输出变量>)` | 供构建逻辑读取 feature 值 |
| `strata_get_config` | `(<config-id> <输出变量>)` | 读取问题域原始值（不推荐） |

三点要注意：

- **`strata_add_project` 是 macro 而不是 function**。生成的 `.cmake` 必须在调用者的作用域里 `include`，否则 `STRATA_FEATURE_*` 只活在函数局部，后面的 `strata_get_feature` 根本看不见。其余四个是 function。
- **顺序有意义**：先工程、再组件、最后目标。在 `strata_add_project` 之前调用 `strata_get_feature` 是报错，不是返回空值。
- **生成发生在配置期**，因为 CMake 自己要用这些值选源文件。改动声明、预设或 resolver 会自动触发重新配置（`CMAKE_CONFIGURE_DEPENDS`）。

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

Python 3.11 及以上（仅用标准库），CMake 3.20 及以上。

---

## 许可证

strata 是自由软件，采用 **GNU 通用公共许可证第三版（GPLv3）**。全文见 [LICENSE](LICENSE)。

含义是：你可以使用、研究、修改、再分发它，包括商业用途；条件是衍生作品同样以 GPLv3 分发，且接收者能拿到源码。没有担保。
