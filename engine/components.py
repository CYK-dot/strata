# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Components: contracts in TOML, resolvers in Python.

Components are declared by the build, one directory per call:

    strata_add_component_path(${CMAKE_CURRENT_SOURCE_DIR}/components/ctl)

so this module never scans a project for them. The component's identity is not
the directory's: the top-level ``component = "ctl"`` line in
``strata_features.toml`` names it, and the top-level ``requires`` line names
the components it reads from. Inside the declared directory the contract file
is looked for at any depth, which leaves the layout inside a component free
(``feature/``, ``features/``, whatever the component prefers).
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from ..config import ConfigAccessError
from ..errors import StrataError
from ..feature import checkpoint, since
from . import graph
from .common import line_of, read_toml

DECLARATION_FILE = "strata_features.toml"
RESOLVER_FILE = "strata_features.py"
VALID_TYPES = ("bool", "int", "float", "string")

COMPONENT_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FEATURE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


@dataclass(frozen=True)
class Declaration:
    name: str
    type: str
    file: Path
    line: int | None
    component: str
    requires: tuple[str, ...] = ()
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
    root: Path
    decl_file: Path
    resolver_file: Path
    requires: list[str] = field(default_factory=list)
    declarations: list[Declaration] = field(default_factory=list)
    resolvers: dict[str, Callable] = field(default_factory=dict)
    takes_view: dict[str, bool] = field(default_factory=dict)


def load_all(directories: Iterable[str | Path]) -> list[Component]:
    """Load every component directory the build declared."""
    directories = list(directories)
    if not directories:
        raise StrataError(
            "No components were declared.",
            hints=["Call strata_add_component_path(<directory>) for each one."],
        )

    components = [_load_component(Path(directory)) for directory in directories]
    _check_unique_components(components)
    _load_resolvers(components)
    _validate(components)
    return sorted(components, key=lambda component: component.id)


def _load_component(root: Path) -> Component:
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
            f'The directory "{root}" holds more than one {DECLARATION_FILE}:',
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
    return _parse_component(root, decl_file, resolver_file)


def _parse_component(root: Path, decl_file: Path, resolver_file: Path) -> Component:
    data = read_toml(decl_file)

    component_id = _parse_component_id(data, decl_file)
    requires = _parse_component_requires(data, component_id, decl_file)
    parsed = _parse_features(data, component_id, decl_file)

    return Component(
        id=component_id,
        root=root,
        decl_file=decl_file,
        resolver_file=resolver_file,
        requires=requires,
        declarations=parsed,
    )


def _parse_component_id(data: dict, decl_file: Path) -> str:
    component_id = data.get("component")
    if not isinstance(component_id, str) or not component_id:
        hints = ['Add component = "<id>" at the top of the file, before any table header.']
        for table in data.get("feature", []) or []:
            if isinstance(table, dict) and "component" in table:
                hints.insert(
                    0,
                    'Found "component" inside a [[feature]] table; keys belong to the\n'
                    "nearest table header, so it must move above the first one.",
                )
                break
        raise StrataError('Component declaration has no "component" name.', file=decl_file, hints=hints)

    if not COMPONENT_ID_RE.match(component_id):
        raise StrataError(
            f'Component id "{component_id}" is not valid; '
            "ids must match [A-Za-z_][A-Za-z0-9_]*.",
            file=decl_file,
            line=line_of(decl_file, f'component = "{component_id}"'),
        )
    return component_id


def _parse_component_requires(data: dict, component_id: str, decl_file: Path) -> list[str]:
    requires = data.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
        raise StrataError(
            f'Component "{component_id}" has a malformed requires; '
            "it must be an array of component ids.",
            file=decl_file,
            line=line_of(decl_file, "requires"),
        )
    duplicated = sorted({item for item in requires if requires.count(item) > 1})
    if duplicated:
        raise StrataError(
            f'Component "{component_id}" lists "{duplicated[0]}" twice in requires.',
            file=decl_file,
            line=line_of(decl_file, "requires"),
        )
    return list(requires)


def _parse_features(data: dict, component_id: str, decl_file: Path) -> list[Declaration]:
    parsed: list[Declaration] = []
    for table in data.get("feature", []) or []:
        feature_name = table.get("name")
        if not isinstance(feature_name, str) or not feature_name:
            raise StrataError(
                "Feature declaration has no name.",
                file=decl_file,
                line=line_of(decl_file, "[[feature]]"),
            )
        _check_feature_id(feature_name, component_id, decl_file)

        kind = table.get("type")
        if kind not in VALID_TYPES:
            raise StrataError(
                f'Feature "{feature_name}" has unsupported type {kind!r}.',
                file=decl_file,
                line=line_of(decl_file, feature_name),
                hints=[f"Supported types: {', '.join(VALID_TYPES)}."],
            )

        requires = table.get("requires", [])
        if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
            raise StrataError(
                f'Feature "{feature_name}" has a malformed requires; '
                "it must be an array of feature ids.",
                file=decl_file,
                line=line_of(decl_file, feature_name),
            )
        duplicated = sorted({item for item in requires if requires.count(item) > 1})
        if duplicated:
            raise StrataError(
                f'Feature "{feature_name}" lists "{duplicated[0]}" twice in requires.',
                file=decl_file,
                line=line_of(decl_file, feature_name),
            )

        parsed.append(
            Declaration(
                name=feature_name,
                type=kind,
                file=decl_file,
                line=line_of(decl_file, f'name = "{feature_name}"') or line_of(decl_file, feature_name),
                component=component_id,
                requires=tuple(requires),
                doc=table.get("doc"),
            )
        )

    names = [declaration.name for declaration in parsed]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise StrataError(
            f'Feature "{duplicated[0]}" is declared twice in this component.',
            file=decl_file,
            line=line_of(decl_file, f'name = "{duplicated[0]}"'),
        )
    return parsed


