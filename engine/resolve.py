# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Run resolvers, capture reads, check declared types.

A resolver sees configuration items and nothing else: features are never inputs
to other features. That single hop is what removes ordering from the system —
there is no dependency graph to sort and no cycle to detect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import ConfigAccessError, build
from ..errors import StrataError
from .common import type_name, value_matches
from .components import Component, Declaration


@dataclass
class Resolved:
    declaration: Declaration
    value: Any
    reads: list[str]


def resolve_all(components: list[Component], config_values: dict[str, Any]) -> list[Resolved]:
    resolved: list[Resolved] = []
    for component in components:
        for declaration in component.declarations:
            resolver = component.resolvers[declaration.name]
            trace: list[str] = []
            node = build(config_values, trace)
            try:
                raw = resolver(node)
            except ConfigAccessError as exc:
                raise StrataError(
                    str(exc.args[0]),
                    file=declaration.file,
                    line=declaration.line,
                    hints=[exc.hint],
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

            resolved.append(
                Resolved(
                    declaration=declaration,
                    value=_coerce(raw, declaration),
                    reads=list(dict.fromkeys(trace)),
                )
            )
    return resolved


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
