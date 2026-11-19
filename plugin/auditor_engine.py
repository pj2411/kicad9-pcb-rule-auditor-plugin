"""
Auditor Engine module for KiCad 9 Automated PCB Net & Silkscreen Design Rule Auditor.

Provides core rule evaluation routines decoupled from the wxPython GUI.
Supports direct execution in headless mode, unit testing with mock boards,
and live execution inside KiCad 9 pcbnew.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .config import AuditRuleConfig


def to_mm(iu: int | float) -> float:
    """
    Convert internal KiCad units (nanometers in KiCad 6/7/8/9) to millimeters.
    Safely falls back to 1 IU = 1 nm = 1e-6 mm if pcbnew is not imported.
    """
    try:
        import pcbnew
        return float(pcbnew.ToMM(int(iu)))
    except (ImportError, AttributeError):
        return float(iu) / 1_000_000.0


def from_mm(mm: float) -> int:
    """
    Convert millimeters to internal KiCad units (nanometers).
    """
    try:
        import pcbnew
        return int(pcbnew.FromMM(float(mm)))
    except (ImportError, AttributeError):
        return int(round(float(mm) * 1_000_000.0))


class Severity(str, Enum):
    """Violation severity levels."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class RuleCategory(str, Enum):
    """Categorization of audit rules."""
    POWER_TRACE_WIDTH = "Power Trace Width"
    SIGNAL_TRACE_WIDTH = "Signal Trace Width"
    UNGROUNDED_MECHANICAL = "Ungrounded Mechanical / Hole"
    FLOATING_VIA = "Floating / Unconnected Via"
    SILKSCREEN_READABILITY = "Silkscreen Readability"
    SILKSCREEN_PAD_OVERLAP = "Silkscreen Pad Overlap"
    DANGLING_TRACK = "Dangling Track / Stub"


