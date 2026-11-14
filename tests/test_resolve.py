# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

from __future__ import annotations

import pytest

from strata.engine import components as components_engine
from strata.engine import preset as preset_engine
from strata.engine import resolve as resolve_engine
from strata.engine import schema as schema_engine
from strata.errors import StrataError


def _resolve(paths, preset_name: str = "p1"):
    loaded_schema = schema_engine.load(paths.schema)
    loaded_preset = preset_engine.load(paths.presets, preset_name, loaded_schema)
    found = components_engine.load_all(paths.component_dirs)
    return resolve_engine.resolve_all(found, loaded_preset.values)


def test_values_and_reads(project):
    paths = project()
    resolved = {item.declaration.name: item for item in _resolve(paths)}
    assert resolved["app.DOUBLE"].value == 8
    assert resolved["app.DOUBLE"].reads == ["a.count"]
    # a.on is read first and is False, so the and-expression short-circuits.
    assert resolved["app.FLAG"].reads == ["a.on"]
    assert resolved["app.FLAG"].value is False


def test_bool_feature_rejects_int(project):
    paths = project(
        {
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.DOUBLE")
def double(config):
    return config.a.count * 2


@feature("app.FLAG")
def flag(config):
    return 1
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _resolve(paths)
    rendered = str(excinfo.value)
    assert 'Resolver for "app.FLAG" returned int' in rendered
    assert "declared as bool" in rendered


def test_int_feature_rejects_bool(project):
    paths = project(
        {
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.DOUBLE")
def double(config):
    return True


@feature("app.FLAG")
def flag(config):
    return False
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _resolve(paths)
    assert "returned bool, but the feature is declared as int" in str(excinfo.value)


def test_unknown_config_variable_has_a_hint(project):
    paths = project(
        {
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.DOUBLE")
def double(config):
    return config.a.coun * 2


@feature("app.FLAG")
def flag(config):
    return False
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _resolve(paths)
    rendered = str(excinfo.value)
    assert 'Unknown config variable "a.coun"' in rendered
    assert 'Did you mean "a.count"' in rendered


def test_resolver_exception_is_reported_with_origin(project):
    paths = project(
        {
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.DOUBLE")
def double(config):
    return config.a.count // 0


@feature("app.FLAG")
def flag(config):
    return False
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _resolve(paths)
    rendered = str(excinfo.value)
    assert 'Resolver for "app.DOUBLE" raised ZeroDivisionError' in rendered
    assert "strata_features.py:" in rendered


def test_float_accepts_int_and_coerces(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.RATIO"
type = "float"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.RATIO")
def ratio(config):
    return 3
""",
        }
    )
    resolved = _resolve(paths)
    assert resolved[0].value == 3.0
    assert isinstance(resolved[0].value, float)
