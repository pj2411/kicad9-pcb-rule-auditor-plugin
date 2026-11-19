"""
Comprehensive Unit Test Suite for KiCad 9 Automated PCB Net & Silkscreen Design Rule Auditor.

Uses robust mock classes representing KiCad 9 pcbnew geometry and board items.
Verifies trace width thresholds, mechanical grounding, silkscreen readability,
pad overlap detection, dangling stubs, IPC-2221 calculations, and report generation.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, List, Optional

# Ensure project root is in sys.path so 'plugin' can be imported anywhere
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plugin.auditor_engine import (
    AuditReport,
    PcbAuditorEngine,
    RuleCategory,
    Severity,
    Violation,
    from_mm,
    to_mm,
)
from plugin.config import (
    AuditRuleConfig,
    calculate_ipc2221_trace_width,
    load_config_from_file,
    save_config_to_file,
)
from plugin.report_exporter import (
    export_to_csv,
    export_to_json,
    export_to_markdown,
    generate_csv_str,
    generate_json_str,
    generate_markdown_str,
)


# =============================================================================
# Mock KiCad 9 Objects
# =============================================================================

class MockVector:
    def __init__(self, x_iu: int, y_iu: int) -> None:
        self.x = int(x_iu)
        self.y = int(y_iu)


class MockTrack:
    def __init__(
        self,
        net_name: str,
        start_x_mm: float,
        start_y_mm: float,
        end_x_mm: float,
        end_y_mm: float,
        width_mm: float,
        layer: str = "F.Cu",
        is_via: bool = False,
    ) -> None:
        self.net_name = net_name
        self.start = MockVector(from_mm(start_x_mm), from_mm(start_y_mm))
        self.end = MockVector(from_mm(end_x_mm), from_mm(end_y_mm))
        self.width = from_mm(width_mm)
        self.layer = layer
        self.is_via = is_via

    def GetNetname(self) -> str:
        return self.net_name

    def GetWidth(self) -> int:
        return self.width

    def GetStart(self) -> MockVector:
        return self.start

    def GetEnd(self) -> MockVector:
        return self.end

    def GetPosition(self) -> MockVector:
        return self.start

    def GetLayerName(self) -> str:
        return self.layer

    def GetClass(self) -> str:
        return "PCB_VIA" if self.is_via else "PCB_TRACK"

    def GetLength(self) -> int:
        import math
        dx = self.start.x - self.end.x
        dy = self.start.y - self.end.y
        return int(math.hypot(dx, dy))


class MockPad:
    def __init__(
        self,
        net_name: str,
        pos_x_mm: float,
        pos_y_mm: float,
        size_x_mm: float = 1.6,
        size_y_mm: float = 1.6,
        layer: str = "F.Cu",
    ) -> None:
        self.net_name = net_name
        self.position = MockVector(from_mm(pos_x_mm), from_mm(pos_y_mm))
        self.size = MockVector(from_mm(size_x_mm), from_mm(size_y_mm))
        self.layer = layer

    def GetNetname(self) -> str:
        return self.net_name

    def GetPosition(self) -> MockVector:
        return self.position

    def GetSize(self) -> MockVector:
        return self.size

    def GetLayerName(self) -> str:
        return self.layer


class MockText:
    def __init__(
        self,
        text: str,
        pos_x_mm: float,
        pos_y_mm: float,
        height_mm: float = 1.0,
        thickness_mm: float = 0.15,
        layer: str = "F.SilkS",
        visible: bool = True,
    ) -> None:
        self.text = text
        self.position = MockVector(from_mm(pos_x_mm), from_mm(pos_y_mm))
        self.height = from_mm(height_mm)
        self.thickness = from_mm(thickness_mm)
        self.layer = layer
        self.visible = visible

    def GetText(self) -> str:
        return self.text

    def GetPosition(self) -> MockVector:
        return self.position

    def GetTextHeight(self) -> int:
        return self.height

    def GetTextThickness(self) -> int:
        return self.thickness

    def GetLayerName(self) -> str:
        return self.layer

    def IsVisible(self) -> bool:
        return self.visible


class MockFootprint:
    def __init__(
        self,
        reference: str,
        fpid: str,
        pos_x_mm: float,
        pos_y_mm: float,
        pads: Optional[List[MockPad]] = None,
        ref_text: Optional[MockText] = None,
        val_text: Optional[MockText] = None,
    ) -> None:
        self.reference = reference
        self.fpid = fpid
        self.position = MockVector(from_mm(pos_x_mm), from_mm(pos_y_mm))
        self.pads_list = pads or []
        self.ref_text = ref_text or MockText(reference, pos_x_mm, pos_y_mm - 1.5)
        self.val_text = val_text or MockText(fpid, pos_x_mm, pos_y_mm + 1.5)
        self.graphical_items: List[Any] = []

    def GetReference(self) -> str:
        return self.reference

    def GetFPIDAsString(self) -> str:
        return self.fpid

    def GetPosition(self) -> MockVector:
        return self.position

    def Pads(self) -> List[MockPad]:
        return self.pads_list

    def Reference(self) -> MockText:
        return self.ref_text

    def Value(self) -> MockText:
        return self.val_text

    def GraphicalItems(self) -> List[Any]:
        return self.graphical_items


class MockBoard:
    def __init__(self, name: str = "TestBoard_v1.kicad_pcb") -> None:
        self.name = name
        self.tracks: List[Any] = []
        self.footprints: List[MockFootprint] = []
        self.drawings: List[Any] = []

    def GetFileName(self) -> str:
        return self.name

    def GetTracks(self) -> List[Any]:
        return self.tracks

    def GetFootprints(self) -> List[MockFootprint]:
        return self.footprints

    def GetDrawings(self) -> List[Any]:
        return self.drawings


# =============================================================================
# Unit Test Cases
# =============================================================================

class TestKiCadAuditorEngine(unittest.TestCase):
    """Test suite exercising all auditor rules, formulas, and report outputs."""

    def setUp(self) -> None:
        self.config = AuditRuleConfig(
            min_power_trace_width_mm=0.50,
            min_signal_trace_width_mm=0.20,
            min_silkscreen_text_height_mm=0.80,
            min_silkscreen_text_thickness_mm=0.15,
            min_silkscreen_pad_clearance_mm=0.15,
            check_ungrounded_mounting_holes=True,
            check_dangling_tracks=True,
            check_silkscreen_pad_overlap=True,
        )
        self.engine = PcbAuditorEngine(self.config)

    # -------------------------------------------------------------------------
    # Unit Conversions & IPC-2221 Formulas
    # -------------------------------------------------------------------------
    def test_unit_conversions(self) -> None:
        """Verify nanometer to millimeter bidirectional conversion."""
        self.assertEqual(to_mm(1_000_000), 1.0)
        self.assertEqual(to_mm(250_000), 0.25)
        self.assertEqual(from_mm(1.0), 1_000_000)
        self.assertEqual(from_mm(0.50), 500_000)

    def test_ipc2221_trace_width_calculation(self) -> None:
        """Verify empirical IPC-2221 trace width calculations."""
        # 1.0 A current, 10 C rise, 1 oz copper external layer
        w_ext = calculate_ipc2221_trace_width(
            current_amps=1.0, temp_rise_c=10.0, copper_thickness_oz=1.0, is_external=True
        )
        self.assertGreater(w_ext, 0.25)
        self.assertLess(w_ext, 0.35)

        # Internal stripline should require wider trace for same current (worse cooling)
        w_int = calculate_ipc2221_trace_width(
            current_amps=1.0, temp_rise_c=10.0, copper_thickness_oz=1.0, is_external=False
        )
        self.assertGreater(w_int, w_ext)

        # 0 Current edge case
        self.assertEqual(calculate_ipc2221_trace_width(0.0), 0.0)

    def test_power_and_ground_regex_matching(self) -> None:
        """Verify standard power and ground rail regex classifications."""
        self.assertTrue(self.config.is_power_net("+3V3"))
        self.assertTrue(self.config.is_power_net("+5V"))
        self.assertTrue(self.config.is_power_net("+12V"))
        self.assertTrue(self.config.is_power_net("VCC"))
        self.assertTrue(self.config.is_power_net("VDD_CORE"))
        self.assertTrue(self.config.is_power_net("VBAT"))
        self.assertTrue(self.config.is_power_net("PWR_MAIN"))

        self.assertTrue(self.config.is_ground_net("GND"))
        self.assertTrue(self.config.is_ground_net("AGND"))
        self.assertTrue(self.config.is_ground_net("PGND"))
        self.assertTrue(self.config.is_ground_net("EARTH"))
        self.assertTrue(self.config.is_ground_net("CHASSIS"))

        # Signals should NOT match
        self.assertFalse(self.config.is_power_net("SPI_SCK"))
        self.assertFalse(self.config.is_power_net("UART_TX"))
        self.assertFalse(self.config.is_ground_net("I2C_SDA"))

    # -------------------------------------------------------------------------
    # Rule 1 & 2: Power and Signal Trace Widths
    # -------------------------------------------------------------------------
    def test_power_trace_width_violation(self) -> None:
        """Undersized power trace (0.35mm vs 0.50mm min) must trigger PWR001 with WARNING."""
        board = MockBoard()
        # Moderately undersized +5V trace with 0.35mm width (0.30 <= width < 0.50)
        trk_bad = MockTrack("+5V", 0.0, 0.0, 10.0, 0.0, width_mm=0.35)
        # Properly sized +3V3 trace with 0.60mm width
        trk_good = MockTrack("+3V3", 0.0, 5.0, 10.0, 5.0, width_mm=0.60)
        board.tracks.extend([trk_bad, trk_good])

        report = self.engine.audit_board(board)
        pwr_violations = [v for v in report.violations if v.rule_id == "PWR001"]

        self.assertEqual(len(pwr_violations), 1)
        self.assertEqual(pwr_violations[0].net_name, "+5V")
        self.assertEqual(pwr_violations[0].severity, Severity.WARNING)

    def test_severe_power_trace_width_error(self) -> None:
        """Very narrow power trace (<60% threshold, <0.30mm) should be Severity.ERROR."""
        board = MockBoard()
        trk_critical = MockTrack("VCC", 0.0, 0.0, 10.0, 0.0, width_mm=0.15)
        board.tracks.append(trk_critical)

        report = self.engine.audit_board(board)
        pwr_violations = [v for v in report.violations if v.rule_id == "PWR001"]

        self.assertEqual(len(pwr_violations), 1)
        self.assertEqual(pwr_violations[0].severity, Severity.ERROR)

    def test_signal_trace_width_violation(self) -> None:
        """Signal trace thinner than minimum signal threshold must trigger SIG001."""
        board = MockBoard()
        # Normal signal with 0.25mm width (Passes)
        trk_pass = MockTrack("SPI_MISO", 0.0, 0.0, 5.0, 0.0, width_mm=0.25)
        # Narrow signal with 0.12mm width (<0.20mm threshold)
        trk_fail = MockTrack("USB_DP", 0.0, 2.0, 5.0, 2.0, width_mm=0.12)
        board.tracks.extend([trk_pass, trk_fail])

        report = self.engine.audit_board(board)
        sig_violations = [v for v in report.violations if v.rule_id == "SIG001"]

        self.assertEqual(len(sig_violations), 1)
        self.assertEqual(sig_violations[0].net_name, "USB_DP")
        self.assertEqual(sig_violations[0].severity, Severity.WARNING)

    # -------------------------------------------------------------------------
    # Rule 3: Mechanical Mounting Holes
    # -------------------------------------------------------------------------
    def test_ungrounded_plated_mounting_hole(self) -> None:
        """Plated mounting hole unconnected or not tied to GND must trigger MCH001."""
        board = MockBoard()
        # H1: Plated pad with no net / unconnected
        pad_unconnected = MockPad(net_name="", pos_x_mm=10.0, pos_y_mm=10.0)
        h1 = MockFootprint("H1", "MountingHole_3.2mm_M3_Pad", 10.0, 10.0, pads=[pad_unconnected])

        # H2: Plated pad tied to GND (Valid)
        pad_gnd = MockPad(net_name="GND", pos_x_mm=50.0, pos_y_mm=10.0)
        h2 = MockFootprint("H2", "MountingHole_3.2mm_M3_Pad", 50.0, 10.0, pads=[pad_gnd])

        # H3: Mechanical non-plated hole (No pads -> MCH002 Info)
        h3 = MockFootprint("H3", "MountingHole_3.2mm_M3", 10.0, 50.0, pads=[])

        board.footprints.extend([h1, h2, h3])

        report = self.engine.audit_board(board)
        mch001 = [v for v in report.violations if v.rule_id == "MCH001"]
        mch002 = [v for v in report.violations if v.rule_id == "MCH002"]

        self.assertEqual(len(mch001), 1)
        self.assertEqual(mch001[0].actual_value, "Net: 'None'")
        self.assertEqual(len(mch002), 1)
        self.assertEqual(mch002[0].severity, Severity.INFO)

    # -------------------------------------------------------------------------
    # Rule 4: Floating Vias
    # -------------------------------------------------------------------------
    def test_floating_via_detection(self) -> None:
        """Via with unassigned net or 0 net code must trigger VIA001."""
        board = MockBoard()
        via_unconnected = MockTrack("", 15.0, 15.0, 15.0, 15.0, width_mm=0.6, is_via=True)
        via_valid = MockTrack("GND", 20.0, 20.0, 20.0, 20.0, width_mm=0.6, is_via=True)
        board.tracks.extend([via_unconnected, via_valid])

        report = self.engine.audit_board(board)
        via_violations = [v for v in report.violations if v.rule_id == "VIA001"]

        self.assertEqual(len(via_violations), 1)
        self.assertEqual(via_violations[0].category, RuleCategory.FLOATING_VIA)

    # -------------------------------------------------------------------------
    # Rule 5: Silkscreen Readability
    # -------------------------------------------------------------------------
    def test_silkscreen_readability(self) -> None:
        """Silkscreen font height <0.80mm or thickness <0.15mm must trigger SLK001."""
        board = MockBoard()
        # Reference text too small (height 0.50mm)
        tiny_ref = MockText("R1", 10.0, 10.0, height_mm=0.50, thickness_mm=0.10, layer="F.SilkS")
        fp = MockFootprint("R1", "Resistor_SMD:R_0805", 10.0, 10.0, ref_text=tiny_ref)
        board.footprints.append(fp)

        # Standalone drawing text too thin (thickness 0.08mm)
        thin_dwg = MockText("LOGO", 5.0, 5.0, height_mm=1.0, thickness_mm=0.08, layer="F.SilkS")
        board.drawings.append(thin_dwg)

        report = self.engine.audit_board(board)
        silk_violations = [v for v in report.violations if v.rule_id == "SLK001"]

        self.assertEqual(len(silk_violations), 2)
        for v in silk_violations:
            self.assertEqual(v.category, RuleCategory.SILKSCREEN_READABILITY)

    # -------------------------------------------------------------------------
    # Rule 6: Silkscreen Pad Overlap
    # -------------------------------------------------------------------------
    def test_silkscreen_pad_overlap(self) -> None:
        """Silkscreen text placed directly over an SMD solder pad must trigger SLK002."""
        board = MockBoard()
        # Pad at (20.0, 20.0)
        pad = MockPad(net_name="NET_A", pos_x_mm=20.0, pos_y_mm=20.0, size_x_mm=1.5, size_y_mm=1.5, layer="F.Cu")
        # Text overlapping at (20.1, 20.1)
        overlap_ref = MockText("R2", 20.1, 20.1, height_mm=1.0, thickness_mm=0.15, layer="F.SilkS")
        fp = MockFootprint("R2", "R_0805", 20.0, 20.0, pads=[pad], ref_text=overlap_ref)
        board.footprints.append(fp)

        report = self.engine.audit_board(board)
        overlap_violations = [v for v in report.violations if v.rule_id == "SLK002"]

        self.assertEqual(len(overlap_violations), 1)
        self.assertEqual(overlap_violations[0].severity, Severity.ERROR)

    # -------------------------------------------------------------------------
    # Rule 7: Dangling Track Stub
    # -------------------------------------------------------------------------
    def test_dangling_track_detection(self) -> None:
        """An isolated track segment with open endpoint and no connected pad must trigger TRK001."""
        board = MockBoard()
        # Pad at (0.0, 0.0)
        pad = MockPad(net_name="SIG_1", pos_x_mm=0.0, pos_y_mm=0.0)
        fp = MockFootprint("U1", "SOIC-8", 0.0, 0.0, pads=[pad])
        board.footprints.append(fp)

        # Track from (0.0, 0.0) to (5.0, 0.0). End at (5.0, 0.0) is dangling!
        stub_track = MockTrack("SIG_1", 0.0, 0.0, 5.0, 0.0, width_mm=0.25)
        board.tracks.append(stub_track)

        report = self.engine.audit_board(board)
        stub_violations = [v for v in report.violations if v.rule_id == "TRK001"]

        self.assertEqual(len(stub_violations), 1)
        self.assertAlmostEqual(stub_violations[0].pos_x_mm, 5.0, places=1)

    # -------------------------------------------------------------------------
    # Configuration Persistence & Profiles
    # -------------------------------------------------------------------------
    def test_config_serialization(self) -> None:
        """Verify configuration round-trip to/from dictionary and JSON file."""
        cfg = AuditRuleConfig(
            min_power_trace_width_mm=0.80,
            target_current_amps=2.5,
            power_net_patterns=["^VCC_CUSTOM.*", "^VDD_5V.*"],
        )
        data = cfg.to_dict()
        self.assertEqual(data["min_power_trace_width_mm"], 0.80)
        self.assertEqual(data["target_current_amps"], 2.5)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            path = tf.name

        try:
            save_config_to_file(cfg, path)
            loaded_cfg = load_config_from_file(path)
            self.assertEqual(loaded_cfg.min_power_trace_width_mm, 0.80)
            self.assertEqual(loaded_cfg.target_current_amps, 2.5)
            self.assertTrue(loaded_cfg.is_power_net("VCC_CUSTOM_BUS"))
        finally:
            if os.path.exists(path):
                os.remove(path)

    # -------------------------------------------------------------------------
    # Report Exporters (JSON, CSV, Markdown)
    # -------------------------------------------------------------------------
    def test_report_exporters(self) -> None:
        """Verify JSON, CSV, and Markdown generation and file export integrity."""
        board = MockBoard("PowerSupply_v2.kicad_pcb")
        trk_bad = MockTrack("+12V", 0.0, 0.0, 10.0, 0.0, width_mm=0.20)
        board.tracks.append(trk_bad)

        report = self.engine.audit_board(board)

        # 1. JSON
        json_str = generate_json_str(report)
        json_data = json.loads(json_str)
        self.assertEqual(json_data["board_name"], "PowerSupply_v2.kicad_pcb")
        self.assertGreaterEqual(json_data["summary"]["total_violations"], 1)

        # 2. CSV
        csv_str = generate_csv_str(report)
        self.assertIn("Rule ID,Category,Severity", csv_str)
        self.assertIn("+12V", csv_str)

        # 3. Markdown
        md_str = generate_markdown_str(report)
        self.assertIn("# KiCad 9 Automated Power & Signal Net Rule Audit", md_str)
        self.assertIn("PowerSupply_v2.kicad_pcb", md_str)
        self.assertIn("PWR001", md_str)

        # 4. File export verification
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_file = os.path.join(tmp_dir, "test.json")
            csv_file = os.path.join(tmp_dir, "test.csv")
            md_file = os.path.join(tmp_dir, "test.md")

            export_to_json(report, json_file)
            export_to_csv(report, csv_file)
            export_to_markdown(report, md_file)

            self.assertTrue(os.path.isfile(json_file))
            self.assertTrue(os.path.isfile(csv_file))
            self.assertTrue(os.path.isfile(md_file))


if __name__ == "__main__":
    unittest.main()
