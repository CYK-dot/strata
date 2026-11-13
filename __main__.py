# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""Command line entry point: ``python -m strata generate ...``."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .engine import generate
from .errors import StrataError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strata",
        description="Separate the problem domain from the solution domain in configuration.",
    )
    parser.add_argument("--version", action="version", version=f"strata {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate", help="resolve features and write the CMake and C views"
    )
    generate_parser.add_argument("--schema", required=True, help="directory of schema declarations")
    generate_parser.add_argument("--presets", required=True, help="directory of presets")
    generate_parser.add_argument("--components", required=True, help="root of the components")
    generate_parser.add_argument("--preset", required=True, help="preset name")
    generate_parser.add_argument("--out", required=True, help="output directory")
    generate_parser.add_argument("--quiet", action="store_true", help="do not print a summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = generate(
            schema_dir=args.schema,
            presets_dir=args.presets,
            components_dir=args.components,
            preset_name=args.preset,
            out_dir=args.out,
        )
    except StrataError as exc:
        print(exc.render(), file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            f'-- strata: preset "{result.preset.name}": '
            f"{len(result.resolved)} features from {len(result.components)} components"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
