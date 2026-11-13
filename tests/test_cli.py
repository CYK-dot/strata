# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

from __future__ import annotations

from strata.__main__ import main


def test_generate_succeeds_and_reports_a_summary(project, capsys):
    paths = project()
    code = main(
        [
            "generate",
            "--schema",
            str(paths.schema),
            "--presets",
            str(paths.presets),
            "--components",
            str(paths.components),
            "--preset",
            "p1",
            "--out",
            str(paths.out),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert 'preset "p1": 2 features from 1 components' in out


def test_failure_uses_the_cmake_diagnostic_shape(project, capsys):
    paths = project({"configs/presets/p2.toml": 'preset = "p2"\na.coun = 3\n'})
    code = main(
        [
            "generate",
            "--schema",
            str(paths.schema),
            "--presets",
            str(paths.presets),
            "--components",
            str(paths.components),
            "--preset",
            "p2",
            "--out",
            str(paths.out),
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("CMake Error at ")
    assert "(strata_add_project):" in err
    assert 'Unknown variable "a.coun"' in err
