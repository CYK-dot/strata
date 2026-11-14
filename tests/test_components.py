# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

from __future__ import annotations

import pytest

from strata.engine import components as components_engine
from strata.errors import StrataError


def test_discovers_and_loads_resolvers(project):
    paths = project()
    found = components_engine.load_all(paths.component_dirs)
    assert [component.id for component in found] == ["app"]
    assert sorted(found[0].resolvers) == ["app.DOUBLE", "app.FLAG"]


def test_component_id_comes_from_the_toml_not_the_directory(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "renamed"

[[feature]]
name = "renamed.DOUBLE"
type = "int"

[[feature]]
name = "renamed.FLAG"
type = "bool"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("renamed.DOUBLE")
def double(config):
    return 0


@feature("renamed.FLAG")
def flag(config):
    return False
""",
        }
    )
    found = components_engine.load_all(paths.component_dirs)
    assert found[0].id == "renamed"


def test_declared_feature_without_resolver(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.DOUBLE"
type = "int"

[[feature]]
name = "app.MISSING"
type = "bool"
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        components_engine.load_all(paths.component_dirs)
    assert 'Feature "app.MISSING" is declared but has no resolver' in str(excinfo.value)


def test_resolver_without_declaration(project):
    paths = project(
        {
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.DOUBLE")
def double(config):
    return 0


@feature("app.FLAG")
def flag(config):
    return False


@feature("app.EXTRA")
def extra(config):
    return 1
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        components_engine.load_all(paths.component_dirs)
    assert 'Feature "app.EXTRA" has a resolver but is not declared' in str(excinfo.value)


def test_two_directories_declaring_the_same_component(project):
    paths = project(
        {
            "components/twin/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.FLAG"
type = "bool"
""",
            "components/twin/feature/strata_features.py": """
from strata import feature


@feature("app.FLAG")
def flag(config):
    return True
""",
        }
    )
    paths.component_dirs.append(paths.components / "twin")
    with pytest.raises(StrataError) as excinfo:
        components_engine.load_all(paths.component_dirs)
    message = str(excinfo.value)
    assert 'Component "app" is declared twice:' in message
    listed = message.split(":", 1)[1].rstrip(".")
    first, second = listed.split(",")
    assert first.strip().endswith("strata_features.toml")
    assert second.strip().endswith("strata_features.toml")
    assert first.strip() != second.strip()


def test_same_feature_declared_twice_in_one_component(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.FLAG"
type = "bool"

[[feature]]
name = "app.FLAG"
type = "bool"
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        components_engine.load_all(paths.component_dirs)
    assert 'Feature "app.FLAG" is declared twice in this component.' in str(excinfo.value)


def test_resolver_file_syntax_error(project):
    paths = project(
        {"components/app/feature/strata_features.py": "def broken(:\n"}
    )
    with pytest.raises(StrataError) as excinfo:
        components_engine.load_all(paths.component_dirs)
    assert "Syntax error in resolver file" in str(excinfo.value)