@dataclass
class Violation:
    """
    Structured representation of a single design rule violation.
    """
    rule_id: str
    category: RuleCategory
    severity: Severity
    net_name: str
    item_type: str
    layer: str
    pos_x_mm: float
    pos_y_mm: float
    actual_value: str
    expected_value: str
    message: str
    suggestion: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert violation to dictionary format."""
        return {
            "rule_id": self.rule_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "net_name": self.net_name,
            "item_type": self.item_type,
            "layer": self.layer,
            "pos_x_mm": round(self.pos_x_mm, 3),
            "pos_y_mm": round(self.pos_y_mm, 3),
            "actual_value": str(self.actual_value),
            "expected_value": str(self.expected_value),
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class AuditSummary:
    """Aggregated statistics for an audit run."""
    total_violations: int = 0
    errors_count: int = 0
    warnings_count: int = 0
    info_count: int = 0
    categories_breakdown: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_violations": self.total_violations,
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count,
            "info_count": self.info_count,
            "categories_breakdown": self.categories_breakdown,
        }


@dataclass
class AuditReport:
    """Complete audit report containing metadata, metrics, and violation list."""
    title: str
    board_name: str
    timestamp: str
    config_used: Dict[str, Any]
    summary: AuditSummary
    violations: List[Violation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "board_name": self.board_name,
            "timestamp": self.timestamp,
            "config_used": self.config_used,
            "summary": self.summary.to_dict(),
            "violations": [v.to_dict() for v in self.violations],
        }


class PcbAuditorEngine:
    """
    Main evaluation engine for checking PCB power/signal tracks, mechanical
    grounding, silkscreen readability, and pad clearances.
    """

    def __init__(self, config: Optional[AuditRuleConfig] = None) -> None:
        self.config: AuditRuleConfig = config or AuditRuleConfig()
        self.violations: List[Violation] = []

    def audit_board(self, board: Any) -> AuditReport:
        """
        Execute all active design rule checks on the provided KiCad board object.

        Args:
            board: A pcbnew.BOARD instance or compatible mock object.

        Returns:
            An AuditReport containing all detected violations and summary stats.
        """
        self.violations.clear()

        # Extract board title / filename
        board_name = "Untitled_PCB"
        try:
            if hasattr(board, "GetFileName") and board.GetFileName():
                board_name = str(board.GetFileName())
            elif hasattr(board, "name") and board.name:
                board_name = str(board.name)
        except Exception:
            pass

        # 1. Audit Tracks (Power trace width, signal width, stubs)
        self._audit_tracks(board)

        # 2. Audit Mechanical Holes and Vias
        if self.config.check_ungrounded_mounting_holes or self.config.check_floating_vias:
            self._audit_mechanical_and_vias(board)

        # 3. Audit Silkscreen Readability
        if self.config.check_silkscreen_readability:
            self._audit_silkscreen_readability(board)

        # 4. Audit Silkscreen Overlap on Exposed Solder Pads
        if self.config.check_silkscreen_pad_overlap:
            self._audit_silkscreen_pad_overlap(board)

        # Compute summary
        summary = self._compute_summary()

        report = AuditReport(
            title="KiCad 9 Automated Power & Signal Net Rule Audit",
            board_name=board_name,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            config_used=self.config.to_dict(),
            summary=summary,
            violations=list(self.violations),
        )
        return report

    # -------------------------------------------------------------------------
    # Rule Evaluators
    # -------------------------------------------------------------------------

    def _audit_tracks(self, board: Any) -> None:
        """Check trace widths against thresholds and detect dangling track stubs."""
        tracks = []
        try:
            if hasattr(board, "GetTracks"):
                tracks = list(board.GetTracks())
            elif hasattr(board, "tracks"):
                tracks = list(board.tracks)
        except Exception:
            return

        # Spatial map for dangling track detection: (round_x, round_y) -> list of tracks
        endpoint_map: Dict[Tuple[int, int], List[Any]] = {}
        # Pad positions to check if endpoints connect to components
        pad_positions: Set[Tuple[int, int]] = set()

        if self.config.check_dangling_tracks:
            pad_positions = self._collect_pad_positions(board)

        for track in tracks:
            # Check if this item is a trace segment (ignore vias for trace width check)
            is_via = False
            try:
                if hasattr(track, "GetClass"):
                    is_via = track.GetClass() in ("PCB_VIA", "VIA")
                elif hasattr(track, "is_via"):
                    is_via = bool(track.is_via)
            except Exception:
                pass

            # Vias are audited separately in _audit_mechanical_and_vias
            if is_via:
                continue

            net_name = self._get_item_netname(track)
            width_iu = getattr(track, "GetWidth", lambda: 0)()
            width_mm = to_mm(width_iu)

            # Extract coordinates
            start_x, start_y = 0.0, 0.0
            end_x, end_y = 0.0, 0.0
            mid_x, mid_y = 0.0, 0.0
            layer_name = self._get_item_layer_name(track)

            if hasattr(track, "GetStart") and hasattr(track, "GetEnd"):
                st = track.GetStart()
                en = track.GetEnd()
                start_x, start_y = to_mm(st.x), to_mm(st.y)
                end_x, end_y = to_mm(en.x), to_mm(en.y)
                mid_x = (start_x + end_x) / 2.0
                mid_y = (start_y + end_y) / 2.0
            elif hasattr(track, "GetPosition"):
                pos = track.GetPosition()
                mid_x, mid_y = to_mm(pos.x), to_mm(pos.y)

            # Check Power Trace Width
            if self.config.is_power_or_ground_net(net_name):
                recommended_width = self.config.min_power_trace_width_mm
                if width_mm < recommended_width:
                    # Critical if trace width is less than 60% of requirement
                    severity = (
                        Severity.ERROR
                        if width_mm < (recommended_width * 0.6)
                        else Severity.WARNING
                    )
                    self.violations.append(
                        Violation(
                            rule_id="PWR001",
                            category=RuleCategory.POWER_TRACE_WIDTH,
                            severity=severity,
                            net_name=net_name,
                            item_type="PCB_TRACK",
                            layer=layer_name,
                            pos_x_mm=mid_x,
                            pos_y_mm=mid_y,
                            actual_value=f"{width_mm:.3f} mm",
                            expected_value=f">= {recommended_width:.3f} mm",
                            message=(
                                f"Power rail '{net_name}' trace width ({width_mm:.3f} mm) is below "
                                f"minimum requirement ({recommended_width:.3f} mm)."
                            ),
                            suggestion=(
                                f"Increase trace width to at least {recommended_width:.3f} mm to carry "
                                f"rated current without excessive I2R heating (IPC-2221)."
                            ),
                        )
                    )
            elif net_name:  # Standard signal track
                if width_mm < self.config.min_signal_trace_width_mm:
                    self.violations.append(
                        Violation(
                            rule_id="SIG001",
                            category=RuleCategory.SIGNAL_TRACE_WIDTH,
                            severity=Severity.WARNING,
                            net_name=net_name,
                            item_type="PCB_TRACK",
                            layer=layer_name,
                            pos_x_mm=mid_x,
                            pos_y_mm=mid_y,
                            actual_value=f"{width_mm:.3f} mm",
                            expected_value=f">= {self.config.min_signal_trace_width_mm:.3f} mm",
                            message=(
                                f"Signal net '{net_name}' trace width ({width_mm:.3f} mm) is below "
                                f"threshold ({self.config.min_signal_trace_width_mm:.3f} mm)."
                            ),
                            suggestion="Increase trace width or update manufacturing clearance rules.",
                        )
                    )

            # Collect endpoints for dangling track check
            if self.config.check_dangling_tracks:
                if hasattr(track, "GetStart") and hasattr(track, "GetEnd"):
                    st = track.GetStart()
                    en = track.GetEnd()
                    pt1 = (int(round(st.x / 1000.0)), int(round(st.y / 1000.0)))
                    pt2 = (int(round(en.x / 1000.0)), int(round(en.y / 1000.0)))
                    endpoint_map.setdefault(pt1, []).append(track)
                    endpoint_map.setdefault(pt2, []).append(track)

        # Evaluate dangling stubs
        if self.config.check_dangling_tracks:
            self._evaluate_dangling_tracks(endpoint_map, pad_positions)

    def _collect_pad_positions(self, board: Any) -> Set[Tuple[int, int]]:
        """Collect spatial coordinates of all pads across all footprints."""
        pad_coords: Set[Tuple[int, int]] = set()
        footprints = []
        try:
            if hasattr(board, "GetFootprints"):
                footprints = list(board.GetFootprints())
            elif hasattr(board, "footprints"):
                footprints = list(board.footprints)
        except Exception:
            return pad_coords

        for fp in footprints:
            pads = []
            try:
                if hasattr(fp, "Pads"):
                    pads = list(fp.Pads())
                elif hasattr(fp, "pads"):
                    pads = list(fp.pads)
            except Exception:
                continue

            for pad in pads:
                pos = pad.GetPosition() if hasattr(pad, "GetPosition") else getattr(pad, "position", None)
                if pos:
                    # Key normalized to 1 um grid to absorb micro-floating-point deviations
                    key = (int(round(pos.x / 1000.0)), int(round(pos.y / 1000.0)))
                    pad_coords.add(key)
        return pad_coords

    def _evaluate_dangling_tracks(
        self,
        endpoint_map: Dict[Tuple[int, int], List[Any]],
        pad_positions: Set[Tuple[int, int]],
    ) -> None:
        """Find tracks with an unconnected end that does not terminate at a pad or junction."""
        reported_tracks = set()

        for pt, connected_tracks in endpoint_map.items():
            # If an endpoint only connects to a single track and no component pad exists at that point
            if len(connected_tracks) == 1 and pt not in pad_positions:
                trk = connected_tracks[0]
                trk_id = id(trk)
                if trk_id in reported_tracks:
                    continue

                net_name = self._get_item_netname(trk)
                # Ignore dummy/unconnected net 0
                if not net_name:
                    continue

                length_mm = 0.0
                if hasattr(trk, "GetLength"):
                    length_mm = to_mm(trk.GetLength())
                elif hasattr(trk, "GetStart") and hasattr(trk, "GetEnd"):
                    st = trk.GetStart()
                    en = trk.GetEnd()
                    dx = to_mm(st.x - en.x)
                    dy = to_mm(st.y - en.y)
                    length_mm = math.hypot(dx, dy)

                if length_mm >= self.config.dangling_track_length_threshold_mm:
                    reported_tracks.add(trk_id)
                    pos_x = pt[0] / 1000.0  # convert from 1um key to mm
                    pos_y = pt[1] / 1000.0
                    self.violations.append(
                        Violation(
                            rule_id="TRK001",
                            category=RuleCategory.DANGLING_TRACK,
                            severity=Severity.WARNING,
                            net_name=net_name,
                            item_type="PCB_TRACK",
                            layer=self._get_item_layer_name(trk),
                            pos_x_mm=pos_x,
                            pos_y_mm=pos_y,
                            actual_value=f"Open endpoint (stub length ~ {length_mm:.2f} mm)",
                            expected_value="Connected to pad, via, or junction",
                            message=f"Dangling track stub detected on net '{net_name}'.",
                            suggestion="Remove or re-route the floating stub to avoid antenna emissions and EMI reflections.",
                        )
                    )

    def _audit_mechanical_and_vias(self, board: Any) -> None:
        """Audit mounting holes for ground connection and check for floating vias."""
        # 1. Footprint Mounting Holes
        footprints = []
        try:
            if hasattr(board, "GetFootprints"):
                footprints = list(board.GetFootprints())
            elif hasattr(board, "footprints"):
                footprints = list(board.footprints)
        except Exception:
            footprints = []

        for fp in footprints:
            ref = fp.GetReference() if hasattr(fp, "GetReference") else getattr(fp, "reference", "")
            fp_id = ""
            if hasattr(fp, "GetFPIDAsString"):
                fp_id = fp.GetFPIDAsString()
            elif hasattr(fp, "fpid"):
                fp_id = str(fp.fpid)

            if self.config.is_mounting_hole(ref, fp_id):
                pos = fp.GetPosition() if hasattr(fp, "GetPosition") else getattr(fp, "position", None)
                pos_x = to_mm(pos.x) if pos else 0.0
                pos_y = to_mm(pos.y) if pos else 0.0

                pads = []
                try:
                    if hasattr(fp, "Pads"):
                        pads = list(fp.Pads())
                    elif hasattr(fp, "pads"):
                        pads = list(fp.pads)
                except Exception:
                    pads = []

                if not pads:
                    # Unplated / non-copper mounting hole
                    self.violations.append(
                        Violation(
                            rule_id="MCH002",
                            category=RuleCategory.UNGROUNDED_MECHANICAL,
                            severity=Severity.INFO,
                            net_name="UNCONNECTED",
                            item_type="FOOTPRINT",
                            layer="Edge.Cuts",
                            pos_x_mm=pos_x,
                            pos_y_mm=pos_y,
                            actual_value="No plated pad",
                            expected_value="Chassis / Earth Ground (Optional)",
                            message=f"Mounting hole '{ref}' is non-plated / mechanical only.",
                            suggestion="If ESD or EMI chassis grounding is needed, replace with a plated mounting hole tied to GND/CHASSIS.",
                        )
                    )
                else:
                    # Check each pad's net
                    is_grounded = False
                    connected_net = ""
                    for pad in pads:
                        pad_net = self._get_item_netname(pad)
                        if pad_net:
                            connected_net = pad_net
                            if self.config.is_ground_net(pad_net):
                                is_grounded = True
                                break

                    if not is_grounded:
                        self.violations.append(
                            Violation(
                                rule_id="MCH001",
                                category=RuleCategory.UNGROUNDED_MECHANICAL,
                                severity=Severity.WARNING,
                                net_name=connected_net or "UNCONNECTED",
                                item_type="FOOTPRINT",
                                layer="F.Cu / B.Cu",
                                pos_x_mm=pos_x,
                                pos_y_mm=pos_y,
                                actual_value=f"Net: '{connected_net or 'None'}'",
                                expected_value="GND / CHASSIS / EARTH",
                                message=f"Plated mounting hole '{ref}' is not tied to a ground net.",
                                suggestion="Tie plated mounting hole to system ground or chassis to improve return path and ESD dissipation.",
                            )
                        )

        # 2. Vias
        if self.config.check_floating_vias:
            tracks = []
            try:
                if hasattr(board, "GetTracks"):
                    tracks = list(board.GetTracks())
                elif hasattr(board, "tracks"):
                    tracks = list(board.tracks)
            except Exception:
                pass

            for item in tracks:
                is_via = False
                try:
                    if hasattr(item, "GetClass"):
                        is_via = item.GetClass() in ("PCB_VIA", "VIA")
                    elif hasattr(item, "is_via"):
                        is_via = bool(item.is_via)
                except Exception:
                    pass

                if is_via:
                    net_name = self._get_item_netname(item)
                    if not net_name or net_name == "0" or net_name.upper() == "UNCONNECTED":
                        pos = item.GetPosition() if hasattr(item, "GetPosition") else getattr(item, "position", None)
                        pos_x = to_mm(pos.x) if pos else 0.0
                        pos_y = to_mm(pos.y) if pos else 0.0
                        self.violations.append(
                            Violation(
                                rule_id="VIA001",
                                category=RuleCategory.FLOATING_VIA,
                                severity=Severity.WARNING,
                                net_name="UNCONNECTED",
                                item_type="PCB_VIA",
                                layer="Multi-layer",
                                pos_x_mm=pos_x,
                                pos_y_mm=pos_y,
                                actual_value="Net code 0 / Unassigned",
                                expected_value="Valid routed net",
                                message="Floating / unassigned via detected.",
                                suggestion="Assign via to a valid signal or power net, or remove orphan via.",
                            )
                        )

    def _audit_silkscreen_readability(self, board: Any) -> None:
        """Validate silkscreen text heights and stroke thicknesses for fabrication readability."""
        min_height = self.config.min_silkscreen_text_height_mm
        min_thickness = self.config.min_silkscreen_text_thickness_mm

        # Check Footprint Reference and Value texts
        footprints = []
        try:
            if hasattr(board, "GetFootprints"):
                footprints = list(board.GetFootprints())
            elif hasattr(board, "footprints"):
                footprints = list(board.footprints)
        except Exception:
            footprints = []

        for fp in footprints:
            text_items = []
            if hasattr(fp, "Reference"):
                text_items.append(fp.Reference())
            if hasattr(fp, "Value"):
                text_items.append(fp.Value())

            # Footprint graphical items (user silkscreen markings)
            if hasattr(fp, "GraphicalItems"):
                try:
                    for gi in fp.GraphicalItems():
                        if hasattr(gi, "GetText"):
                            text_items.append(gi)
                except Exception:
                    pass

            for item in text_items:
                if not item or not hasattr(item, "IsVisible") or not item.IsVisible():
                    continue

                layer_name = self._get_item_layer_name(item)
                if "Silk" not in layer_name:
                    continue

                text_str = item.GetText() if hasattr(item, "GetText") else getattr(item, "text", "")
                if not text_str.strip():
                    continue

                height_mm, thickness_mm = self._get_text_metrics(item)
                pos = item.GetPosition() if hasattr(item, "GetPosition") else getattr(item, "position", None)
                pos_x = to_mm(pos.x) if pos else 0.0
                pos_y = to_mm(pos.y) if pos else 0.0

                if height_mm < min_height or thickness_mm < min_thickness:
                    self.violations.append(
                        Violation(
                            rule_id="SLK001",
                            category=RuleCategory.SILKSCREEN_READABILITY,
                            severity=Severity.WARNING,
                            net_name="N/A",
                            item_type="FP_TEXT",
                            layer=layer_name,
                            pos_x_mm=pos_x,
                            pos_y_mm=pos_y,
                            actual_value=f"Height: {height_mm:.2f}mm, Width/Thick: {thickness_mm:.2f}mm",
                            expected_value=f"Min Height: {min_height:.2f}mm, Min Thick: {min_thickness:.2f}mm",
                            message=f"Silkscreen text '{text_str}' may be unreadable after PCB fabrication.",
                            suggestion=f"Increase font height to >= {min_height:.2f} mm and stroke width to >= {min_thickness:.2f} mm.",
                        )
                    )

        # Check Standalone Board Drawings (Board-level silkscreen text)
        drawings = []
        try:
            if hasattr(board, "GetDrawings"):
                drawings = list(board.GetDrawings())
            elif hasattr(board, "drawings"):
                drawings = list(board.drawings)
        except Exception:
            pass

        for dwg in drawings:
            if hasattr(dwg, "GetText"):
                layer_name = self._get_item_layer_name(dwg)
                if "Silk" not in layer_name:
                    continue

                text_str = dwg.GetText()
                if not text_str.strip():
                    continue

                height_mm, thickness_mm = self._get_text_metrics(dwg)
                pos = dwg.GetPosition() if hasattr(dwg, "GetPosition") else getattr(dwg, "position", None)
                pos_x = to_mm(pos.x) if pos else 0.0
                pos_y = to_mm(pos.y) if pos else 0.0

                if height_mm < min_height or thickness_mm < min_thickness:
                    self.violations.append(
                        Violation(
                            rule_id="SLK001",
                            category=RuleCategory.SILKSCREEN_READABILITY,
                            severity=Severity.WARNING,
                            net_name="N/A",
                            item_type="PCB_TEXT",
                            layer=layer_name,
                            pos_x_mm=pos_x,
                            pos_y_mm=pos_y,
                            actual_value=f"Height: {height_mm:.2f}mm, Width/Thick: {thickness_mm:.2f}mm",
                            expected_value=f"Min Height: {min_height:.2f}mm, Min Thick: {min_thickness:.2f}mm",
                            message=f"Board silkscreen text '{text_str}' is below readability thresholds.",
                            suggestion=f"Resize text to >= {min_height:.2f} mm height.",
                        )
                    )

    def _audit_silkscreen_pad_overlap(self, board: Any) -> None:
        """
        Detect silkscreen text crossing over exposed SMD or THT copper pads.
        Silkscreen ink on solder pads causes poor solder wetting and tombstoning.
        """
        footprints = []
        try:
            if hasattr(board, "GetFootprints"):
                footprints = list(board.GetFootprints())
            elif hasattr(board, "footprints"):
                footprints = list(board.footprints)
        except Exception:
            return

        # Build list of pads with their bounding circles/boxes in mm
        pads_summary: List[Tuple[float, float, float, str, str]] = []  # (x, y, radius, layer_side, ref)

        for fp in footprints:
            ref = fp.GetReference() if hasattr(fp, "GetReference") else getattr(fp, "reference", "")
            pads = []
            try:
                if hasattr(fp, "Pads"):
                    pads = list(fp.Pads())
                elif hasattr(fp, "pads"):
                    pads = list(fp.pads)
            except Exception:
                continue

            for pad in pads:
                pos = pad.GetPosition() if hasattr(pad, "GetPosition") else getattr(pad, "position", None)
                if not pos:
                    continue

                px, py = to_mm(pos.x), to_mm(pos.y)
                layer_name = self._get_item_layer_name(pad)
                side = "F" if "F." in layer_name or "Top" in layer_name else "B"

                # Pad size approximation
                size_x, size_y = 1.0, 1.0
                if hasattr(pad, "GetSize"):
                    sz = pad.GetSize()
                    size_x, size_y = to_mm(sz.x), to_mm(sz.y)
                radius = max(size_x, size_y) / 2.0

                pads_summary.append((px, py, radius, side, ref))

        # Check silkscreen text bounding boxes against pads
        for fp in footprints:
            text_items = []
            if hasattr(fp, "Reference"):
                text_items.append(fp.Reference())
            if hasattr(fp, "Value"):
                text_items.append(fp.Value())

            for item in text_items:
                if not item or not hasattr(item, "IsVisible") or not item.IsVisible():
                    continue

                layer_name = self._get_item_layer_name(item)
                if "Silk" not in layer_name:
                    continue

                text_str = item.GetText() if hasattr(item, "GetText") else getattr(item, "text", "")
                if not text_str.strip():
                    continue

                side = "F" if "F." in layer_name else "B"
                pos = item.GetPosition() if hasattr(item, "GetPosition") else getattr(item, "position", None)
                if not pos:
                    continue
                tx, ty = to_mm(pos.x), to_mm(pos.y)
                text_height, _ = self._get_text_metrics(item)
                text_reach = max(text_height, 0.6)

                # Check proximity to pads on same side
                for px, py, pad_rad, pad_side, pad_ref in pads_summary:
                    if side != pad_side:
                        continue
                    dist = math.hypot(tx - px, ty - py)
                    clearance_needed = pad_rad + text_reach * 0.4 + self.config.min_silkscreen_pad_clearance_mm
                    if dist < clearance_needed:
                        self.violations.append(
                            Violation(
                                rule_id="SLK002",
                                category=RuleCategory.SILKSCREEN_PAD_OVERLAP,
                                severity=Severity.ERROR,
                                net_name="N/A",
                                item_type="FP_TEXT",
                                layer=layer_name,
                                pos_x_mm=tx,
                                pos_y_mm=ty,
                                actual_value=f"Distance to pad {dist:.2f}mm",
                                expected_value=f"Clearance >= {self.config.min_silkscreen_pad_clearance_mm:.2f}mm",
                                message=f"Silkscreen '{text_str}' encroaches upon pad of footprint '{pad_ref}'.",
                                suggestion="Relocate silkscreen reference or text away from exposed solder pads to prevent soldering defects.",
                            )
                        )
                        break  # Report once per overlapping text item

    # -------------------------------------------------------------------------
    # Helper Utilities
    # -------------------------------------------------------------------------

    def _get_item_netname(self, item: Any) -> str:
        """Safely extract net name string from any KiCad item."""
        try:
            if hasattr(item, "GetNetname"):
                return str(item.GetNetname())
            if hasattr(item, "GetNet"):
                net = item.GetNet()
                if net and hasattr(net, "GetNetname"):
                    return str(net.GetNetname())
            if hasattr(item, "net_name"):
                return str(item.net_name)
        except Exception:
            pass
        return ""

    def _get_item_layer_name(self, item: Any) -> str:
        """Extract canonical layer name string."""
        try:
            if hasattr(item, "GetLayerName"):
                return str(item.GetLayerName())
            if hasattr(item, "layer"):
                return str(item.layer)
        except Exception:
            pass
        return "Unknown"

    def _get_text_metrics(self, text_item: Any) -> Tuple[float, float]:
        """Extract text height (mm) and stroke thickness (mm)."""
        height_mm = 1.0
        thickness_mm = 0.15

        try:
            if hasattr(text_item, "GetTextHeight"):
                height_mm = to_mm(text_item.GetTextHeight())
            elif hasattr(text_item, "GetTextSize"):
                sz = text_item.GetTextSize()
                height_mm = to_mm(sz.y if hasattr(sz, "y") else sz[1])
            elif hasattr(text_item, "height"):
                height_mm = float(text_item.height)

            if hasattr(text_item, "GetTextThickness"):
                thickness_mm = to_mm(text_item.GetTextThickness())
            elif hasattr(text_item, "thickness"):
                thickness_mm = float(text_item.thickness)
        except Exception:
            pass

        return height_mm, thickness_mm

    def _compute_summary(self) -> AuditSummary:
        """Calculate counts by severity and category."""
        summary = AuditSummary(total_violations=len(self.violations))
        for v in self.violations:
            if v.severity == Severity.ERROR:
                summary.errors_count += 1
            elif v.severity == Severity.WARNING:
                summary.warnings_count += 1
            elif v.severity == Severity.INFO:
                summary.info_count += 1

            cat_key = v.category.value
            summary.categories_breakdown[cat_key] = (
                summary.categories_breakdown.get(cat_key, 0) + 1
            )
        return summary
