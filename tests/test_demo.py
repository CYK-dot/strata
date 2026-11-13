# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot

"""End to end against the real demo tree shipped next to this package."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.engine import generate

DEMO_PROJECT = Path(__file__).resolve().parents[2]  # demo/

TRUTH = {
    # preset           tunnel  sessions  backend
    "daplink_ble": (True, 2, "ble"),
    "daplink_plb": (True, 1, "plb"),
    "daplink_uart": (True, 1, "uart_ble"),
    "daplink_wired": (False, 0, "none"),
}


@pytest.mark.parametrize("preset_name", sorted(TRUTH))
def test_demo_truth_table(preset_name, tmp_path):
    tunnel, sessions, backend = TRUTH[preset_name]
    result = generate(
        schema_dir=DEMO_PROJECT / "configs" / "schema",
        presets_dir=DEMO_PROJECT / "configs" / "presets",
        components_dir=DEMO_PROJECT / "components",
        preset_name=preset_name,
        out_dir=tmp_path / preset_name,
    )
    assert result.feature("ctl.SUPPORT_WIRELESS_TUNNEL").value is tunnel
    assert result.feature("ctl.MAX_TUNNEL_SESSIONS").value == sessions
    assert result.feature("bsp.TUNNEL_BACKEND").value == backend


def test_short_circuit_shortens_the_trace(tmp_path):
    result = generate(
        schema_dir=DEMO_PROJECT / "configs" / "schema",
        presets_dir=DEMO_PROJECT / "configs" / "presets",
        components_dir=DEMO_PROJECT / "components",
        preset_name="daplink_plb",
        out_dir=tmp_path / "plb",
    )
    reads = result.feature("ctl.SUPPORT_WIRELESS_TUNNEL").reads
    assert reads == ["product.wireless_debug", "board.has_ble_module", "chip.pioc"]
    assert "board.has_uart_ble_adapter" not in reads


def test_layers_are_separated_in_the_generated_headers(tmp_path):
    generate(
        schema_dir=DEMO_PROJECT / "configs" / "schema",
        presets_dir=DEMO_PROJECT / "configs" / "presets",
        components_dir=DEMO_PROJECT / "components",
        preset_name="daplink_ble",
        out_dir=tmp_path / "ble",
    )
    ctl = (tmp_path / "ble" / "ctl" / "strata_features.h").read_text(encoding="utf-8")
    bsp = (tmp_path / "ble" / "bsp" / "strata_features.h").read_text(encoding="utf-8")
    assert "STRATA_FEATURE_CTL_SUPPORT_WIRELESS_TUNNEL" in ctl
    assert "TUNNEL_BACKEND" not in ctl
    assert "STRATA_FEATURE_BSP_TUNNEL_BACKEND" in bsp
    assert "SUPPORT_WIRELESS_TUNNEL" not in bsp
