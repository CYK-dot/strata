# strata

Turns configuration items into named features that CMake and C/C++ code read.

Configuration items pile up quickly: chip model, board revision, customer tier,
region, optional hardware, build profile. The build and the code have to turn
those items into decisions, and the usual way is to read them directly — `#ifdef`
in the sources, `if()` in CMake.

That works while there are two items. As they grow:

- the predicates grow with the items and with their combinations, and the same
  decision is copied into every place that needs it;
- the code speaks the configuration's vocabulary, so a new chip or a new customer
  tier means editing code that had no business knowing those words;
- the build and the sources decide independently, and nothing keeps them in step;
- nobody can answer "why is this enabled in this build?" without reading both.

**The idea.** Nothing above the configuration should read the items. Derive what
it needs instead.

strata makes that derivation a layer of its own. Each component declares the
features it exposes — named, typed values in the software's own vocabulary — and
writes the function that derives each one from the configuration items. strata
evaluates the declarations once and emits the result as a CMake file and as one C
header per layer. The build and the code read features, never items: adding a
chip, a tier or a region becomes a new derivation instead of an edit to code that
should not care.

Hardware is the usual first case — several different chips can provide the same
capability — but nothing in strata is specific to hardware. Any configuration
with more than one answer fits the same shape.

It pays off when one codebase has to serve several configurations. It is not
worth it for a single build with a single switch — a CMake `option()` is cheaper.

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
├── configs/                configuration items and presets
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

Which configuration item made the feature true — a BLE module, a programmable
I/O controller, a customer tier — never reaches this file.

## Concepts

The vocabulary is deliberately small. These are the words that appear in strata's
files, output and errors.

| Term | Definition | What matters |
| --- | --- | --- |
| **Configuration schema** | The global vocabulary of configuration items: ids, types, ranges, defaults and docs | Components read it; they never extend it. Ids are globally unique |
| **Configuration item** | One declared value, e.g. `chip.pioc`, `board.uart_count`, `tier.pro` | Typed: `bool`, `int`, `float` or `string`. Its meaning belongs to whoever owns that domain |
| **Preset** | One complete assignment of items — one product, one deployment, one customer | Anything not given falls back to the schema default |
| **Component** | A directory holding `strata_features.toml` (contract) next to `strata_features.py` (resolvers) | Owns its features and declares one `layer` |
| **Feature** | A named, typed value derived from configuration items, readable by both the build and the code, e.g. `ctl.SUPPORT_WIRELESS_TUNNEL` | This is the software's vocabulary, not the configuration's. Globally unique; depends on items only, **never on another feature** |
| **Resolver** | The function that computes one feature: `@feature("...")` and `(config) -> value` | One feature, one resolver, one owner |
| **config object** | The configuration view handed to a resolver (`config.chip.pioc`) | Every read is recorded — this is how provenance is recovered |
| **Layer** | A visibility boundary for features | Emitted into that layer's own header; crossing layers is possible but not handed to you |
| **Views** | The generated artifacts: one CMake view, one C header per layer | Produced by one run, so they cannot disagree |
| **Manifest** | `strata_manifest.json`: values, owners, the items read (`by`), input hashes | The answer to "why is this enabled?" |
| **Escape hatch** | Every configuration item, exported as `STRATA_CONFIG_*` | Available on purpose, discouraged on purpose: reading it re-couples the code to the raw vocabulary |

## What strata is not

| It is not | Because |
| --- | --- |
| A configuration manager | It does not own where values come from, how they are stored, or how they are distributed |
| A Kconfig replacement | Kconfig's symbols share one flat namespace and cannot express which layer owns them; strata's whole point is that boundary |
| A build system | It compiles nothing; it produces input that CMake consumes |
| A runtime switch service | It covers build-time and compile-time decisions only, never what a running device does |
| An enforcement mechanism | It provides the layered path and makes the other path visible; it does not block it |
| A hardware tool | Hardware is the usual first case, not the subject. Any configuration with more than one answer fits the same shape |

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
| `strata_get_config` | `(<config-id> <out-var>)` | Read a raw configuration item (discouraged) |

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
`STRATA_FEATURE_ctl.MAX_TUNNEL_SESSIONS` in CMake; a configuration item
`chip.pioc` becomes `STRATA_CONFIG_CHIP_PIOC`. The two prefixes never overlap, so
the prefix alone tells you whether you are holding an item or a feature.

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
