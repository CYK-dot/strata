from __future__ import annotations

import pytest

from strata.engine import components as components_engine
from strata.errors import StrataError


def test_discovers_and_loads_resolvers(project):
    paths = project()
    found = components_engine.discover(paths.components)
    assert [component.id for component in found] == ["app"]
    assert sorted(found[0].resolvers) == ["app.DOUBLE", "app.FLAG"]


def test_declared_feature_without_resolver(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
[meta]
component = "app"
layer     = "app"

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
        components_engine.discover(paths.components)
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
        components_engine.discover(paths.components)
    assert 'Feature "app.EXTRA" has a resolver but is not declared' in str(excinfo.value)


def test_component_without_layer(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
[meta]
component = "app"

[[feature]]
name = "app.DOUBLE"
type = "int"

[[feature]]
name = "app.FLAG"
type = "bool"
"""
        }
    )
    with pytest.raises(StrataError) as excinfo:
        components_engine.discover(paths.components)
    assert "does not declare a layer" in str(excinfo.value)


def test_duplicate_feature_across_components(project):
    paths = project(
        {
            "components/other/feature/strata_features.toml": """
[meta]
component = "other"
layer     = "other"

[[feature]]
name = "app.FLAG"
type = "bool"
""",
            "components/other/feature/strata_features.py": """
from strata import feature


@feature("app.FLAG")
def flag(config):
    return True
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        components_engine.discover(paths.components)
    assert 'Feature "app.FLAG" is already declared in' in str(excinfo.value)


def test_resolver_file_syntax_error(project):
    paths = project(
        {"components/app/feature/strata_features.py": "def broken(:\n"}
    )
    with pytest.raises(StrataError) as excinfo:
        components_engine.discover(paths.components)
    assert "Syntax error in resolver file" in str(excinfo.value)
