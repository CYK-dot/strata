# strata

A CMake configuration generator that derives software features from a description of the target.

Most projects of any size carry two kinds of knowledge in the same places: what
the target hardware *is* — which chip, which board, which options were fitted —
and what the software *provides* for a given build. The two get welded together
in preprocessor expressions, and every new product edits code that was supposed
to be independent of the hardware.

strata keeps them apart. The target is described as data; the software's
features are derived from that description by functions that live next to the
component they belong to. The derivation is written once, so it can be reviewed,
explained and tested, instead of being copied into every use site.

The derived features are typed values that both the build system and the C/C++
code read, from the same generated files. Changing the target description changes
what gets compiled and what gets enabled, without either side learning how the
hardware happens to provide a capability.

It pays off when one codebase has to produce several products. It is not worth it
for a single target with a single switch — a CMake `option()` is cheaper.

## Table of Contents

- [Install](#install)
- [Usage](#usage)
- [Concepts](#concepts)
- [What strata is not](#what-strata-is-not)
- [Diagnostics](#diagnostics)
- [API](#api)
- [Contributing](#contributing)
- [License](#license)

## Install

strata is not a package you install; it is a directory you vendor into the
project it serves, and it brings its own history.

```
your-project/
├── strata/                 this repository
├── configs/                target descriptions and presets
├── components/             features and the functions that derive them
└── CMakeLists.txt
```

Dependencies:

- CMake 3.20 or newer
- Python 3.11 or newer, standard library only. CMake invokes it during the
  configure step; you never call it yourself.

## Usage

Enable it once, near the top of `CMakeLists.txt`:

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

strata_add_project(
  SCHEMA     ${CMAKE_CURRENT_SOURCE_DIR}/configs/schema
  PRESETS    ${CMAKE_CURRENT_SOURCE_DIR}/configs/presets
  COMPONENTS ${CMAKE_CURRENT_SOURCE_DIR}/components
  PRESET     ${STRATA_PRESET}          # e.g. from -DSTRATA_PRESET=...
)

strata_add_component(ctl LAYER ctl)
strata_add_component(bsp LAYER bsp)

add_executable(firmware src/ctlp.c)
strata_link_resolves(firmware ctl)

strata_get_feature("bsp.TUNNEL_BACKEND" backend)
target_sources(firmware PRIVATE bsp/tunnel_${backend}.c)
```

Then the code includes one header and reads the features:

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

What is behind a feature — a BLE module, a programmable I/O controller, a UART
adapter — never reaches this file.

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

## What strata is not

| It is not | Because |
| --- | --- |
| A configuration manager | It does not own where values come from, how they are stored, or how they are distributed |
| A Kconfig replacement | Kconfig's symbols share one flat namespace and cannot express which layer owns them; strata's whole point is that boundary |
| A build system | It compiles nothing; it produces input that CMake consumes |
| A runtime switch service | It covers build-time and compile-time decisions only, never what a running device does |
| An enforcement mechanism | It provides the layered path and makes the other path visible; it does not block it |

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

## API

### CMake functions

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

### Generated files

```
build/generated/
├── strata_features.cmake     set(STRATA_FEATURE_<id> <value>) for every feature
├── <layer>/strata_features.h #define STRATA_FEATURE_<LAYER>_<NAME> <value>
├── config/strata_config.h    #define STRATA_CONFIG_<ID> <value>
├── config/strata_config.cmake
└── strata_manifest.json      values, provenance, input hashes
```

All layers use the same header name, so which file `strata_features.h` resolves
to is decided by the include path: a target subscribed to `ctl` cannot name
`bsp`'s features, because that header is not on its path.

Naming: a feature `ctl.MAX_TUNNEL_SESSIONS` becomes
`STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS` in C and
`STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS` in CMake; a dimension `chip.pioc`
becomes `STRATA_CONFIG_CHIP_PIOC`. The two prefixes never overlap, so the prefix
alone tells you whether you are holding a fact or a capability.

## Contributing

Issues and pull requests are welcome. The test suite runs with pytest and needs
nothing beyond Python 3.11:

```sh
python -m pytest -q
```

Please keep the generated output deterministic: the tests compare two runs
byte for byte.

## License

Copyright (C) 2026 CYK-Dot.

GPL-3.0-or-later — GNU General Public License, version 3 or any later version.
The full text is in [LICENSE](LICENSE).
