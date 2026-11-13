"""Run resolvers, capture reads, check declared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import ConfigAccessError, build
from ..errors import StrataError
from .common import value_matches
from .components import Component, Declaration


@dataclass
class Resolved:
    declaration: Declaration
    value: Any
    reads: list[str]


def resolve_all(components: list[Component], values: dict[str, Any]) -> list[Resolved]:
    resolved: list[Resolved] = []
    for component in components:
        for declaration in component.declarations:
            func = component.resolvers[declaration.name]
            trace: list[str] = []
            node = build(values, trace)
            try:
                raw = func(node)
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
                code = getattr(func, "__code__", None)
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
    from .common import type_name

    raise StrataError(
        f'Resolver for "{declaration.name}" returned {type_name(value)}, '
        f"but the feature is declared as {declaration.type} "
        f"in {declaration.file.name}:{declaration.line}.",
        file=declaration.file,
        line=declaration.line,
    )
