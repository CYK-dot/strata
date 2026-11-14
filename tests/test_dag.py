# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""The DAG baseline: what feature-derivation dependencies must and must not do.

Engine-level cases live here. T16 (two directories declaring the same
component) and the resolver/declaration pairing cases of T27 live in
test_components.py; the CMake-level cases T23-T26 and T29 live in
test_cmake_integration.py.
"""

from __future__ import annotations

import json

import pytest

from strata.engine import generate
from strata.errors import StrataError


# -- two-component baseline: lib (leaf) <- app ---------------------------------

TWO_TREE = {
    "components/lib/feature/strata_features.toml": """
component = "lib"

[[feature]]
name = "lib.BASE"
type = "int"

[[feature]]
name = "lib.DOUBLE"
type = "int"
requires = ["lib.BASE"]
""",
    "components/lib/feature/strata_features.py": """
from strata import feature


@feature("lib.BASE")
def base(config):
    return config.a.count


@feature("lib.DOUBLE")
def double(config, features):
    return features.lib.BASE * 2
""",
    "components/app/feature/strata_features.toml": """
component = "app"
requires  = ["lib"]

[[feature]]
name = "app.SUM"
type = "int"
""",
    "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.SUM")
def sum_(config, features):
    return features["lib.BASE"] + features["lib.DOUBLE"]
""",
}


@pytest.fixture
def dag(project):
    paths = project(dict(TWO_TREE))
    paths.component_dirs = [paths.components / "app", paths.components / "lib"]
    return paths


def _generate(paths, name: str = "p1"):
    return generate(
        schema_dir=paths.schema,
        presets_dir=paths.presets,
        components=paths.component_dirs,
        preset_name=name,
        out_dir=paths.out,
    )


def _manifest(paths) -> dict:
    return json.loads((paths.out / "strata_manifest.json").read_text(encoding="utf-8"))


def _values(paths) -> dict:
    return {item.declaration.name: item.value for item in _generate(paths).resolved}


def _load(paths):
    from strata.engine import components as components_engine

    return components_engine.load_all(paths.component_dirs)


# T01 (C1, C7): a leaf component writes only `component`; everything still
# lands in the views even when nobody reads it.
def test_t01_leaf_component(project):
    paths = project()
    _generate(paths)
    assert _values(paths) == {"app.DOUBLE": 8, "app.FLAG": False}
    manifest = _manifest(paths)
    assert manifest["features"]["app.DOUBLE"]["from"] == []
    assert manifest["features"]["app.FLAG"]["from"] == []
    assert manifest["components"]["app"]["requires"] == []
    cmake = (paths.out / "strata_features.cmake").read_text(encoding="utf-8")
    assert "set(STRATA_FEATURE_app.DOUBLE 8)" in cmake
    assert "set(STRATA_FEATURE_app.FLAG OFF)" in cmake


# T02 (C2): component-level requires make the lower component evaluate first.
def test_t02_component_requires_dependency(dag):
    values = _values(dag)
    assert values == {"lib.BASE": 4, "lib.DOUBLE": 8, "app.SUM": 12}
    assert _generate(dag).feature("app.SUM").froms == ["lib.BASE", "lib.DOUBLE"]


# T03 (C2): a transitive cone read: top reads a bottom feature with only mid
# declared as its direct requires.
def test_t03_transitive_cone(project):
    paths = project(
        {
            "components/bottom/feature/strata_features.toml": """
component = "bottom"

[[feature]]
name = "bottom.VALUE"
type = "int"
""",
            "components/bottom/feature/strata_features.py": """
from strata import feature


@feature("bottom.VALUE")
def value(config):
    return config.a.count
""",
            "components/mid/feature/strata_features.toml": """
component = "mid"
requires  = ["bottom"]

[[feature]]
name = "mid.WRAP"
type = "int"
""",
            "components/mid/feature/strata_features.py": """
from strata import feature


@feature("mid.WRAP")
def wrap(config, features):
    return features["bottom.VALUE"] + 1
""",
            "components/top/feature/strata_features.toml": """
component = "top"
requires  = ["mid"]

[[feature]]
name = "top.DIRECT"
type = "int"
""",
            "components/top/feature/strata_features.py": """
from strata import feature


@feature("top.DIRECT")
def direct(config, features):
    return features["bottom.VALUE"] * 10
""",
        }
    )
    paths.component_dirs = [
        paths.components / "top",
        paths.components / "mid",
        paths.components / "bottom",
    ]
    values = _values(paths)
    assert values["top.DIRECT"] == 40
    assert values["mid.WRAP"] == 5
    assert _generate(paths).feature("top.DIRECT").froms == ["bottom.VALUE"]
    assert _manifest(paths)["components"]["top"]["requires"] == ["mid"]


