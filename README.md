# strata

Separate the **problem domain** (what the target is) from the **solution domain**
(what the software provides), and keep the mapping between them in one reviewable
place. The build system and the C/C++ code both read the derived features.

This directory is the tool; everything around it is a demo that uses it.

## Layout

```
strata/
├── __init__.py        exposes @feature and __version__
├── __main__.py        python -m strata generate ...
├── feature.py         the @feature decorator and its registry
├── config.py          the config object handed to resolvers (reads are traced)
├── errors.py          CMake style diagnostics
├── engine/
│   ├── schema.py      loads configs/schema/*.toml
│   ├── preset.py      loads one preset, applies defaults, validates
│   ├── components.py  finds components, loads resolvers, cross-checks
│   ├── resolve.py     runs resolvers, checks types, records provenance
│   └── emit.py        writes the CMake view, the per-layer C views, the manifest
└── cmake/strata.cmake the five CMake integration functions
```

## Use

```bash
python -m strata generate \
  --schema configs/schema \
  --presets configs/presets \
  --components components \
  --preset daplink_plb \
  --out build/generated
```

From CMake:

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/strata/cmake)
include(strata)

strata_add_project(SCHEMA ... PRESETS ... COMPONENTS ... PRESET ${STRATA_PRESET})
strata_add_component(ctl LAYER ctl)
strata_link_resolves(firmware ctl)
strata_get_feature("ctl.SUPPORT_WIRELESS_TUNNEL" has_tunnel)
```

## Test

```bash
cd demo
python -m pytest strata/tests -q
```

Requires Python 3.11+ (stdlib `tomllib`). No third party runtime dependency.
