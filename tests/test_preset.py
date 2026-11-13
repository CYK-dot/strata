# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

from __future__ import annotations

import pytest

from strata.engine import preset as preset_engine
from strata.engine import schema as schema_engine
from strata.errors import StrataError


def test_applies_defaults(project):
    paths = project()
    loaded = preset_engine.load(paths.presets, "p1", schema_engine.load(paths.schema))
    assert loaded.values == {"a.on": False, "a.count": 4}
    assert loaded.overrides == {"a.count": 4}


def test_unknown_variable_suggests_a_neighbour(project):
    paths = project(
        {"configs/presets/p2.toml": 'preset = "p2"\na.coun = 3\n'}
    )
    with pytest.raises(StrataError) as excinfo:
        preset_engine.load(paths.presets, "p2", schema_engine.load(paths.schema))
    rendered = str(excinfo.value)
    assert 'Unknown variable "a.coun"' in rendered
    assert 'Did you mean "a.count"' in rendered


def test_missing_required_variable(project):
    paths = project(
        {
            "configs/schema/req.toml": '[[dimension]]\nid = "b.need"\ntype = "int"\n',
            "configs/presets/p2.toml": 'preset = "p2"\n',
        }
    )
    with pytest.raises(StrataError) as excinfo:
        preset_engine.load(paths.presets, "p2", schema_engine.load(paths.schema))
    assert 'Missing value for required variable "b.need"' in str(excinfo.value)


def test_type_mismatch(project):
    paths = project({"configs/presets/p2.toml": 'preset = "p2"\na.count = "many"\n'})
    with pytest.raises(StrataError) as excinfo:
        preset_engine.load(paths.presets, "p2", schema_engine.load(paths.schema))
    assert "is declared as int, but the preset sets a string" in str(excinfo.value)


def test_range_violation(project):
    paths = project({"configs/presets/p2.toml": "preset = \"p2\"\na.count = 99\n"})
    with pytest.raises(StrataError) as excinfo:
        preset_engine.load(paths.presets, "p2", schema_engine.load(paths.schema))
    assert "outside its range" in str(excinfo.value)


def test_unknown_preset_lists_the_alternatives(project):
    paths = project()
    with pytest.raises(StrataError) as excinfo:
        preset_engine.load(paths.presets, "nope", schema_engine.load(paths.schema))
    assert 'Preset "nope" not found' in str(excinfo.value)
    assert "p1" in str(excinfo.value)
