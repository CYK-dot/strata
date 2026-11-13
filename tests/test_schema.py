from __future__ import annotations

import pytest

from strata.engine import schema
from strata.errors import StrataError

from conftest import write_tree


def test_merges_multiple_files(project):
    paths = project()
    loaded = schema.load(paths.schema)
    assert loaded.ids() == ["a.count", "a.on"]
    assert loaded.dimensions["a.count"].default == 1


def test_rejects_duplicate_variable(project):
    paths = project(
        {"configs/schema/dup.toml": '[[dimension]]\nid = "a.on"\ntype = "bool"\n'}
    )
    with pytest.raises(StrataError) as excinfo:
        schema.load(paths.schema)
    message = str(excinfo.value)
    assert "already declared in" in message
    assert "CMake Error at" in message


def test_rejects_prefix_collision(project):
    paths = project(
        {
            "configs/schema/collide.toml": (
                '[[dimension]]\nid = "a.b"\ntype = "bool"\ndefault = false\n\n'
                '[[dimension]]\nid = "a.b.c"\ntype = "int"\ndefault = 1\n'
            )
        }
    )
    with pytest.raises(StrataError) as excinfo:
        schema.load(paths.schema)
    assert 'nested under "a.b"' in str(excinfo.value)


def test_rejects_unknown_type(project):
    paths = project(
        {"configs/schema/bad.toml": '[[dimension]]\nid = "b.x"\ntype = "date"\n'}
    )
    with pytest.raises(StrataError) as excinfo:
        schema.load(paths.schema)
    assert "unsupported type" in str(excinfo.value)


def test_rejects_default_of_wrong_type(project):
    paths = project(
        {
            "configs/schema/bad.toml": (
                '[[dimension]]\nid = "b.flag"\ntype = "bool"\ndefault = 1\n'
            )
        }
    )
    with pytest.raises(StrataError) as excinfo:
        schema.load(paths.schema)
    assert "is int, but the variable is declared as bool" in str(excinfo.value)


def test_reports_missing_schema_directory(project, tmp_path):
    with pytest.raises(StrataError) as excinfo:
        schema.load(tmp_path / "nope")
    assert "Schema directory not found" in str(excinfo.value)


def test_tolerates_a_utf8_bom(tmp_path):
    root = tmp_path / "schema"
    root.mkdir()
    (root / "bom.toml").write_bytes(
        b'\xef\xbb\xbf[[dimension]]\nid = "b.x"\ntype = "bool"\ndefault = false\n'
    )
    loaded = schema.load(root)
    assert loaded.ids() == ["b.x"]
