"""Shared helpers for the engine."""

from __future__ import annotations

import tomllib
from pathlib import Path

from ..errors import StrataError


def read_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise StrataError(f"Invalid TOML: {exc}", file=path) from None


def line_of(path: Path, needle: str) -> int | None:
    """First line containing ``needle``; TOML gives us no positions."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    return None


def sha256_of(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def type_name(value: object) -> str:
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "float"
    if type(value) is str:
        return "string"
    return type(value).__name__


def value_matches(value: object, declared: str) -> bool:
    """Strict check: bool is not an int, int is acceptable where float is declared."""
    if declared == "bool":
        return type(value) is bool
    if declared == "int":
        return type(value) is int
    if declared == "float":
        return type(value) is float or type(value) is int
    if declared == "string":
        return type(value) is str
    return False
