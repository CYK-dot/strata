# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Components: contracts in TOML, resolvers in Python.

Components are declared by the build, one call per component:

    strata_add_component(ctl ${CMAKE_CURRENT_SOURCE_DIR}/components/ctl)

so this module never scans a project for them. Inside the declared directory it
looks for ``strata_features.toml`` at any depth, which leaves the layout inside a
component free (``feature/``, ``features/``, whatever the component prefers).
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from ..config import ConfigAccessError
from ..errors import StrataError
from ..feature import checkpoint, since
from .common import line_of, read_toml

DECLARATION_FILE = "strata_features.toml"
RESOLVER_FILE = "strata_features.py"
VALID_TYPES = ("bool", "int", "float", "string")


@dataclass(frozen=True)
class Declaration:
    name: str
    type: str
    file: Path
    line: int | None
    component: str
    layer: str
    doc: str | None = None

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}" if self.line else str(self.file)

    @property
    def local_name(self) -> str:
        return self.name.split(".")[-1]


@dataclass
class Component:
    id: str
    layer: str
    root: Path
    decl_file: Path
    resolver_file: Path
    declarations: list[Declaration] = field(default_factory=list)
    resolvers: dict[str, Callable] = field(default_factory=dict)


def load_all(pairs: Iterable[tuple[str, str | Path]]) -> list[Component]:
    """Load every ``(name, directory)`` the build declared."""
    pairs = list(pairs)
    if not pairs:
        raise StrataError(
            "No components were declared.",
            hints=["Call strata_add_component(<name> <directory>) for each one."],
        )

    components = [_load_component(name, Path(directory)) for name, directory in pairs]
    _load_resolvers(components)
    _validate(components)
    return sorted(components, key=lambda component: component.id)


def _load_component(name: str, root: Path) -> Component:
    if not root.is_dir():
        raise StrataError(f'Component directory not found: "{root}".', file=root)

    declarations = sorted(root.rglob(DECLARATION_FILE))
    if not declarations:
        raise StrataError(
            f'No {DECLARATION_FILE} under "{root}".',
            file=root,
            hints=["A component is a directory holding a declaration file."],
        )
    if len(declarations) > 1:
        listed = "\n".join(f"  {path}" for path in declarations)
        raise StrataError(
            f'Component "{name}" declares more than one {DECLARATION_FILE}:',
            file=root,
            hints=[listed],
        )

    decl_file = declarations[0]
    resolver_file = decl_file.with_name(RESOLVER_FILE)
    if not resolver_file.is_file():
        raise StrataError(
            f'Component has no resolver file "{RESOLVER_FILE}".',
            file=decl_file.parent,
            hints=[
                f'"{DECLARATION_FILE}" and "{RESOLVER_FILE}" must sit in the same directory.'
            ],
        )
    return _parse_component(name, root, decl_file, resolver_file)


def _parse_component(name: str, root: Path, decl_file: Path, resolver_file: Path) -> Component:
    data = read_toml(decl_file)
    meta = data.get("meta", {}) or {}
    layer = meta.get("layer")
    if not isinstance(layer, str) or not layer:
        raise StrataError(
            "Component does not declare a layer.",
            file=decl_file,
            line=line_of(decl_file, "[meta]"),
            hints=['Add a [meta] table with layer = "ctl" (or whatever yours is called).'],
        )

    parsed: list[Declaration] = []
    for table in data.get("feature", []) or []:
        feature_name = table.get("name")
        if not isinstance(feature_name, str) or not feature_name:
            raise StrataError(
                "Feature declaration has no name.",
                file=decl_file,
                line=line_of(decl_file, "[[feature]]"),
            )
        kind = table.get("type")
        if kind not in VALID_TYPES:
            raise StrataError(
                f'Feature "{feature_name}" has unsupported type {kind!r}.',
                file=decl_file,
                line=line_of(decl_file, feature_name),
                hints=[f"Supported types: {', '.join(VALID_TYPES)}."],
            )
        parsed.append(
            Declaration(
                name=feature_name,
                type=kind,
                file=decl_file,
                line=line_of(decl_file, feature_name),
                component=name,
                layer=layer,
                doc=table.get("doc"),
            )
        )

    return Component(
        id=name,
        layer=layer,
        root=root,
        decl_file=decl_file,
        resolver_file=resolver_file,
        declarations=parsed,
    )


def _load_resolvers(components: list[Component]) -> None:
    for index, component in enumerate(components):
        mark = checkpoint()
        module_name = f"_strata_component_{index}_{abs(hash(str(component.resolver_file))) & 0xFFFF:x}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, component.resolver_file)
            if spec is None or spec.loader is None:
                raise StrataError(
                    "Could not load resolver file.", file=component.resolver_file
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except StrataError:
            raise
        except SyntaxError as exc:
            raise StrataError(
                f"Syntax error in resolver file: {exc.msg}",
                file=component.resolver_file,
                line=exc.lineno,
            ) from None
        except ConfigAccessError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a diagnostic
            last = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
            raise StrataError(
                f"Resolver file failed to load: {type(exc).__name__}: {exc}",
                file=component.resolver_file,
                line=last.lineno if last else None,
            ) from None

        for entry in since(mark):
            if entry.name in component.resolvers:
                raise StrataError(
                    f'Feature "{entry.name}" is registered twice in this component.',
                    file=component.resolver_file,
                    hints=[f"First registration at {entry.origin}."],
                )
            component.resolvers[entry.name] = entry.func


def _validate(components: list[Component]) -> None:
    seen: dict[str, Declaration] = {}
    for component in components:
        declared = {decl.name for decl in component.declarations}

        for name in sorted(declared - set(component.resolvers)):
            decl = next(d for d in component.declarations if d.name == name)
            raise StrataError(
                f'Feature "{name}" is declared but has no resolver.',
                file=decl.file,
                line=decl.line,
                hints=[f'Add @feature("{name}") to {component.resolver_file.name}.'],
            )

        for name in sorted(set(component.resolvers) - declared):
            func = component.resolvers[name]
            code = getattr(func, "__code__", None)
            raise StrataError(
                f'Feature "{name}" has a resolver but is not declared.',
                file=component.resolver_file,
                line=code.co_firstlineno if code else None,
                hints=[f'Add it to {component.decl_file.name}, or remove the decorator.'],
            )

        for decl in component.declarations:
            previous = seen.get(decl.name)
            if previous is not None:
                raise StrataError(
                    f'Feature "{decl.name}" is already declared in {previous.where}.',
                    file=decl.file,
                    line=decl.line,
                )
            seen[decl.name] = decl
