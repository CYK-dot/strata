"""The ``@feature`` decorator and its registration buffer.

A component's ``strata_features.py`` declares one resolver per feature:

    @feature("ctl.SUPPORT_WIRELESS_TUNNEL")
    def support_wireless_tunnel(config):
        ...

The decorator may be repeated with different names; function names are local
and carry no meaning beyond readability.
"""

from __future__ import annotations

from typing import Callable, NamedTuple


class Entry(NamedTuple):
    name: str
    func: Callable
    origin: str  # "path/to/strata_features.py:12"


_ENTRIES: list[Entry] = []


def feature(name: str):
    """Register the decorated function as the resolver of ``name``."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("feature() expects a non-empty feature name")

    name = name.strip()

    def register(func: Callable) -> Callable:
        code = getattr(func, "__code__", None)
        origin = f"{code.co_filename}:{code.co_firstlineno}" if code else repr(func)
        _ENTRIES.append(Entry(name, func, origin))
        func.__strata_feature__ = name
        return func

    return register


def checkpoint() -> int:
    """Mark the current end of the buffer, for per-module imports."""
    return len(_ENTRIES)


def since(mark: int) -> list[Entry]:
    return _ENTRIES[mark:]


def entries() -> list[Entry]:
    return list(_ENTRIES)


def clear() -> None:
    """Test helper."""
    _ENTRIES.clear()
