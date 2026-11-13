# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""The ``config`` object handed to resolvers.

Resolvers read the effective problem-domain values through attribute access::

    config.chip.pioc
    config["board.has_ble_module"]

Every read is recorded, which is how strata recovers the provenance a plain
function would otherwise lose: ``by: ["chip.pioc"]`` in the manifest.
"""

from __future__ import annotations

import difflib
from typing import Any


class ConfigAccessError(Exception):
    """A resolver asked for a variable the schema does not declare."""

    def __init__(self, path: str, candidates: list[str]) -> None:
        self.path = path
        self.candidates = candidates
        super().__init__(f'Unknown config variable "{path}".')

    @property
    def hint(self) -> str:
        leaf = self.path.rsplit(".", 1)[-1]
        by_leaf = {c.rsplit(".", 1)[-1]: c for c in self.candidates}
        close = difflib.get_close_matches(leaf, list(by_leaf), n=1, cutoff=0.5)
        if close:
            return f'Did you mean "{by_leaf[close[0]]}"?'
        if self.candidates:
            shown = ", ".join(sorted(self.candidates)[:8])
            return f"Available: {shown}."
        return "No variables are declared at this level."


class ConfigNode:
    """A node of the config tree; leaves return their value and record a read."""

    __slots__ = ("_path", "_tree", "_trace")

    def __init__(self, path: tuple[str, ...], tree: dict[str, Any], trace: list[str]) -> None:
        self._path = path
        self._tree = tree
        self._trace = trace

    # -- access ---------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._step(name)

    def __getitem__(self, key: str) -> Any:
        node: Any = self
        for part in key.split("."):
            node = node._step(part)
        return node

    def _step(self, name: str) -> Any:
        if name not in self._tree:
            raise ConfigAccessError(".".join(self._path + (name,)), self._leaves())
        value = self._tree[name]
        if isinstance(value, dict):
            return ConfigNode(self._path + (name,), value, self._trace)
        self._trace.append(".".join(self._path + (name,)))
        return value

    # -- helpers --------------------------------------------------------

    def _leaves(self) -> list[str]:
        out: list[str] = []

        def walk(prefix: tuple[str, ...], tree: dict[str, Any]) -> None:
            for key, value in tree.items():
                path = prefix + (key,)
                if isinstance(value, dict):
                    walk(path, value)
                else:
                    out.append(".".join(path))

        walk(self._path, self._tree)
        return out

    def __repr__(self) -> str:
        where = ".".join(self._path) or "<root>"
        return f"ConfigNode({where})"


def build(values: dict[str, Any], trace: list[str] | None = None) -> ConfigNode:
    """Build the tree from ``{"chip.pioc": False, ...}``."""
    trace = [] if trace is None else trace
    tree: dict[str, Any] = {}
    for dotted, value in values.items():
        parts = dotted.split(".")
        node = tree
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError(f'config variable "{dotted}" collides with "{part}"')
            node = child
        leaf = parts[-1]
        if isinstance(node.get(leaf), dict):
            raise ValueError(f'config variable "{dotted}" collides with a namespace')
        node[leaf] = value
    return ConfigNode((), tree, trace)
