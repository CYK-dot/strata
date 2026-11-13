"""Presets: one file, one complete set of problem-domain values."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import StrataError
from .common import line_of, read_toml, type_name, value_matches
from .schema import Schema

RESERVED_KEYS = {"preset"}


@dataclass
class Preset:
    name: str
    file: Path
    overrides: dict[str, Any] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)


def load(presets_dir: str | Path, name: str, schema: Schema) -> Preset:
    root = Path(presets_dir)
    if not root.is_dir():
        raise StrataError(f'Preset directory not found: "{root}".', file=root)

    path = root / f"{name}.toml"
    if not path.is_file():
        available = sorted(p.stem for p in root.glob("*.toml"))
        raise StrataError(
            f'Preset "{name}" not found in "{root}".',
            file=root,
            hints=[
                "Available presets: " + (", ".join(available) if available else "none") + "."
            ],
        )

    data = read_toml(path)
    flat = _flatten(data)
    for key in RESERVED_KEYS:
        flat.pop(key, None)

    overrides: dict[str, Any] = {}
    for identifier, value in flat.items():
        dimension = schema.dimensions.get(identifier)
        if dimension is None:
            close = difflib.get_close_matches(identifier, schema.ids(), n=1, cutoff=0.6)
            hints = []
            if close:
                hints.append(f'Did you mean "{close[0]}"?')
            raise StrataError(
                f'Unknown variable "{identifier}".',
                file=path,
                line=line_of(path, identifier.rsplit(".", 1)[-1]),
                hints=hints,
            )
        if not value_matches(value, dimension.type):
            raise StrataError(
                f'Variable "{identifier}" is declared as {dimension.type}, '
                f"but the preset sets a {type_name(value)}.",
                file=path,
                line=line_of(path, identifier.rsplit(".", 1)[-1]),
                hints=[f"Declared in {dimension.where}."],
            )
        if dimension.minimum is not None and not (
            dimension.minimum <= value <= dimension.maximum
        ):
            raise StrataError(
                f'Value {value} for "{identifier}" is outside its range '
                f"[{dimension.minimum}, {dimension.maximum}].",
                file=path,
                line=line_of(path, identifier.rsplit(".", 1)[-1]),
                hints=[f"Declared in {dimension.where}."],
            )
        overrides[identifier] = value

    values: dict[str, Any] = {}
    missing: list[str] = []
    for identifier, dimension in schema.dimensions.items():
        if identifier in overrides:
            values[identifier] = overrides[identifier]
        elif dimension.has_default:
            values[identifier] = dimension.default
        else:
            missing.append(identifier)

    if missing:
        missing.sort()
        raise StrataError(
            f'Missing value for required variable "{missing[0]}".',
            file=path,
            hints=_missing_hint(missing, schema),
        )

    return Preset(name=name, file=path, overrides=overrides, values=values)


def _missing_hint(missing: list[str], schema: Schema) -> list[str]:
    hints = [
        "The variable has no default. Set it in the preset, or declare a\n"
        "default in its schema file."
    ]
    if len(missing) > 1:
        hints.append("Also missing: " + ", ".join(missing[1:]) + ".")
    where = schema.dimensions[missing[0]].where
    hints.append(f"Declared in {where}.")
    return hints


def _flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted + "."))
        else:
            flat[dotted] = value
    return flat
