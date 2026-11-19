"""
Report Exporter module for KiCad 9 Automated PCB Net & Silkscreen Design Rule Auditor.

Generates structured audit reports in JSON, CSV, and Markdown formats.
Can write directly to disk or return formatted strings for UI presentation.
"""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Optional

from .auditor_engine import AuditReport, Severity


def generate_json_str(report: AuditReport, indent: int = 2) -> str:
    """Return JSON string representation of the audit report."""
    return json.dumps(report.to_dict(), indent=indent)


def export_to_json(report: AuditReport, file_path: str) -> None:
    """Write audit report to disk as a JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(generate_json_str(report))


def generate_csv_str(report: AuditReport) -> str:
    """Return CSV formatted string of all violations."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # CSV Header
    writer.writerow([
        "Rule ID",
        "Category",
        "Severity",
        "Net Name",
        "Item Type",
        "Layer",
        "Pos X (mm)",
        "Pos Y (mm)",
        "Actual Value",
        "Expected Value",
        "Message",
        "Remediation Suggestion",
    ])

    for v in report.violations:
        writer.writerow([
            v.rule_id,
            v.category.value,
            v.severity.value,
            v.net_name,
            v.item_type,
            v.layer,
            f"{v.pos_x_mm:.3f}",
            f"{v.pos_y_mm:.3f}",
            v.actual_value,
            v.expected_value,
            v.message,
            v.suggestion,
        ])

    return output.getvalue()


def export_to_csv(report: AuditReport, file_path: str) -> None:
    """Write audit report to disk as a CSV file."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(generate_csv_str(report))


def generate_markdown_str(report: AuditReport) -> str:
    """Return publication-grade Markdown formatted audit report."""
    lines = []
    lines.append(f"# {report.title}")
    lines.append("")
    lines.append(f"**Target Board:** `{report.board_name}`  ")
    lines.append(f"**Audit Timestamp:** `{report.timestamp}`  ")
    lines.append(f"**Status:** {'❌ FAIL (Errors Detected)' if report.summary.errors_count > 0 else ('⚠️ WARNING (Action Recommended)' if report.summary.warnings_count > 0 else '✅ PASS (Design Clean)')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. Executive Summary Table
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append("| Metric | Count | Status Badge |")
    lines.append("| :--- | :---: | :--- |")
    lines.append(f"| **Total Violations** | **{report.summary.total_violations}** | {'🚨 Critical' if report.summary.errors_count > 0 else 'ℹ️ Monitored'} |")
    lines.append(f"| Errors (Must Fix) | {report.summary.errors_count} | {'🔴 FAIL' if report.summary.errors_count > 0 else '🟢 CLEAN'} |")
    lines.append(f"| Warnings (Recommended) | {report.summary.warnings_count} | {'🟡 ATTENTION' if report.summary.warnings_count > 0 else '🟢 CLEAN'} |")
    lines.append(f"| Information / Notices | {report.summary.info_count} | 🔵 INFO |")
    lines.append("")

    # 2. Rule Category Breakdown
    lines.append("## 2. Category Breakdown")
    lines.append("")
    if report.summary.categories_breakdown:
        lines.append("| Rule Category | Count | Primary Impact |")
        lines.append("| :--- | :---: | :--- |")
        category_impacts = {
            "Power Trace Width": "I2R resistive drop & PCB thermal overheating",
            "Signal Trace Width": "Manufacturing etch capability & current limits",
            "Ungrounded Mechanical / Hole": "ESD discharge path & chassis EMI shielding",
            "Floating / Unconnected Via": "Orphan copper / unrouted stub antenna",
            "Silkscreen Readability": "Fab legibility & optical inspection readability",
            "Silkscreen Pad Overlap": "Solder dewetting, bridge defects & tombstoning",
            "Dangling Track / Stub": "High-frequency reflection & RF radiated emissions",
        }
        for cat, cnt in sorted(report.summary.categories_breakdown.items(), key=lambda x: -x[1]):
            impact = category_impacts.get(cat, "Design rule compliance")
            lines.append(f"| {cat} | {cnt} | {impact} |")
        lines.append("")
    else:
        lines.append("No rule violations found across all inspected categories.\n")

    # 3. Applied Thresholds
    lines.append("## 3. Active Rule Thresholds")
    lines.append("")
    lines.append("| Parameter | Configured Value | Unit | Description |")
    lines.append("| :--- | :---: | :---: | :--- |")
    cfg = report.config_used
    lines.append(f"| `min_power_trace_width_mm` | {cfg.get('min_power_trace_width_mm', 0.50):.2f} | mm | Min width for high-current power rails |")
    lines.append(f"| `min_signal_trace_width_mm` | {cfg.get('min_signal_trace_width_mm', 0.20):.2f} | mm | Min width for standard logic/signal traces |")
    lines.append(f"| `min_silkscreen_text_height_mm` | {cfg.get('min_silkscreen_text_height_mm', 0.80):.2f} | mm | Min legible silkscreen text height |")
    lines.append(f"| `min_silkscreen_text_thickness_mm` | {cfg.get('min_silkscreen_text_thickness_mm', 0.15):.2f} | mm | Min silkscreen line stroke thickness |")
    lines.append(f"| `min_silkscreen_pad_clearance_mm` | {cfg.get('min_silkscreen_pad_clearance_mm', 0.15):.2f} | mm | Clearance between silkscreen ink and pads |")
    lines.append(f"| `target_current_amps` | {cfg.get('target_current_amps', 1.0):.1f} | A | IPC-2221 reference calculation current |")
    lines.append("")

    # 4. Detailed Violations Log
    lines.append("## 4. Detailed Violations")
    lines.append("")
    if not report.violations:
        lines.append("🎉 **No design rule violations detected. The layout conforms to all configured audit criteria.**")
    else:
        lines.append("| # | Sev | Rule | Net | Layer | Position (mm) | Actual | Expected | Message & Suggestion |")
        lines.append("| :-: | :-: | :--- | :--- | :--- | :---: | :--- | :--- | :--- |")
        for i, v in enumerate(report.violations, start=1):
            sev_badge = "🔴 ERR" if v.severity == Severity.ERROR else ("🟡 WARN" if v.severity == Severity.WARNING else "🔵 INFO")
            coord_str = f"({v.pos_x_mm:.2f}, {v.pos_y_mm:.2f})"
            desc = f"**{v.message}**<br>💡 *Remedy:* {v.suggestion}"
            lines.append(
                f"| {i} | {sev_badge} | `{v.rule_id}` | `{v.net_name}` | {v.layer} | {coord_str} | {v.actual_value} | {v.expected_value} | {desc} |"
            )

    lines.append("")
    lines.append("---")
    lines.append("*Generated by KiCad 9 Automated PCB Net & Silkscreen Design Rule Auditor (FOSSEE eSim Winter Internship)*")
    return "\n".join(lines)


def export_to_markdown(report: AuditReport, file_path: str) -> None:
    """Write audit report to disk as a Markdown file."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown_str(report))
