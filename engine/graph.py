# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Dependency graphs: topological order, transitive closure, cycle paths.

Both the component graph and the per-component feature graph use the same
shape: ``edges[node]`` lists the ids ``node`` depends on. Evaluation runs the
dependencies first; ties are broken by id, so the order is a function of the
graph alone and never of declaration order.
"""

from __future__ import annotations

import heapq
from typing import Iterable


class CyclePath(Exception):
    """A directed cycle, as the node list from start back to start."""

    def __init__(self, path: list[str]) -> None:
        super().__init__(" -> ".join(path))
        self.path = path


def topo_order(edges: dict[str, list[str]]) -> list[str]:
    """Kahn topological order: dependencies first, ties by id.

    Raises :class:`CyclePath` when the graph is not acyclic; the path names the
    cycle from one node back to itself.
    """
    cleaned = {node: sorted(set(deps)) for node, deps in edges.items()}
    indegree = {node: len(deps) for node, deps in cleaned.items()}
    dependents: dict[str, list[str]] = {node: [] for node in cleaned}
    for node, deps in cleaned.items():
        for dep in deps:
            dependents[dep].append(node)

    ready = [node for node, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)

    if len(order) != len(cleaned):
        raise CyclePath(_cycle_of(cleaned, set(cleaned) - set(order)))
    return order


def closure(starts: Iterable[str], edges: dict[str, list[str]]) -> set[str]:
    """Transitive closure over dependency edges, starting from ``starts``.

    The starts themselves are part of the result; callers pass the direct
    dependencies, so the direct ones are included and the start node only
    shows up if the graph actually leads back to it.
    """
    seen: set[str] = set(starts)
    stack = list(starts)
    while stack:
        node = stack.pop()
        for dep in edges.get(node, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def _cycle_of(edges: dict[str, list[str]], remaining: set[str]) -> list[str]:
    """One deterministic cycle among the leftover nodes, as ``a -> ... -> a``.

    After Kahn, every leftover node still has at least one unmet dependency
    inside ``remaining``, so the walk always closes.
    """
    current = min(remaining)
    path = [current]
    while True:
        current = min(dep for dep in edges[current] if dep in remaining)
        if current in path:
            return path[path.index(current):] + [current]
        path.append(current)
