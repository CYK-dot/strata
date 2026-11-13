# strata

> **strata derives the software's features from a description of the target, and
> keeps that derivation as one explicit, reviewable artifact.**

Read that sentence again: three claims are packed into it, and each one carries a
design consequence.

**1. "a description of the target" is a model of its own.**
What the hardware *is* — which chip, which board, which product tier — is
written down as data: named values with types, ranges and defaults. It is owned
by the people who know the hardware, changed at the rate the hardware changes,
and it says nothing about software.

**2. "the derivation" is an artifact, not a habit.**
The correspondence between the two sides — *"PIOC or PLB is enough to offload
JTAG"* — is written once, in one place, where it can be reviewed, explained and
tested. Today it lives inside preprocessor expressions: unnamed, duplicated,
never verified.

**3. The result is shared by two consumers.**
Derivation produces typed **features**. The build system reads them to decide
what to compile and link; the C/C++ code reads them to decide what to enable.
Both read the *same* values from the *same* run, so build-time pruning and
compile-time branching cannot drift apart.

Everything else in this document is consequence.

---

## What the definition changes

```c
/* Before: a control plane reading hardware facts it should not know.
 * Three facts, one capability, decided at the wrong layer. */
#if defined(MCU_HAS_PIOC) || defined(BOARD_HAS_BLE_MODULE) || defined(BOARD_HAS_AT_ADAPTER)
    tunnel_start(2);
#endif

/* After: the same control plane reading a capability.
 * Which hardware provides the tunnel is below the abstraction now. */
#if STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL
    tunnel_start(STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS);
#endif
```

The second version cannot rot in the same way: adding a fourth hardware path is
a line in a mapping file, not an edit to control-plane code. What changed is not
the syntax but **where the knowledge lives**.

---

## What strata is not

| It is not | Because |
| --- | --- |
| A configuration manager | It does not own where values come from, how they are stored, or how they are distributed |
| A Kconfig replacement | Kconfig's symbols share one flat namespace and cannot express which layer owns them; strata's whole point is that boundary |
| A build system | It compiles nothing; it produces input that CMake consumes |
| A runtime switch service | It covers build-time and compile-time decisions only, never what a running device does |
| An enforcement mechanism | It provides the layered path and makes the other path visible; it does not block it |

---

## When you need it

- **One source tree, several products** that differ in *how* a capability is
  provided, not in *whether* the software offers it.
- **`#if` predicates that mix several hardware facts** (`BOARD_HAS_BLE ||
  MCU_HAS_PIOC`). Every new target edits them again.
- **Build logic and source code drift apart**: CMake picks sources from one set
  of switches, the C code branches on another.
- **Nobody can answer "why does this build have this feature?"** without reading
  code and datasheets.
- **The mapping itself deserves review**: hardware conclusions are worth writing
  down once, with a name, instead of being copied into every use site.

## When you probably don't

- One target and one switch. A CMake `option()` is cheaper and clearer.
- Driver internals. There strata only buys you solved, validated combinations of
  macros; the real payoff is at the layers that promise to be hardware
  agnostic — control plane, protocol stacks, application logic.
- A single build with no variants: there is nothing to map.

---

## Concepts

The vocabulary is deliberately small. These are the words that appear in strata's
files, output and errors.

| Term | Definition | What matters |
| --- | --- | --- |
| **Problem-domain schema** | The global vocabulary of the target: dimensions with ids, types, ranges, defaults and docs | Components read it; they never extend it. Ids are globally unique |
| **Dimension** | One fact or number in that vocabulary, e.g. `chip.pioc`, `board.uart_count` | Typed: `bool`, `int`, `float` or `string` |
| **Preset** | One complete assignment of dimensions — one product | Anything not given falls back to the schema default |
| **Component** | A directory holding `strata_features.toml` (contract) next to `strata_features.py` (resolvers) | Owns its features and declares one `layer` |
| **Feature** | A typed value derived from the problem domain, readable by both the build and the code, e.g. `ctl.SUPPORT_WIRELESS_TUNNEL` | Globally unique; depends on problem-domain values only, **never on another feature** |
| **Resolver** | The function that computes one feature: `@feature("...")` and `(config) -> value` | One feature, one resolver, one owner |
| **config object** | The problem-domain view handed to a resolver (`config.chip.pioc`) | Every read is recorded — this is how provenance is recovered |
| **Layer** | A visibility boundary for features | Emitted into that layer's own header; crossing layers is possible but not handed to you |
| **Views** | The generated artifacts: one CMake view, one C header per layer | Produced by one run, so they cannot disagree |
| **Manifest** | `strata_manifest.json`: values, owners, the variables read (`by`), input hashes | The answer to "why is this enabled?" |
| **Escape hatch** | Every problem-domain value, exported as `STRATA_CONFIG_*` | Available on purpose, discouraged on purpose: reading it re-couples the code to hardware |

