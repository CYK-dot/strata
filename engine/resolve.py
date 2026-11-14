# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Run resolvers in dependency order, capture reads, check declared types.

Two graphs order the work. Components run dependencies-first (their top-level
``requires``); inside a component, features run dependencies-first (their
feature-level ``requires``). While a feature runs it may read the features of
the components its component depends on (the cone) and the siblings its own
``requires`` chain reaches — nothing else. Every read is recorded: config
reads become ``by``, feature reads become ``from``.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from ..config import ConfigAccessError, build
from ..errors import StrataError
from . import graph
from .common import type_name, value_matches
from .components import Component, Declaration

DECLARATION_NAME = "strata_features.toml"


class FeatureAccessError(Exception):
    """A resolver read a feature it may not read, or one that does not exist."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class Resolved:
    declaration: Declaration
    value: Any
    reads: list[str]  # config reads -> manifest "by"
    froms: list[str]  # feature reads -> manifest "from"


def resolve_all(components: list[Component], config_values: dict[str, Any]) -> list[Resolved]:
    if not components:
        return []
    by_id = {component.id: component for component in components}
    component_edges = {component.id: list(component.requires) for component in components}
    component_order = _ordered(component_edges, "Component", by_id[sorted(by_id)[0]].decl_file)
    owner = {
        declaration.name: component.id
        for component in components
        for declaration in component.declarations
    }
    cone = {
        component.id: graph.closure(component.requires, component_edges)
        for component in components
    }

    values: dict[str, Any] = {}
    resolved: list[Resolved] = []
    for component_id in component_order:
        component = by_id[component_id]
        feature_edges = {declaration.name: list(declaration.requires) for declaration in component.declarations}
        feature_order = _ordered(feature_edges, "Feature", component.decl_file)
        readable = {name for name, id_ in owner.items() if id_ in cone[component_id]}

        for name in feature_order:
            declaration = next(d for d in component.declarations if d.name == name)
            resolver = component.resolvers[name]
            siblings = graph.closure(declaration.requires, feature_edges)
            trace_by: list[str] = []
            trace_from: list[str] = []
            node = build(config_values, trace_by)
            view = FeatureView(
                reader=name,
                component=component_id,
                allowed=readable | siblings,
                owner=owner,
                values=values,
                trace=trace_from,
            )
            try:
                if component.takes_view[name]:
                    raw = resolver(node, view)
                else:
                    raw = resolver(node)
            except ConfigAccessError as exc:
                raise StrataError(
                    str(exc.args[0]),
                    file=declaration.file,
                    line=declaration.line,
                    hints=[exc.hint],
                ) from None
            except FeatureAccessError as exc:
                raise StrataError(
                    exc.message,
                    file=component.resolver_file,
                    line=_reading_line(exc, component.resolver_file) or _firstlineno(resolver),
                    hints=[exc.hint] if exc.hint else (),
                ) from None
            except StrataError:
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced as a diagnostic
                code = getattr(resolver, "__code__", None)
                raise StrataError(
                    f'Resolver for "{declaration.name}" raised '
                    f"{type(exc).__name__}:\n\n  {exc}",
                    file=component.resolver_file,
                    line=code.co_firstlineno if code else None,
                ) from None

            values[name] = _coerce(raw, declaration)
            resolved.append(
                Resolved(
                    declaration=declaration,
                    value=values[name],
                    reads=list(dict.fromkeys(trace_by)),
                    froms=list(dict.fromkeys(trace_from)),
                )
            )
    return resolved


def _ordered(edges: dict[str, list[str]], what: str, file: object) -> list[str]:
    try:
        return graph.topo_order(edges)
    except graph.CyclePath as cycle:  # pragma: no cover - load_all rejects cycles first
        raise StrataError(
            f"{what} dependency cycle: {' -> '.join(cycle.path)}.", file=file
        ) from None


def _firstlineno(func) -> int | None:
    code = getattr(func, "__code__", None)
    return code.co_firstlineno if code else None


def _reading_line(exc: FeatureAccessError, resolver_file) -> int | None:
    """The line of the resolver that was executing when the failed read happened.

    The caught exception's traceback walks from this frame down to the raise
    inside the view; the resolver's frame is the one between them.
    """
    filename = str(resolver_file)
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == filename:
            return tb.tb_lineno
        tb = tb.tb_next
    return None


class FeatureView:
    """The read-only view of already-evaluated features handed to a resolver.

    ``view["ctl.X"]`` always works; ``view.ctl.X`` works when the id has
    exactly one dot. Every successful read is appended to ``trace``.
    """

    __slots__ = ("_reader", "_component", "_allowed", "_owner", "_values", "_trace")

    def __init__(
        self,
        reader: str,
        component: str,
        allowed: set[str],
        owner: dict[str, str],
        values: dict[str, Any],
        trace: list[str],
    ) -> None:
        self._reader = reader
        self._component = component
        self._allowed = allowed
        self._owner = owner
        self._values = values
        self._trace = trace

    def __getitem__(self, feature_id: object) -> Any:
        if not isinstance(feature_id, str):
            raise FeatureAccessError("A feature id must be a string.")
        return self._read(feature_id)

    def __getattr__(self, prefix: str) -> Any:
        if prefix.startswith("_"):
            raise AttributeError(prefix)
        return _FeatureGroup(self, prefix)

    def _read(self, feature_id: str) -> Any:
        if feature_id == self._reader:
            raise FeatureAccessError(
                f'Feature "{self._reader}" reads "{feature_id}"; a feature cannot read itself.'
            )
        if feature_id not in self._owner:
            raise FeatureAccessError(f'Unknown feature "{feature_id}".', _unknown_hint(feature_id, self._owner))
        if feature_id not in self._allowed:
            if self._owner[feature_id] == self._component:
                raise FeatureAccessError(
                    f'Feature "{self._reader}" reads "{feature_id}", '
                    f'but "{self._reader}" does not require "{feature_id}".',
                    f'Add "{feature_id}" to the requires of "{self._reader}" '
                    f"in {DECLARATION_NAME}.",
                )
            other = self._owner[feature_id]
            raise FeatureAccessError(
                f'Feature "{self._reader}" reads "{feature_id}", '
                f'but component "{self._component}" does not depend on "{other}".',
                f'Add "{other}" to the top-level requires of component "{self._component}".',
            )
        self._trace.append(feature_id)
        return self._values[feature_id]


class _FeatureGroup:
    """One attribute hop of the view; the id is assembled piece by piece."""

    __slots__ = ("_view", "_prefix")

    def __init__(self, view: FeatureView, prefix: str) -> None:
        self._view = view
        self._prefix = prefix

    def __getattr__(self, segment: str) -> Any:
        if segment.startswith("_"):
            raise AttributeError(segment)
        return self._view._read(f"{self._prefix}.{segment}")

    def __getitem__(self, key: object) -> Any:
        if not isinstance(key, str):
            raise FeatureAccessError("A feature id must be a string.")
        return self._view._read(f"{self._prefix}.{key}")


def _unknown_hint(feature_id: str, owner: dict[str, str]) -> str | None:
    candidates = sorted(owner)
    close = difflib.get_close_matches(feature_id, candidates, n=1, cutoff=0.5)
    if close:
        return f'Did you mean "{close[0]}"?'
    if candidates:
        return "Available: " + ", ".join(candidates[:8]) + "."
    return None


def _coerce(value: Any, declaration: Declaration) -> Any:
    if value_matches(value, declaration.type):
        return float(value) if declaration.type == "float" else value
    raise StrataError(
        f'Resolver for "{declaration.name}" returned {type_name(value)}, '
        f"but the feature is declared as {declaration.type} "
        f"in {declaration.file.name}:{declaration.line}.",
        file=declaration.file,
        line=declaration.line,
    )
