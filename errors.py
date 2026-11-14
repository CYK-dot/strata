# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Diagnostics, rendered in CMake's own style.

    CMake Error at configs/presets/daplink_x.toml:2 (strata_project):
      Unknown variable "board.has_ble".

      Did you mean "board.has_ble_module"? It is declared in
      schema/board.toml:3.
"""

from __future__ import annotations

from typing import Sequence

DEFAULT_COMMAND = "strata_project"


class StrataError(Exception):
    """One diagnostic, addressed to a file and line where one is known."""

    def __init__(
        self,
        message: str,
        *,
        file: object | None = None,
        line: int | None = None,
        hints: Sequence[str] = (),
        command: str = DEFAULT_COMMAND,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.file = str(file) if file is not None else None
        self.line = line
        self.hints = list(hints)
        self.command = command

    def render(self) -> str:
        location = self.file or "<strata>"
        if self.line is not None:
            location = f"{location}:{self.line}"
        out = [f"CMake Error at {location} ({self.command}):"]
        out.extend(f"  {text}" for text in self.message.splitlines())
        for hint in self.hints:
            out.append("")
            out.extend(f"  {text}" for text in hint.splitlines())
        return "\n".join(out)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.render()


def join_lines(items: Sequence[str], indent: str = "  ") -> str:
    """Render a short list for the body of a diagnostic."""
    return "\n".join(indent + item for item in items)