---

## Layout

strata is normally vendored inside the project it serves, in one directory:

```
project/
├── strata/                 the tool: engine, CMake module, its own history
├── configs/schema/         problem-domain declarations (any number of files)
├── configs/presets/        one file per product
├── components/<name>/feature/strata_features.{toml,py}
├── src/                    code that reads features
└── CMakeLists.txt
```

---

## Usage

There is nothing to run and nothing to install: strata works inside `CMakeLists.txt`,
during the configure step.

### In CMake

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

# 1. generate once, at configure time
strata_add_project(
  SCHEMA     ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS    ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
  COMPONENTS ${CMAKE_CURRENT_SOURCE_DIR}/components
  PRESET     ${STRATA_PRESET}          # e.g. from -DSTRATA_PRESET=...
)

# 2. register the components this project uses
strata_add_component(ctl LAYER ctl)
strata_add_component(bsp LAYER bsp)

# 3. subscribe a target to a layer's features
add_executable(firmware src/ctlp.c)
strata_link_resolves(firmware ctl)

# 4. read values when the build itself has to decide
strata_get_feature("bsp.TUNNEL_BACKEND" backend)
target_sources(firmware PRIVATE bsp/tunnel_${backend}.c)

strata_get_feature("ctl.SUPPORT_WIRELESS_TUNNEL" has_tunnel)
if(has_tunnel)
  target_link_libraries(firmware PRIVATE tunnel_client)
endif()
```

| Function | Signature | Purpose |
| --- | --- | --- |
| `strata_add_project` | `(SCHEMA <dir> PRESETS <dir> COMPONENTS <dir> PRESET <name> [OUT <dir>])` | Generate at configure time and load feature values into the current scope |
| `strata_add_component` | `(<name> [LAYER <layer>])` | Register a component; creates the imported target `strata::<name>` whose include path is that layer's header directory |
| `strata_link_resolves` | `(<target> <component>...)` | Subscribe a target to the generated views |
| `strata_get_feature` | `(<feature-id> <out-var>)` | Read a feature value for build decisions |
| `strata_get_config` | `(<config-id> <out-var>)` | Read a raw problem-domain value (discouraged) |

Notes:

- `strata_add_project` is a **macro, not a function**: the generated `.cmake` is
  included in the caller's scope, which is what makes `strata_get_feature` work
  later in the same `CMakeLists.txt`. The other four are functions.
- Order matters: project, then components, then targets. `strata_get_feature`
  before `strata_add_project` is an error, not an empty value.
- A change to any schema, preset or resolver file triggers a re-configure
  automatically (`CMAKE_CONFIGURE_DEPENDS`), so the values can never be stale.

### In C and C++

`strata_link_resolves(firmware ctl)` puts the `ctl` layer's header on the
target's include path. Nothing else is needed:

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

All layers use the same header name, so which file `strata_features.h` resolves
to is decided by the include path: a target subscribed to `ctl` cannot name
`bsp`'s features, because that header is not on its path.

### Generated artifacts

```
build/generated/
├── strata_features.cmake     set(STRATA_FEATURE_<id> <value>) for every feature
├── <layer>/strata_features.h #define STRATA_FEATURE_<LAYER>_<NAME> <value>
├── config/strata_config.h    #define STRATA_CONFIG_<ID> <value>
├── config/strata_config.cmake
└── strata_manifest.json      values, provenance, input hashes
```

Names: a feature `ctl.MAX_TUNNEL_SESSIONS` becomes
`STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS` in C and
`STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS` in CMake; a dimension `chip.pioc`
becomes `STRATA_CONFIG_CHIP_PIOC`. The two prefixes never overlap, so the prefix
alone tells you whether you are holding a fact or a capability.

---

## Diagnostics

Errors are English, ASCII only, and shaped like CMake's own, so editors and CI
can jump to the location:

```
CMake Error at configs/presets/daplink_x.toml:2 (strata_add_project):
  Unknown variable "board.has_ble".

  Did you mean "board.has_ble_module"?
```

Hard failures: duplicate declarations, prefix collisions, unknown or missing
preset values, type and range violations, features declared without a resolver
(or the reverse), duplicate feature names, resolvers returning the wrong type,
resolvers that raise.

---

## Requirements

- CMake 3.20 or newer.
- Python 3.11 or newer, standard library only. CMake invokes it during configure;
  you never call it yourself.

---

## License

Copyright (C) 2026 CYK-Dot.

strata is free software, licensed under the **GNU General Public License,
version 3 or (at your option) any later version** (GPL-3.0-or-later). The full
text is in [LICENSE](LICENSE).

You may use, study, modify and redistribute it, including commercially, provided
that derivative works are distributed under the same license and that recipients
can obtain the source. There is no warranty.
