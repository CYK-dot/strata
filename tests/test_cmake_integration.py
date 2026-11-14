# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""CMake integration: what ``strata_project`` + ``strata_add_component_path``
must do in a real configure.

Each test drives a scratch project. No language is enabled, so no compiler is
needed; the tests only exercise the strata module and its generated views. The
module locates its own package, so the tests set no PYTHONPATH and make no
assumption about the directory layout. Skipped when CMake is missing or no
usable generator (Ninja / MinGW Makefiles / Unix Makefiles) is present.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STRATA_PARENT = Path(__file__).resolve().parents[2]  # the directory holding the strata package


def _pick_generator() -> str | None:
    if shutil.which("ninja"):
        return "Ninja"
    if shutil.which("mingw32-make"):
        return "MinGW Makefiles"
    if shutil.which("make"):
        return "Unix Makefiles"
    return None


GENERATOR = _pick_generator()

pytestmark = [
    pytest.mark.skipif(shutil.which("cmake") is None, reason="cmake not on PATH"),
    pytest.mark.skipif(GENERATOR is None, reason="no usable generator (ninja/make)"),
]

SCHEMA_TOML = """
[[dimension]]
id      = "a.count"
type    = "int"
range   = [0, 10]
default = 1
"""
PRESET_TOML = """
preset = "p1"
a.count = 4
"""
LIB_TOML = """
component = "lib"

[[feature]]
name = "lib.BASE"
type = "int"

[[feature]]
name = "lib.DOUBLE"
type = "int"
requires = ["lib.BASE"]
"""
LIB_PY = """
from strata import feature


@feature("lib.BASE")
def base(config):
    return config.a.count


@feature("lib.DOUBLE")
def double(config, features):
    return features.lib.BASE * 2
"""
APP_TOML = """
component = "app"
requires  = ["lib"]

[[feature]]
name = "app.SUM"
type = "int"
"""
APP_PY = """
from strata import feature


@feature("app.SUM")
def sum_(config, features):
    return features["lib.BASE"] + features["lib.DOUBLE"]
"""

CMAKELISTS_TAIL = """\
include(strata)

strata_project(
  SCHEMA  {schema}
  PRESETS {presets}
)

strata_add_component_path({components}/c_app)
strata_add_component_path({components}/c_lib)

strata_get_feature("lib.DOUBLE" scratch_double)
message(STATUS "SCRATCH_DOUBLE=${{scratch_double}}")
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _project(root: Path) -> Path:
    _write(root / "configs" / "schema" / "base.toml", SCHEMA_TOML)
    _write(root / "configs" / "presets" / "p1.toml", PRESET_TOML)
    _write(root / "components" / "c_app" / "feature" / "strata_features.toml", APP_TOML)
    _write(root / "components" / "c_app" / "feature" / "strata_features.py", APP_PY)
    _write(root / "components" / "c_lib" / "feature" / "strata_features.toml", LIB_TOML)
    _write(root / "components" / "c_lib" / "feature" / "strata_features.py", LIB_PY)
    return root


def _write_cmakelists(root: Path, body: str) -> None:
    """Assemble a CMakeLists with plain joins; no brace-escaping traps."""
    lines = [
        "cmake_minimum_required(VERSION 3.20)",
        "project(scratch NONE)",
        "",
        f"list(APPEND CMAKE_MODULE_PATH {(STRATA_PARENT / 'strata' / 'cmake').as_posix()})",
        body.format(
            schema=(root / "configs" / "schema").as_posix(),
            presets=(root / "configs" / "presets").as_posix(),
            components=(root / "components").as_posix(),
        ),
    ]
    _write(root / "CMakeLists.txt", "\n".join(lines))


def _configure(root: Path, build: Path, preset: str = "p1") -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "cmake",
            "-S",
            str(root),
            "-B",
            str(build),
            "-G",
            GENERATOR,
            f"-DSTRATA_PRESET={preset}",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        encoding="utf-8",
        errors="replace",
    )


def _configure_text(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout + proc.stderr


# T23 (C1): strata_project plus directories only; the component names come
# from the TOML files, not from the directory names.
def test_t23_project_and_component_paths(tmp_path):
    root = _project(tmp_path / "proj")
    _write_cmakelists(root, CMAKELISTS_TAIL)
    proc = _configure(root, tmp_path / "build")
    assert proc.returncode == 0, _configure_text(proc)

    manifest = json.loads(
        (tmp_path / "build" / "generated" / "strata_manifest.json").read_text(encoding="utf-8")
    )
    assert sorted(manifest["components"]) == ["app", "lib"]
    assert manifest["components"]["app"]["requires"] == ["lib"]
    assert manifest["features"]["app.SUM"]["owner"] == "app"


# T24 (C7): the generated header carries the intermediate features too.
def test_t24_header_contains_intermediate_features(tmp_path):
    root = _project(tmp_path / "proj")
    _write_cmakelists(root, CMAKELISTS_TAIL)
    proc = _configure(root, tmp_path / "build")
    assert proc.returncode == 0, _configure_text(proc)

    header = (tmp_path / "build" / "generated" / "strata_features.h").read_text(encoding="utf-8")
    assert "#define STRATA_FEATURE_LIB_BASE 4" in header
    assert "#define STRATA_FEATURE_LIB_DOUBLE 8" in header
    assert "#define STRATA_FEATURE_APP_SUM 12" in header


# T25 (C10): the build can read an intermediate feature.
def test_t25_build_reads_intermediate_feature(tmp_path):
    root = _project(tmp_path / "proj")
    _write_cmakelists(root, CMAKELISTS_TAIL)
    proc = _configure(root, tmp_path / "build")
    assert proc.returncode == 0, _configure_text(proc)
    assert "SCRATCH_DOUBLE=8" in proc.stdout


# T26 (—): failures render in the CMake diagnostic shape, in English ASCII,
# and fail the configure step.
def test_t26_failure_diagnostic_shape(tmp_path):
    root = _project(tmp_path / "proj")
    _write(
        root / "components" / "c_app" / "feature" / "strata_features.toml",
        """
component = "app"
requires  = ["nosuch"]

[[feature]]
name = "app.SUM"
type = "int"
""",
    )
    _write_cmakelists(root, CMAKELISTS_TAIL)
    proc = _configure(root, tmp_path / "build")
    output = _configure_text(proc)
    assert proc.returncode != 0
    assert "CMake Error at " in output
    assert 'Component "app" requires "nosuch", which is not declared.' in output
    assert "strata: generation failed" in output
    diagnostic_start = output.index("CMake Error at ")
    assert output[diagnostic_start:].isascii()


# T29 (R8): all strata_add_component_path calls must precede the first
# consumer; consuming before the graph is complete fails the configure.
def test_t29_consume_before_component_paths(tmp_path):
    root = _project(tmp_path / "proj")
    _write_cmakelists(
        root,
        """\
include(strata)

strata_project(
  SCHEMA  {schema}
  PRESETS {presets}
)

strata_add_component_path({components}/c_app)
strata_get_feature("app.SUM" scratch_sum)

strata_add_component_path({components}/c_lib)
""",
    )
    proc = _configure(root, tmp_path / "build")
    output = _configure_text(proc)
    assert proc.returncode != 0
    assert 'Component "app" requires "lib", which is not declared.' in output
