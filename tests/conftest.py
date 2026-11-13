# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Shared fixtures: a throwaway project tree plus a clean feature registry."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DEMO_ROOT = Path(__file__).resolve().parents[2]
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))

from strata.feature import clear as clear_registry  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def write_tree(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


BASE_FILES = {
    "configs/schema/base.toml": """
[[dimension]]
id      = "a.on"
type    = "bool"
default = false

[[dimension]]
id      = "a.count"
type    = "int"
range   = [0, 10]
default = 1
""",
    "configs/presets/p1.toml": """
preset = "p1"
a.count = 4
""",
    "components/app/feature/strata_features.toml": """
[meta]
component = "app"
layer     = "app"

[[feature]]
name = "app.DOUBLE"
type = "int"

[[feature]]
name = "app.FLAG"
type = "bool"
""",
    "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.DOUBLE")
def double(config):
    return config.a.count * 2


@feature("app.FLAG")
def flag(config):
    return config.a.on and config.a.count > 1
""",
}


@pytest.fixture
def project(tmp_path: Path):
    """Create a minimal but complete project; returns its paths."""

    def build(files: dict[str, str] | None = None) -> SimpleNamespace:
        root = tmp_path / "proj"
        root.mkdir(parents=True, exist_ok=True)
        write_tree(root, dict(BASE_FILES))
        if files:
            write_tree(root, files)
        return SimpleNamespace(
            root=root,
            schema=root / "configs" / "schema",
            presets=root / "configs" / "presets",
            components=root / "components",
            out=root / "build" / "generated",
        )

    return build
