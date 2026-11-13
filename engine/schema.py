# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Problem-domain schema: the vocabulary every component reads."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import StrataError
from .common import line_of, read_toml, type_name, value_matches

ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
VALID_TYPES = ("bool", "int", "float", "string")


@dataclass(frozen=True)
class Dimension:
    id: str
    type: str
    file: Path
    line: int | None = None
    default: Any = None
    has_default: bool = False
    minimum: float | None = None
    maximum: float | None = None
    doc: str | None = None

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}" if self.line else str(self.file)


@dataclass
class Schema:
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)

    def ids(self) -> list[str]:
        return sorted(self.dimensions)


def load(schema_dir: str | Path) -> Schema:
    root = Path(schema_dir)
    if not root.is_dir():
        raise StrataError(f'Schema directory not found: "{root}".', file=root)

    files = sorted(root.glob("*.toml"))
    if not files:
        raise StrataError(f'No schema files (*.toml) in "{root}".', file=root)

    schema = Schema(files=list(files))
    for path in files:
        data = read_toml(path)
        for table in data.get("dimension", []) or []:
            dimension = _parse(table, path)
            previous = schema.dimensions.get(dimension.id)
            if previous is not None:
                raise StrataError(
                    f'Variable "{dimension.id}" is already declared in {previous.where}.',
                    file=path,
                    line=dimension.line,
                    hints=[
                        "A variable may be declared only once, even when the\n"
                        "declarations are identical."
                    ],
                )
            schema.dimensions[dimension.id] = dimension

    _reject_prefix_collisions(schema)
    return schema


def _parse(table: dict, path: Path) -> Dimension:
    identifier = table.get("id")
    if not isinstance(identifier, str) or not ID_RE.match(identifier):
        raise StrataError(
            f'Invalid dimension id: {identifier!r}.',
            file=path,
            line=line_of(path, "id ="),
            hints=['Ids look like "chip.pioc": lowercase words separated by dots.'],
        )
    line = line_of(path, f'id = "{identifier}"') or line_of(path, f'id="{identifier}"')

    kind = table.get("type")
    if kind not in VALID_TYPES:
        raise StrataError(
            f'Variable "{identifier}" has unsupported type {kind!r}.',
            file=path,
            line=line,
            hints=[f"Supported types: {', '.join(VALID_TYPES)}."],
        )

    minimum = maximum = None
    bounds = table.get("range")
    if bounds is not None:
        if kind not in ("int", "float"):
            raise StrataError(
                f'Variable "{identifier}" declares a range but is not numeric.',
                file=path,
                line=line,
            )
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise StrataError(
                f'Variable "{identifier}" has a malformed range.',
                file=path,
                line=line,
                hints=["A range is a two element array: [minimum, maximum]."],
            )
        minimum, maximum = bounds
        if minimum > maximum:
            raise StrataError(
                f'Variable "{identifier}" has a range whose minimum exceeds its maximum.',
                file=path,
                line=line,
            )

    default = table.get("default")
    has_default = "default" in table
    if has_default and not value_matches(default, kind):
        raise StrataError(
            f'Default for "{identifier}" is {type_name(default)}, '
            f"but the variable is declared as {kind}.",
            file=path,
            line=line,
        )
    if has_default and minimum is not None and not (minimum <= default <= maximum):
        raise StrataError(
            f'Default for "{identifier}" is outside its declared range.',
            file=path,
            line=line,
        )

    return Dimension(
        id=identifier,
        type=kind,
        file=path,
        line=line,
        default=default,
        has_default=has_default,
        minimum=minimum,
        maximum=maximum,
        doc=table.get("doc"),
    )


def _reject_prefix_collisions(schema: Schema) -> None:
    """``chip`` and ``chip.pioc`` cannot coexist: the tree would be ambiguous."""
    ids = set(schema.dimensions)
    for identifier, dimension in schema.dimensions.items():
        parts = identifier.split(".")
        for index in range(1, len(parts)):
            prefix = ".".join(parts[:index])
            if prefix in ids:
                other = schema.dimensions[prefix]
                raise StrataError(
                    f'Variable "{identifier}" is nested under "{prefix}", '
                    "which is itself a declared variable.",
                    file=dimension.file,
                    line=dimension.line,
                    hints=[f'"{prefix}" is declared in {other.where}.'],
                )