def _check_feature_id(feature_name: str, component_id: str, decl_file: Path) -> None:
    if not FEATURE_ID_RE.match(feature_name):
        raise StrataError(
            f'Feature id "{feature_name}" is not valid; ids look like '
            '"component.SEGMENT", with each segment matching [A-Za-z_][A-Za-z0-9_]*.',
            file=decl_file,
            line=line_of(decl_file, feature_name),
        )
    if not feature_name.startswith(component_id + "."):
        raise StrataError(
            f'Feature "{feature_name}" is declared by component "{component_id}"; '
            f'feature ids must start with "{component_id}.".',
            file=decl_file,
            line=line_of(decl_file, feature_name),
        )

def _check_unique_components(components: list[Component]) -> None:
    grouped: dict[str, list[Component]] = {}
    for component in components:
        grouped.setdefault(component.id, []).append(component)
    for component_id, group in grouped.items():
        if len(group) > 1:
            files = sorted(str(component.decl_file) for component in group)
            raise StrataError(
                f'Component "{component_id}" is declared twice: {files[0]}, {files[1]}.',
                file=group[0].decl_file,
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
            component.takes_view[entry.name] = _check_signature(
                entry.name, entry.func, component.resolver_file
            )


def _check_signature(name: str, func: Callable, file: Path) -> bool:
    """Validate ``f(config)`` or ``f(config, features)``; True when features are taken."""
    try:
        parameters = list(inspect.signature(func).parameters.values())
    except (TypeError, ValueError):
        parameters = []

    positional = 0
    valid = True
    for parameter in parameters:
        kind = parameter.kind
        if kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            positional += 1
        else:  # *args, **kwargs and keyword-only parameters are all rejected
            valid = False
            break

    if valid and positional in (1, 2):
        return positional == 2
    raise StrataError(
        f'Resolver for "{name}" must take (config) or (config, features).',
        file=file,
        line=_firstlineno(func),
    )


def _firstlineno(func: Callable) -> int | None:
    code = getattr(func, "__code__", None)
    return code.co_firstlineno if code else None


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

    by_id = {component.id: component for component in components}

    for component in components:
        for dependency in component.requires:
            if dependency not in by_id:
                raise StrataError(
                    f'Component "{component.id}" requires "{dependency}", which is not declared.',
                    file=component.decl_file,
                    hints=[f'Add the directory that declares "{dependency}" to the build.'],
                )

    for component in components:
        declared = {decl.name for decl in component.declarations}
        for decl in component.declarations:
            for target in decl.requires:
                if not FEATURE_ID_RE.match(target):
                    if COMPONENT_ID_RE.match(target):
                        raise StrataError(
                            f'Feature "{decl.name}" requires "{target}"; "{target}" '
                            "looks like a component id. Component-level requires "
                            "belong at the top of the file, before any "
                            "[[feature]] table.",
                            file=decl.file,
                            line=decl.line,
                        )
                    raise StrataError(
                        f'Feature "{decl.name}" requires "{target}", '
                        "which is not a valid feature id.",
                        file=decl.file,
                        line=decl.line,
                    )
                if not target.startswith(component.id + "."):
                    raise StrataError(
                        f'Feature "{decl.name}" requires "{target}"; feature-level requires '
                        "may reference only features of the same component.",
                        file=decl.file,
                        line=decl.line,
                    )
                if target not in declared:
                    raise StrataError(
                        f'Feature "{decl.name}" requires "{target}", which is not declared.',
                        file=decl.file,
                        line=decl.line,
                    )

    component_edges = {component.id: list(component.requires) for component in components}
    try:
        graph.topo_order(component_edges)
    except graph.CyclePath as cycle:
        raise StrataError(
            f"Component dependency cycle: {' -> '.join(cycle.path)}.",
            file=by_id[cycle.path[0]].decl_file,
        ) from None

    for component in components:
        feature_edges = {decl.name: list(decl.requires) for decl in component.declarations}
        try:
            graph.topo_order(feature_edges)
        except graph.CyclePath as cycle:
            raise StrataError(
                f"Feature dependency cycle: {' -> '.join(cycle.path)}.",
                file=component.decl_file,
            ) from None

    for component in components:
        component.requires = sorted(set(component.requires))
