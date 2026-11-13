# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""The pipeline: schema -> preset -> components -> resolved features -> views."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import components as components_mod
from . import emit
from . import preset as preset_mod
from . import resolve as resolve_mod
from . import schema as schema_mod
from .common import sha256_of


@dataclass
class Result:
    schema: schema_mod.Schema
    preset: preset_mod.Preset
    components: list[components_mod.Component]
    resolved: list[resolve_mod.Resolved]
    inputs: dict[str, str]
    written: list[Path]

    def feature(self, name: str):
        for item in self.resolved:
            if item.declaration.name == name:
                return item
        raise KeyError(name)


def generate(
    schema_dir: str | Path,
    presets_dir: str | Path,
    components: Iterable[tuple[str, str | Path]],
    preset_name: str,
    out_dir: str | Path,
) -> Result:
    schema = schema_mod.load(schema_dir)
    preset = preset_mod.load(presets_dir, preset_name, schema)
    loaded = components_mod.load_all(components)
    resolved = resolve_mod.resolve_all(loaded, preset.values)
    inputs = _inputs(schema_dir, presets_dir, schema, preset, loaded)
    written = emit.write(out_dir, schema, preset, loaded, resolved, inputs)
    return Result(
        schema=schema,
        preset=preset,
        components=loaded,
        resolved=resolved,
        inputs=inputs,
        written=written,
    )


def _inputs(
    schema_dir: str | Path,
    presets_dir: str | Path,
    schema: schema_mod.Schema,
    preset: preset_mod.Preset,
    components: list[components_mod.Component],
) -> dict[str, str]:
    inputs: dict[str, str] = {}

    for path in schema.files:
        inputs[_relative(path, schema_dir)] = sha256_of(path)
    inputs[_relative(preset.file, presets_dir)] = sha256_of(preset.file)
    for component in components:
        for path in (component.decl_file, component.resolver_file):
            inputs[_relative(path, component.root)] = sha256_of(path)
    return dict(sorted(inputs.items()))


def _relative(path: Path, root: str | Path) -> str:
    """Stable, machine independent key such as ``schema/chip.toml``."""
    try:
        base = Path(root).resolve().parent
        return Path(path).resolve().relative_to(base).as_posix()
    except (ValueError, OSError):
        return Path(path).name
