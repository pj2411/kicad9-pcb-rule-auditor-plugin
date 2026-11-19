"""
Configuration module for KiCad 9 Automated PCB Net & Silkscreen Design Rule Auditor.

Defines rule thresholds, default power net naming patterns, IPC-2221 trace
width estimation formulas, and configuration profile serialization (JSON).
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Pattern


# Default regex patterns used to classify power and ground nets
DEFAULT_POWER_NET_PATTERNS: List[str] = [
    r"^(\+)?([0-9]+[vV][0-9]*|[0-9]+(\.[0-9]+)?[vV]).*",
    r"^V(CC|DD|IN|BAT|BUS|REF|A|D|CORE|IO|AUX).*",
    r"^PWR_.*",
    r"^\+?[0-9]+V.*",
]

DEFAULT_GROUND_NET_PATTERNS: List[str] = [
    r"^(GND|AGND|DGND|PGND|EGND|VSS|0V|EARTH|CHASSIS|SHIELD).*",
]

# Footprint reference/name patterns for mechanical mounting holes
DEFAULT_MOUNTING_HOLE_PATTERNS: List[str] = [
    r"^H[0-9]+.*",
    r"^MH[0-9]+.*",
    r".*Mounting[-_]?Hole.*",
    r".*Mounting[-_]?Pad.*",
]


def calculate_ipc2221_trace_width(
    current_amps: float,
    temp_rise_c: float = 10.0,
    copper_thickness_oz: float = 1.0,
    is_external: bool = True,
) -> float:
    """
    Calculate minimum PCB trace width in millimeters using IPC-2221 standards.

    Formula:
        I = k * (delta_T ^ b) * (A ^ c)
        where:
            I       = Current in Amperes
            delta_T = Permissible temperature rise in degrees Celsius
            A       = Cross-sectional area in square mils
            k, b, c = Empirical constants
                      External layers: k = 0.048, b = 0.44, c = 0.725
                      Internal layers: k = 0.024, b = 0.44, c = 0.725

    Args:
        current_amps: Maximum anticipated continuous current (A).
        temp_rise_c: Maximum acceptable temperature rise (°C). Defaults to 10.0°C.
        copper_thickness_oz: Copper weight in ounces (1 oz = ~1.37 mils = 0.035 mm).
        is_external: True if outer microstrip layer (F.Cu/B.Cu), False if inner stripline.

    Returns:
        Minimum trace width in millimeters (mm).
    """
    if current_amps <= 0.0:
        return 0.0

    temp_rise = max(temp_rise_c, 1.0)
    copper_oz = max(copper_thickness_oz, 0.25)

    # IPC-2221 empirical coefficients
    if is_external:
        k = 0.048
    else:
        k = 0.024
    b = 0.44
    c = 0.725

    # Area in sq mils: A = [ I / (k * delta_T^b) ]^(1/c)
    area_sq_mils = math.pow(current_amps / (k * math.pow(temp_rise, b)), 1.0 / c)

    # 1 oz/sq ft copper thickness is ~ 1.378 mils (~ 0.035 mm)
    thickness_mils = copper_oz * 1.378

    # Width in mils = Area / Thickness
    width_mils = area_sq_mils / thickness_mils

    # Convert mils to millimeters: 1 mil = 0.0254 mm
    width_mm = width_mils * 0.0254

    return round(width_mm, 4)


@dataclass
class AuditRuleConfig:
    """
    User-configurable rules, thresholds, and regex patterns for PCB auditing.
    """

    # --- Power & Signal Trace Width Rules ---
    min_power_trace_width_mm: float = 0.50
    min_signal_trace_width_mm: float = 0.20
    target_current_amps: float = 1.0
    allowed_temp_rise_c: float = 10.0
    copper_weight_oz: float = 1.0

    # Patterns to detect power and ground nets
    power_net_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_POWER_NET_PATTERNS))
    ground_net_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_GROUND_NET_PATTERNS))

    # --- Mechanical & Via Grounding Rules ---
    check_ungrounded_mounting_holes: bool = True
    mounting_hole_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_MOUNTING_HOLE_PATTERNS))
    require_plated_mounting_ground: bool = True
    check_floating_vias: bool = True

    # --- Silkscreen Rules ---
    check_silkscreen_readability: bool = True
    min_silkscreen_text_height_mm: float = 0.80
    min_silkscreen_text_thickness_mm: float = 0.15
    check_silkscreen_pad_overlap: bool = True
    min_silkscreen_pad_clearance_mm: float = 0.15

    # --- Track Integrity Rules ---
    check_dangling_tracks: bool = True
    dangling_track_length_threshold_mm: float = 0.10

    # Internal compiled regex cache (ignored in serialization)
    _compiled_power_regex: List[Pattern[str]] = field(init=False, repr=False, default_factory=list)
    _compiled_ground_regex: List[Pattern[str]] = field(init=False, repr=False, default_factory=list)
    _compiled_hole_regex: List[Pattern[str]] = field(init=False, repr=False, default_factory=list)

    def __post_init__(self) -> None:
        self.compile_regexes()

    def compile_regexes(self) -> None:
        """Compile string regex patterns into cached Pattern objects."""
        self._compiled_power_regex = [
            re.compile(p, re.IGNORECASE) for p in self.power_net_patterns
        ]
        self._compiled_ground_regex = [
            re.compile(p, re.IGNORECASE) for p in self.ground_net_patterns
        ]
        self._compiled_hole_regex = [
            re.compile(p, re.IGNORECASE) for p in self.mounting_hole_patterns
        ]

    def is_power_net(self, net_name: str) -> bool:
        """Return True if the net name matches power rail patterns."""
        if not net_name:
            return False
        clean_name = net_name.strip()
        return any(rx.search(clean_name) for rx in self._compiled_power_regex)

    def is_ground_net(self, net_name: str) -> bool:
        """Return True if the net name matches ground rail patterns."""
        if not net_name:
            return False
        clean_name = net_name.strip()
        return any(rx.search(clean_name) for rx in self._compiled_ground_regex)

    def is_power_or_ground_net(self, net_name: str) -> bool:
        """Return True if net name is either power or ground."""
        return self.is_power_net(net_name) or self.is_ground_net(net_name)

    def is_mounting_hole(self, reference: str, footprint_name: str = "") -> bool:
        """Return True if reference or footprint name matches mounting hole patterns."""
        ref = reference.strip() if reference else ""
        fp = footprint_name.strip() if footprint_name else ""
        return any(rx.search(ref) or rx.search(fp) for rx in self._compiled_hole_regex)

    def get_ipc2221_recommended_power_width_mm(self) -> float:
        """Calculate recommended power trace width based on current config."""
        return calculate_ipc2221_trace_width(
            current_amps=self.target_current_amps,
            temp_rise_c=self.allowed_temp_rise_c,
            copper_thickness_oz=self.copper_weight_oz,
            is_external=True,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to a pure dictionary."""
        data = asdict(self)
        # Drop private internal fields
        for key in list(data.keys()):
            if key.startswith("_"):
                del data[key]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuditRuleConfig:
        """Instantiate AuditRuleConfig from a dictionary, safely ignoring unknown keys."""
        valid_keys = {
            "min_power_trace_width_mm",
            "min_signal_trace_width_mm",
            "target_current_amps",
            "allowed_temp_rise_c",
            "copper_weight_oz",
            "power_net_patterns",
            "ground_net_patterns",
            "check_ungrounded_mounting_holes",
            "mounting_hole_patterns",
            "require_plated_mounting_ground",
            "check_floating_vias",
            "check_silkscreen_readability",
            "min_silkscreen_text_height_mm",
            "min_silkscreen_text_thickness_mm",
            "check_silkscreen_pad_overlap",
            "min_silkscreen_pad_clearance_mm",
            "check_dangling_tracks",
            "dangling_track_length_threshold_mm",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


def load_config_from_file(file_path: str) -> AuditRuleConfig:
    """
    Load rule configuration from a JSON file. Returns default config if file is missing.
    """
    if not os.path.isfile(file_path):
        return AuditRuleConfig()

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AuditRuleConfig.from_dict(data)
    except Exception as exc:
        print(f"[KiCad Auditor] Warning: Failed to load config from {file_path}: {exc}. Using defaults.")
        return AuditRuleConfig()


def save_config_to_file(config: AuditRuleConfig, file_path: str) -> None:
    """
    Save configuration profile to a JSON file with pretty formatting.
    """
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=4)
