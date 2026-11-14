# strata

English | [简体中文](README.zh-CN.md)

[![CI](https://github.com/CYK-dot/strata/actions/workflows/ci.yml/badge.svg)](https://github.com/CYK-dot/strata/actions/workflows/ci.yml)

Turns configuration items into named features that CMake and C/C++ code read.

This file follows one running example: a USB debug probe whose firmware can
offer a *wireless debug tunnel* — the probe debugs the target board over BLE
instead of a cable. Whether that is possible rests on facts such as: a BLE
module is soldered on the board (`board.has_ble_module`), the chip carries a
programmable I/O controller (`chip.pioc`), the product tier offers wireless
debugging (`product.wireless_debug`). Facts like these are **configuration
items**. What the software can do — `ctl.SUPPORT_WIRELESS_TUNNEL`, "this build
can open the tunnel" — is a **feature**, derived from the items once; the
build and the code read only the feature. A feature id carries its owning
component as a prefix: `ctl.` is the control plane, `bsp.` the board support.
Features may build on other features: a component declares `requires` and
derives its features from the lower layer's features, so hardware words stay
in the hardware layer.

The obvious alternative is to read the items directly: `#ifdef` in the sources,
`if()` in CMake. That works while there are two items. As they multiply:

- the predicates grow with the items and with their combinations, and the same
  decision is copied into every place that needs it;
- the code speaks the configuration's vocabulary, so a new chip or a new customer
  tier means editing code that had no business knowing those words;
- the build and the sources decide independently, and nothing keeps them in step;
- nobody can answer "why is this enabled in this build?" without reading both.

**The idea.** Nothing above the configuration should read the items; it should
read what was derived from them.

strata makes that derivation a layer of its own. Each component declares the
features it exposes and writes the function that derives each one — from the
configuration items, or from the features of the components it declares in
`requires`. The declarations form a directed graph that strata evaluates in a
deterministic order and emits as a CMake file and one C header. Adding a chip,
a tier or a region becomes a new derivation instead of an edit to code that
should not care.

Hardware is the usual first case — several different chips can provide the same
capability — but nothing in strata is specific to hardware. Any configuration
with more than one answer fits the same shape.

It pays off when one codebase has to serve several configurations. It is not
worth it for a single build with a single switch — a CMake `option()` is cheaper.

## Install

strata lives inside the project it serves, so the recommended way to bring it in
is a git submodule: each project pins the version it builds with, in its own
history.

```sh
cd your-project
git submodule add https://github.com/CYK-dot/strata.git strata
git commit -m "add strata"
```

Clone with the submodule, or fetch it later:

```sh
git clone --recurse-submodules <your-project>   # when cloning
git submodule update --init --recursive        # after a plain clone
git submodule update --remote strata           # move to a newer strata
```

It then sits at the project root:

```
your-project/
├── strata/                 the submodule
├── configs/                configuration items and presets
├── components/             features and the functions that derive them
└── CMakeLists.txt
```

Dependencies:

- CMake 3.20 or newer
- Python 3.11 or newer, standard library only. CMake invokes it during the
  configure step; you never call it yourself.

## Usage

The product is chosen when configuring, not in the build file, so one
`CMakeLists.txt` builds every product:

```sh
cmake -B build/ble -DSTRATA_PRESET=daplink_ble
```

A preset is one file in the presets directory that assigns every item for one
product; `daplink_ble` is the probe with the BLE module fitted.

Enabled once, near the top of `CMakeLists.txt`:

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

strata_project(
  SCHEMA  ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
)

strata_add_component_path(${CMAKE_CURRENT_SOURCE_DIR}/components/ctl)
strata_add_component_path(${CMAKE_CURRENT_SOURCE_DIR}/components/bsp)

# The build picks which BSP implementation goes in.
strata_get_feature("bsp.TUNNEL_BACKEND" backend)

add_executable(firmware
  src/ctlp.c
  bsp/tunnel_${backend}.c
)
strata_link_resolves(firmware)   # every feature becomes visible to this target
```

`backend` is `ble`, `plb`, `uart_ble` or `none` — the tunnel carried by the
soldered BLE module, by the chip's I/O controller, by a UART-attached BLE
adapter, or not carried at all. Here it decides which BSP file is compiled.
That decision belongs to the build, not to strata — strata only guarantees the
value is the right one.

Then the code includes one header and reads the features:

```c
#include "strata_features.h"

int main(void)
{
#if STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL            /* this build can open the tunnel */
    tunnel_start(STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS); /* with at most this many sessions */
#else
    tunnel_start(0);                                      /* wired build: nothing to open */
#endif
    return 0;
}
```

`tunnel_start` is the BSP's one entry point: open the tunnel with a session
cap, or with zero on a wired build. Which configuration item made the feature
true — the soldered BLE module, the chip's I/O controller, the product tier —
never reaches this file.

## Deriving a feature from other features

A control plane can derive its features from a BSP's features, so the hardware
vocabulary (`chip.pioc`, `board.has_ble_module`) stops inside the BSP. The BSP
first turns raw facts into capabilities — `bsp.TUNNEL_BACKEND` names the way
the tunnel is carried, `bsp.HAS_WIRELESS_TUNNEL` says whether it can be carried
at all, `bsp.MAX_SESSIONS` says how many concurrent sessions that way supports
— and the control plane composes those:

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

The rules: a component reads the features of the components its top-level
`requires` reaches (the cone); a feature reads the siblings its own `requires`
chain reaches; anything else is a hard error at read time, and cycles in either
graph fail at load with the full path. The evaluation order is fixed and
derivable: dependencies first, ties by id. Every feature read is recorded as
`from` in the manifest, next to the config reads in `by`. Resolvers are
expected to be pure functions of their arguments — strata does not check it,
but anything else makes the derived values unpredictable.

## Concepts

The vocabulary is deliberately small. These are the words that appear in strata's
files, output and errors.

| Term | Definition | What matters |
| --- | --- | --- |
| **Configuration schema** | The global vocabulary of configuration items: ids, types, ranges, defaults and docs | Components read it; they never extend it. Ids are globally unique |
| **Configuration item** | One declared value, e.g. `board.has_ble_module`, `chip.pioc`, `product.wireless_debug` | Typed: `bool`, `int`, `float` or `string`. Its meaning belongs to whoever owns that domain |
| **Preset** | One complete assignment of items — one product, one deployment, one customer | Anything not given falls back to the schema default |
| **Component** | A directory holding `strata_features.toml` (contract) next to `strata_features.py` (resolvers) | Owns its features. The top-level `component = "..."` line is its identity and owner tag; the top-level `requires` line lists the components it reads from |
| **Feature** | A named, typed value derived from configuration items or from other features, readable by both the build and the code, e.g. `ctl.SUPPORT_WIRELESS_TUNNEL` | This is the software's vocabulary, not the configuration's. Globally unique, and visible to every subscriber; a feature may read only the cone of its component's `requires` and the siblings its own `requires` reaches |
| **Resolver** | The function that computes one feature: `@feature("...")` and `(config) -> value` or `(config, features) -> value` | One feature, one resolver, one owner |
| **config object** | The configuration view handed to a resolver (`config.chip.pioc`) | Every read is recorded — this is how provenance is recovered |
| **features view** | The read-only view of already-evaluated features (`features.bsp.HAS_WIRELESS_TUNNEL`, `features["bsp.MAX_SESSIONS"]`) | Reads are checked against the declared graph and recorded as `from` |
| **Views** | The generated artifacts: one CMake file and one C header | Produced by one run, so they cannot disagree |
| **Manifest** | `strata_manifest.json`: values, owners, the items read (`by`), the features read (`from`), input hashes | The answer to "why is this enabled?" |
| **Escape hatch** | Every configuration item, exported as `STRATA_CONFIG_*` | Available on purpose, discouraged on purpose: reading it re-couples the code to the raw vocabulary |

## What strata is not

| It is not | Because |
| --- | --- |
| A configuration manager | It does not own where values come from, how they are stored, or how they are distributed |
| A Kconfig replacement | Kconfig says nothing about what a symbol *means* to the software, and nothing derives one symbol from another; strata's subject is that derivation, not the storage of values |
| A build system | It compiles nothing; it produces input that CMake consumes |
| A runtime switch service | It covers build-time and compile-time decisions only, never what a running device does |
| An enforcement mechanism | It shows what reads an item instead of a feature; it does not block it |
| A hardware tool | Hardware is the usual first case, not the subject. Any configuration with more than one answer fits the same shape |

## API

### CMake functions

| Function | Signature | Purpose |
| --- | --- | --- |
| `strata_project` | `(SCHEMA <dir> PRESETS <dir> [OUT <dir>])` | Declare where configuration items and presets live. Reads `STRATA_PRESET` from the cache |
| `strata_add_component_path` | `(<directory>)` | Declare one component directory; its identity and `requires` come from its `strata_features.toml` |
| `strata_link_resolves` | `(<target>)` | Subscribe a target to the generated views |
| `strata_get_feature` | `(<feature-id> <out-var>)` | Read a feature value for build decisions, intermediates included |
| `strata_get_config` | `(<config-id> <out-var>)` | Read a raw configuration item (discouraged) |

Notes:

- **The preset is not an argument.** It is a cache variable, set with
  `-DSTRATA_PRESET=<name>` or by a CMake preset. Nothing in `CMakeLists.txt`
  names a product, so switching products never edits the build file.
- **The component name is not an argument either.** `strata_add_component_path`
  passes a directory only; the top-level `component` and `requires` lines in
  that directory's `strata_features.toml` say who it is and what it reads.
- Generation is deferred until the first call that needs values, because
  components are declared after `strata_project`. `strata_project` and
  the consumers are macros for that reason: the generated `.cmake` is
  included in the caller's scope, so the values are visible where they are read.
- Order matters: project, then components, then targets. Every
  `strata_add_component_path` must come before the first consumer; a `requires`
  entry the graph does not know at generation time is a hard error.
- A change to any schema, preset or resolver file triggers a re-configure
  automatically (`CMAKE_CONFIGURE_DEPENDS`), so the values can never be stale.

### Generated files

```
build/generated/
├── strata_features.cmake     set(STRATA_FEATURE_<id> <value>) for every feature
├── strata_features.h         #define STRATA_FEATURE_<ID> <value>
├── config/strata_config.h    #define STRATA_CONFIG_<ID> <value>
├── config/strata_config.cmake
└── strata_manifest.json      values, provenance, input hashes
```

One header holds every feature. A target that calls `strata_link_resolves` gets
it on its include path; a target that does not, does not.

Naming: a feature `ctl.MAX_TUNNEL_SESSIONS` becomes
`STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS` in C and
`STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS` in CMake; a configuration item
`chip.pioc` becomes `STRATA_CONFIG_CHIP_PIOC`. The two prefixes never overlap, so
the prefix alone tells you whether you are holding an item or a feature.

## License

Copyright (C) 2026 CYK-Dot.

GPL-3.0-or-later — GNU General Public License, version 3 or any later version.
The full text is in [LICENSE](LICENSE).