# T04 (C6, R9): reading outside the cone fails, naming reader and target, and
# points at the top-level requires.
def test_t04_read_outside_cone(dag):
    paths = dag
    (paths.components / "app" / "feature" / "strata_features.py").write_text(
        """
from strata import feature


@feature("app.SUM")
def sum_(config, features):
    return features["lib.BASE"]
""",
        encoding="utf-8",
    )
    (paths.components / "app" / "feature" / "strata_features.toml").write_text(
        """
component = "app"

[[feature]]
name = "app.SUM"
type = "int"
""",
        encoding="utf-8",
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    rendered = str(excinfo.value)
    assert 'Feature "app.SUM" reads "lib.BASE", but component "app" does not depend on "lib".' in rendered
    assert 'Add "lib" to the top-level requires of component "app".' in rendered


# T04 variant: the reader may not skip its cone and read a component its
# component never required, even when that component is part of the build.
def test_t04_read_component_outside_the_cone(project):
    paths = project(dict(TWO_TREE))
    paths.component_dirs = [paths.components / "app", paths.components / "lib"]
    (paths.components / "side" / "feature").mkdir(parents=True, exist_ok=True)
    (paths.components / "side" / "feature" / "strata_features.toml").write_text(
        """
component = "side"

[[feature]]
name = "side.X"
type = "bool"
""",
        encoding="utf-8",
    )
    (paths.components / "side" / "feature" / "strata_features.py").write_text(
        """
from strata import feature


@feature("side.X")
def x(config):
    return True
""",
        encoding="utf-8",
    )
    (paths.components / "app" / "feature" / "strata_features.py").write_text(
        """
from strata import feature


@feature("app.SUM")
def sum_(config, features):
    return 1 if features["side.X"] else 0
""",
        encoding="utf-8",
    )
    paths.component_dirs.append(paths.components / "side")
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    assert 'reads "side.X", but component "app" does not depend on "side"' in str(excinfo.value)


# T04 variant: a lower component may not read an upper one.
def test_t04_lower_may_not_read_upper(dag):
    paths = dag
    (paths.components / "lib" / "feature" / "strata_features.py").write_text(
        """
from strata import feature


@feature("lib.BASE")
def base(config, features):
    return features["app.SUM"]


@feature("lib.DOUBLE")
def double(config, features):
    return features.lib.BASE * 2
""",
        encoding="utf-8",
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    assert 'Feature "lib.BASE" reads "app.SUM", but component "lib" does not depend on "app".' in str(
        excinfo.value
    )


# T05 (C6, R9): a same-component sibling that is not in the requires closure.
def test_t05_undeclared_sibling(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.Y"
type = "int"

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.Y")
def y(config):
    return config.a.count


@feature("app.X")
def x(config, features):
    return features["app.Y"] * 3
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    rendered = str(excinfo.value)
    assert 'Feature "app.X" reads "app.Y", but "app.X" does not require "app.Y".' in rendered
    assert 'Add "app.Y" to the requires of "app.X" in strata_features.toml.' in rendered


# T06 (C3): a declared sibling read succeeds.
def test_t06_declared_sibling(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.Y"
type = "int"

[[feature]]
name = "app.X"
type = "int"
requires = ["app.Y"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.Y")
def y(config):
    return config.a.count


@feature("app.X")
def x(config, features):
    return features["app.Y"] * 3
""",
        }
    )
    resolved = {item.declaration.name: item for item in _generate(paths).resolved}
    assert resolved["app.X"].value == 12
    assert resolved["app.X"].froms == ["app.Y"]


# T07 (C3): sibling reads reach through the requires chain: F reads H via G.
def test_t07_sibling_transitive(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.H"
type = "int"

[[feature]]
name = "app.G"
type = "int"
requires = ["app.H"]

[[feature]]
name = "app.F"
type = "int"
requires = ["app.G"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.H")
def h(config):
    return config.a.count


@feature("app.G")
def g(config, features):
    return features["app.H"] + 1


@feature("app.F")
def f(config, features):
    return features["app.H"] * 100
""",
        }
    )
    resolved = {item.declaration.name: item for item in _generate(paths).resolved}
    assert resolved["app.F"].value == 400
    assert resolved["app.F"].froms == ["app.H"]


# T08 (R5): feature-level requires may not cross components.
def test_t08_feature_requires_cross_component(dag):
    paths = dag
    (paths.components / "app" / "feature" / "strata_features.toml").write_text(
        """
component = "app"
requires  = ["lib"]

[[feature]]
name = "app.SUM"
type = "int"
requires = ["lib.BASE"]
""",
        encoding="utf-8",
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert (
        'Feature "app.SUM" requires "lib.BASE"; feature-level requires '
        "may reference only features of the same component." in str(excinfo.value)
    )


# T09 (C6, R9): an unknown feature read fails with the nearest neighbour.
def test_t09_unknown_feature_suggests_neighbour(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.TOTAL"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.TOTAL")
def total(config, features):
    return features["app.TOTLA"]
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    rendered = str(excinfo.value)
    assert 'Unknown feature "app.TOTLA".' in rendered
    assert 'Did you mean "app.TOTAL"?' in rendered


# T10 (C5, R7): feature cycles fail at load with the full path; a self
# reference is a one-node cycle.
def test_t10_feature_cycle(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.A"
type = "int"
requires = ["app.B"]

[[feature]]
name = "app.B"
type = "int"
requires = ["app.A"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.A")
def a(config):
    return 1


@feature("app.B")
def b(config):
    return 2
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert "Feature dependency cycle: app.A -> app.B -> app.A." in str(excinfo.value)


def test_t10_feature_self_reference(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.S"
type = "int"
requires = ["app.S"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.S")
def s(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert "Feature dependency cycle: app.S -> app.S." in str(excinfo.value)


# T11 (C5, R7): component cycles fail at load with the full path.
def test_t11_component_cycle(dag):
    paths = dag
    (paths.components / "lib" / "feature" / "strata_features.toml").write_text(
        """
component = "lib"
requires  = ["app"]

[[feature]]
name = "lib.BASE"
type = "int"

[[feature]]
name = "lib.DOUBLE"
type = "int"
requires = ["lib.BASE"]
""",
        encoding="utf-8",
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert "Component dependency cycle: app -> lib -> app." in str(excinfo.value)


def test_t11_component_self_reference(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"
requires  = ["app"]

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert "Component dependency cycle: app -> app." in str(excinfo.value)


# T12 (R12): component-level requires may not reference an unknown component.
def test_t12_component_requires_unknown(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"
requires  = ["nosuch"]

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert 'Component "app" requires "nosuch", which is not declared.' in str(excinfo.value)


# T13 (R12): duplicate entries are rejected at both levels.
def test_t13_component_requires_duplicate(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"
requires  = ["lib", "lib"]

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert 'Component "app" lists "lib" twice in requires.' in str(excinfo.value)


def test_t13_feature_requires_duplicate(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.Y"
type = "int"

[[feature]]
name = "app.X"
type = "int"
requires = ["app.Y", "app.Y"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.Y")
def y(config):
    return 1


@feature("app.X")
def x(config, features):
    return features["app.Y"]
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert 'Feature "app.X" lists "app.Y" twice in requires.' in str(excinfo.value)


# T14 (R4): a feature id must start with its own component id.
def test_t14_feature_prefix_mismatch(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "lib.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("lib.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert 'Feature "lib.X" is declared by component "app"; feature ids must start with "app.".' in str(
        excinfo.value
    )


# T15 (R2, R3, R4): malformed declarations fail at load.
def test_t15_missing_component(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert 'Component declaration has no "component" name.' in str(excinfo.value)


def test_t15_invalid_component_id(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "1bad"

[[feature]]
name = "1bad.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("1bad.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert 'Component id "1bad" is not valid' in str(excinfo.value)


@pytest.mark.parametrize("feature_id", ["app.2BAD", "app.LOWER-DASH", "app"])
def test_t15_invalid_feature_id(project, feature_id):
    paths = project(
        {
            "components/app/feature/strata_features.toml": f"""
component = "app"

[[feature]]
name = "{feature_id}"
type = "int"
""",
            "components/app/feature/strata_features.py": f"""
from strata import feature


@feature("{feature_id}")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert f'Feature id "{feature_id}" is not valid' in str(excinfo.value)


# T17 (C9): a one-argument resolver receives config only.
def test_t17_one_argument_resolver(project):
    paths = project()
    resolved = {item.declaration.name: item for item in _generate(paths).resolved}
    assert resolved["app.DOUBLE"].value == 8
    assert resolved["app.DOUBLE"].reads == ["a.count"]
    assert resolved["app.DOUBLE"].froms == []


# T18 (C9): a two-argument resolver receives config and the view; both access
# forms reach the same values.
def test_t18_two_argument_resolver_both_access_forms(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.COUNT"
type = "int"

[[feature]]
name = "app.VIA_ATTR"
type = "int"
requires = ["app.COUNT"]

[[feature]]
name = "app.VIA_INDEX"
type = "int"
requires = ["app.COUNT"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.COUNT")
def count(config):
    return config.a.count


@feature("app.VIA_ATTR")
def via_attr(config, features):
    return features.app.COUNT


@feature("app.VIA_INDEX")
def via_index(config, features):
    return features["app.COUNT"]
""",
        }
    )
    resolved = {item.declaration.name: item for item in _generate(paths).resolved}
    assert resolved["app.VIA_ATTR"].value == 4
    assert resolved["app.VIA_INDEX"].value == 4
    assert resolved["app.VIA_ATTR"].froms == ["app.COUNT"]


# T19 (R10): only (config) and (config, features) are accepted, at load time.
@pytest.mark.parametrize(
    "signature",
    [
        "def x():\n    return 1\n",
        "def x(a, b, c):\n    return 1\n",
        "def x(*args):\n    return 1\n",
        "def x(**kwargs):\n    return 1\n",
        "def x(config, *, features):\n    return 1\n",
    ],
)
def test_t19_resolver_signature_rejected(project, signature):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": f"""
from strata import feature


@feature("app.X")
{signature}""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    assert 'Resolver for "app.X" must take (config) or (config, features).' in str(excinfo.value)


# T20 (C8): `from` records first reads in order, deduplicated, across both
# access forms.
def test_t20_from_is_deduplicated_in_first_read_order(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.B"
type = "int"

[[feature]]
name = "app.C"
type = "int"

[[feature]]
name = "app.X"
type = "int"
requires = ["app.B", "app.C"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.B")
def b(config):
    return 1


@feature("app.C")
def c(config):
    return 2


@feature("app.X")
def x(config, features):
    first = features["app.B"]
    again = features.app.B
    third = features["app.C"]
    return first + again + third
""",
        }
    )
    resolved = {item.declaration.name: item for item in _generate(paths).resolved}
    assert resolved["app.X"].froms == ["app.B", "app.C"]


# T21 (C4): declaration order never reaches the products. Same bytes with a
# different --component order must be byte-identical everywhere; reordered
# TOML entries and requires entries change only the input hashes, so the
# derived artifacts are compared with the banner digest and the inputs section
# normalized away.
def test_t21_component_declaration_order_is_irrelevant(project):
    first = project(dict(TWO_TREE), name="one")
    first.component_dirs = [first.components / "app", first.components / "lib"]
    second = project(dict(TWO_TREE), name="two")
    second.component_dirs = [second.components / "lib", second.components / "app"]

    _generate(first)
    _generate(second)
    for name in (
        "strata_features.cmake",
        "strata_features.h",
        "config/strata_config.cmake",
        "config/strata_config.h",
        "strata_manifest.json",
    ):
        assert (first.out / name).read_bytes() == (second.out / name).read_bytes()


def test_t21_toml_entry_and_requires_order_are_irrelevant(project):
    ordered = project(dict(TWO_TREE), name="ordered")
    ordered.component_dirs = [ordered.components / "app", ordered.components / "lib"]

    shuffled = project(
        {
            "components/lib/feature/strata_features.toml": """
component = "lib"

[[feature]]
name = "lib.DOUBLE"
type = "int"
requires = ["lib.BASE"]

[[feature]]
name = "lib.BASE"
type = "int"
""",
            "components/lib/feature/strata_features.py": TWO_TREE[
                "components/lib/feature/strata_features.py"
            ],
            "components/app/feature/strata_features.toml": """
requires  = ["lib"]
component = "app"

[[feature]]
name = "app.SUM"
type = "int"
""",
            "components/app/feature/strata_features.py": TWO_TREE[
                "components/app/feature/strata_features.py"
            ],
        },
        name="shuffled",
    )
    shuffled.component_dirs = [shuffled.components / "lib", shuffled.components / "app"]

    _generate(ordered)
    _generate(shuffled)

    for name in ("strata_features.cmake", "strata_features.h"):
        first = (ordered.out / name).read_text(encoding="utf-8").splitlines()
        second = (shuffled.out / name).read_text(encoding="utf-8").splitlines()
        assert first[2:] == second[2:]  # skip the banner digest line pair

    first_manifest = _manifest(ordered)
    second_manifest = _manifest(shuffled)
    first_manifest.pop("inputs")
    second_manifest.pop("inputs")
    assert first_manifest == second_manifest


# T22 (C8): the manifest carries `from` and component `requires` with sorted
# order and empty arrays.
def test_t22_manifest_from_and_requires(dag):
    _generate(dag)
    manifest = _manifest(dag)
    assert manifest["features"]["app.SUM"]["from"] == ["lib.BASE", "lib.DOUBLE"]
    assert manifest["features"]["lib.DOUBLE"]["from"] == ["lib.BASE"]
    assert manifest["features"]["lib.BASE"]["from"] == []
    assert manifest["components"]["app"]["requires"] == ["lib"]
    assert manifest["components"]["lib"]["requires"] == []


# T28 (R2): `component` after a table header belongs to that table, so the
# top-level declaration is missing.
def test_t28_component_after_a_table_header(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
[[feature]]
name = "app.X"
type = "int"
component = "app"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    rendered = str(excinfo.value)
    assert 'Component declaration has no "component" name.' in rendered
    assert "inside a [[feature]] table" in rendered


# -- view behaviour beyond the matrix ------------------------------------------


# Multi-segment ids must be read by index; the attribute chain stops after the
# first dot.
def test_multi_segment_ids_use_index_access(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.NET.WIDTH"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.NET.WIDTH")
def width(config):
    return config.a.count
""",
        }
    )
    (paths.components / "app" / "feature" / "strata_features.toml").write_text(
        """
component = "app"

[[feature]]
name = "app.NET.WIDTH"
type = "int"

[[feature]]
name = "app.USER"
type = "int"
requires = ["app.NET.WIDTH"]
""",
        encoding="utf-8",
    )
    (paths.components / "app" / "feature" / "strata_features.py").write_text(
        """
from strata import feature


@feature("app.NET.WIDTH")
def width(config):
    return config.a.count


@feature("app.USER")
def user(config, features):
    return features["app.NET.WIDTH"] + 1
""",
        encoding="utf-8",
    )
    resolved = {item.declaration.name: item for item in _generate(paths).resolved}
    assert resolved["app.USER"].value == 5
    assert resolved["app.USER"].froms == ["app.NET.WIDTH"]


def test_attribute_chain_stops_at_the_first_dot(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.NET.WIDTH"
type = "int"

[[feature]]
name = "app.USER"
type = "int"
requires = ["app.NET.WIDTH"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.NET.WIDTH")
def width(config):
    return config.a.count


@feature("app.USER")
def user(config, features):
    return features.app.NET.WIDTH
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    assert 'Unknown feature "app.NET".' in str(excinfo.value)


# A feature may not read itself, even when its own id is declared.
def test_self_read_is_rejected(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config, features):
    return features["app.X"]
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    assert 'Feature "app.X" reads "app.X"; a feature cannot read itself.' in str(excinfo.value)


# The engine-level shape of T29: consuming with an incomplete graph fails.
def test_incomplete_graph_fails_at_generation(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"
requires  = ["lib"]

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config, features):
    return features["lib.BASE"]
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    assert 'Component "app" requires "lib", which is not declared.' in str(excinfo.value)


# A read-time failure names the line that performed the read, not the first
# line of the resolver.
def test_read_error_points_at_the_reading_line(project):
    content = '''
from strata import feature


@feature("app.Y")
def y(config):
    return 1


@feature("app.X")
def x(config, features):
    pad = 1
    return features["app.Y"]
'''
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.Y"
type = "int"

[[feature]]
name = "app.X"
type = "int"
""",
            "components/app/feature/strata_features.py": content,
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _generate(paths)
    reading_line = content.splitlines().index('    return features["app.Y"]') + 1
    assert f"strata_features.py:{reading_line}" in str(excinfo.value)


# `requires = ["lib"]` inside a [[feature]] table gets the targeted hint that
# component-level requires belong at the top of the file.
def test_component_id_in_feature_requires_gets_a_move_hint(project):
    paths = project(
        {
            "components/app/feature/strata_features.toml": """
component = "app"

[[feature]]
name = "app.X"
type = "int"
requires = ["lib"]
""",
            "components/app/feature/strata_features.py": """
from strata import feature


@feature("app.X")
def x(config):
    return 1
""",
        }
    )
    with pytest.raises(StrataError) as excinfo:
        _load(paths)
    rendered = str(excinfo.value)
    assert 'Feature "app.X" requires "lib"; "lib" looks like a component id.' in rendered
    assert "before any [[feature]] table." in rendered
