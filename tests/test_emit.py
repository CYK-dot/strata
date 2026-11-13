from __future__ import annotations

import json

from strata.engine import generate


def _generate(paths, name: str = "p1"):
    return generate(
        schema_dir=paths.schema,
        presets_dir=paths.presets,
        components_dir=paths.components,
        preset_name=name,
        out_dir=paths.out,
    )


def test_writes_all_views(project):
    paths = project()
    _generate(paths)
    assert (paths.out / "strata_features.cmake").is_file()
    assert (paths.out / "app" / "strata_features.h").is_file()
    assert (paths.out / "config" / "strata_config.h").is_file()
    assert (paths.out / "config" / "strata_config.cmake").is_file()
    assert (paths.out / "strata_manifest.json").is_file()


def test_cmake_view_uses_the_documented_prefixes(project):
    paths = project()
    _generate(paths)
    text = (paths.out / "strata_features.cmake").read_text(encoding="utf-8")
    assert "set(STRATA_FEATURE_app.DOUBLE 8)" in text

    config = (paths.out / "config" / "strata_config.cmake").read_text(encoding="utf-8")
    assert "set(STRATA_CONFIG_a.count 4)" in config
    assert "set(STRATA_CONFIG_a.on OFF)" in config


def test_layer_header_only_carries_its_layer(project):
    paths = project()
    _generate(paths)
    header = (paths.out / "app" / "strata_features.h").read_text(encoding="utf-8")
    assert "#define STRATA_FEATURE_APP_DOUBLE 8" in header
    assert "STRATA_CONFIG_" not in header


def test_manifest_records_provenance(project):
    paths = project()
    _generate(paths)
    manifest = json.loads((paths.out / "strata_manifest.json").read_text(encoding="utf-8"))
    assert manifest["preset"] == "p1"
    assert manifest["features"]["app.DOUBLE"]["value"] == 8
    assert manifest["features"]["app.DOUBLE"]["by"] == ["a.count"]
    assert manifest["features"]["app.FLAG"]["by"] == ["a.on"]
    assert "schema/base.toml" in manifest["inputs"]


def test_output_is_byte_identical_between_runs(project):
    paths = project()
    _generate(paths)
    first = {
        path.relative_to(paths.out).as_posix(): path.read_bytes()
        for path in paths.out.rglob("*")
        if path.is_file()
    }
    _generate(paths)
    second = {
        path.relative_to(paths.out).as_posix(): path.read_bytes()
        for path in paths.out.rglob("*")
        if path.is_file()
    }
    assert first == second
    assert not any(b"\r\n" in blob for blob in first.values())


def test_different_presets_produce_different_values(project):
    paths = project({"configs/presets/p2.toml": 'preset = "p2"\na.count = 2\n'})
    _generate(paths, "p1")
    one = (paths.out / "strata_features.cmake").read_text(encoding="utf-8")
    _generate(paths, "p2")
    two = (paths.out / "strata_features.cmake").read_text(encoding="utf-8")
    assert "set(STRATA_FEATURE_app.DOUBLE 8)" in one
    assert "set(STRATA_FEATURE_app.DOUBLE 4)" in two
