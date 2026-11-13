# strata

**Separate the problem domain from the solution domain in configuration.**

strata turns statements like *"this board has a BLE module"* into capabilities
like *"this build provides a wireless tunnel"*, and keeps the correspondence in
one reviewable file. CMake and the C/C++ code read the same derived values, so
the build and the sources cannot disagree about what a product supports.

```c
/* before: a control plane reading hardware facts it should not know */
#if defined(MCU_HAS_PIOC) || defined(BOARD_HAS_BLE_MODULE) || defined(BOARD_HAS_AT_ADAPTER)
    tunnel_start(2);
#endif

/* after: a control plane reading a capability */
#if STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL
    tunnel_start(STRATA_FEATURE_CTL_MAX_TUNNEL_SESSIONS);
#endif
```

Whether the tunnel runs over BLE, over programmable logic, or over a UART
adapter stays below the abstraction, where the BSP implements one interface.

---

## When you need it

- **One source tree, several products** that differ in *how* a capability is
  provided, not in *whether* the software offers it.
- **`#if` predicates that mix several hardware facts** (`BOARD_HAS_BLE ||
  MCU_HAS_PIOC`). Every new target edits them again.
- **Build logic and source code drift apart**: CMake picks the sources from one
  set of switches, the C code branches on another.
- **Nobody can answer "why does this build have this feature?"** without reading
  code and datasheets.
- **The mapping itself deserves review**: "PIOC or PLB is enough for JTAG
  offload" is hardware knowledge that today lives inside a preprocessor
  expression, unnamed and untested.

## When you probably don't

- One target and one switch. A CMake `option()` is cheaper and clearer.
- Driver internals. There strata only buys you solved, validated combinations of
  macros; the real payoff is at the layers that promise to be hardware
  agnostic — control plane, protocol stacks, application logic.
- A single build with no variants: the mapping has nothing to map.

---

## Concepts

strata deliberately has a small vocabulary. These are the words used in its
files, its output and its errors.

**Problem domain / schema.** What the target *is*: facts and numbers about the
chip, the board, the product tier. A schema file declares *dimensions*: an id, a
type (`bool`, `int`, `float`, `string`), an optional range, an optional default,
a doc line. The schema is global — components read it, they never extend it.

**Preset.** One complete assignment of those dimensions: "which chip, which
board, which product tier". A preset file is one product. Values not given fall
back to the schema default.

**Config object.** What a resolver receives. `config.chip.pioc`, or
`config["board.has_ble_module"]`. It is also a probe: every read is recorded, so
strata can later say which facts made a feature true.

**Component.** A directory holding `strata_features.toml` (the contract: which
features exist, their types, their docs) next to `strata_features.py` (the
resolvers). A component owns its features and declares one `layer`.

**Feature.** A typed value that both the build system and the code may read:
`ctl.SUPPORT_WIRELESS_TUNNEL`. Feature names are globally unique. A feature is
derived only from problem-domain values — **never from another feature**, which
keeps evaluation order irrelevant and makes cycles impossible.

**Resolver.** The function that computes one feature:

```python
@feature("ctl.SUPPORT_WIRELESS_TUNNEL")
def support_wireless_tunnel(config):
    return config.product.wireless_debug and (
        config.board.has_ble_module
        or config.chip.pioc
        or config.board.has_uart_ble_adapter
    )
```

One feature, one resolver, one owner.

**Layer.** A visibility boundary. Features are emitted per layer into that
layer's own header, so a control-plane target linking only the `ctl` layer cannot
even name `bsp.TUNNEL_BACKEND`. strata does not forbid crossing layers; it just
does not hand you the other layer's macros.

**Views.** The generated artifacts: a CMake view (`strata_features.cmake`) and
per-layer C views (`<layer>/strata_features.h`). Both come from one run, so they
cannot disagree.

**Manifest.** `strata_manifest.json`: every feature with its value, its owning
component, and the config variables that were actually read (`by`), plus the
hashes of every input. This is the answer to "why is this enabled?".

**Escape hatch.** Every problem-domain value is also exported as
`STRATA_CONFIG_*`, for the cases where no honest feature name exists (clock
frequency, flash size). It is available on purpose and discouraged on purpose:
reading it re-couples the code to the hardware. `strata` marks it clearly in the
generated header, and nothing stops you but review.

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

### Command line

```bash
python -m strata generate \
  --schema     configs/schema \
  --presets    configs/presets \
  --components components \
  --preset     daplink_plb \
  --out        build/generated
```

Runs the pipeline for one preset and writes both views plus the manifest.
Requires Python 3.11 or newer; no third-party runtime dependency.

### CMake

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
- Generation runs at configure time, because CMake itself needs the values to
  choose sources. Editing a schema, preset or resolver file triggers a
  re-configure automatically (`CMAKE_CONFIGURE_DEPENDS`).

### Generated artifacts

```
build/generated/
├── strata_features.cmake     set(STRATA_FEATURE_<id> <value>) for every feature
├── <layer>/strata_features.h #define STRATA_FEATURE_<LAYER>_<NAME> <value>
├── config/strata_config.h    #define STRATA_CONFIG_<ID> <value>
├── config/strata_config.cmake
└── strata_manifest.json      values, provenance, input hashes
```

Naming: a feature `ctl.MAX_TUNNEL_SESSIONS` becomes
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

Python 3.11+ (standard library only), CMake 3.20+.

---

## License

strata is free software, licensed under the **GNU General Public License,
version 3**. The full text is in [LICENSE](LICENSE).

This means: you may use, study, modify and redistribute it, including
commercially, provided that derivative works are distributed under the same
license and that users can obtain the source. There is no warranty.
