"""
KiCad 9 ActionPlugin entry point and wxPython interactive user interface.

Provides the GUI dialog with audit violation inspection, real-time filtering,
IPC-2221 trace width calculator, and instant export to CSV, JSON, and Markdown.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional

# Attempt to import pcbnew and wx; safely provide stubs when running outside KiCad
try:
    import pcbnew
    HAS_PCBNEW = True
except ImportError:
    pcbnew = None  # type: ignore
    HAS_PCBNEW = False

try:
    import wx
    import wx.grid
    HAS_WX = True
except ImportError:
    wx = None  # type: ignore
    HAS_WX = False

from .auditor_engine import AuditReport, PcbAuditorEngine, Severity, Violation, from_mm
from .config import AuditRuleConfig, calculate_ipc2221_trace_width, load_config_from_file, save_config_to_file
from .report_exporter import export_to_csv, export_to_json, export_to_markdown


# Base class for ActionPlugin (uses pcbnew.ActionPlugin inside KiCad, object outside)
ActionPluginBase = pcbnew.ActionPlugin if HAS_PCBNEW else object


class AuditorMainDialog(wx.Dialog if HAS_WX else object):  # type: ignore
    """
    Primary wxPython dialog providing the audit interface, IPC calculator,
    and rule configuration editor within KiCad 9.
    """

    def __init__(self, parent: Any, board: Any) -> None:
        if not HAS_WX:
            raise RuntimeError("wxPython is not available in the current Python environment.")

        super().__init__(
            parent,
            title="KiCad 9 PCB Net & Silkscreen Design Rule Auditor",
            size=(920, 640),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )

        self.board = board
        self.config = AuditRuleConfig()
        self.engine = PcbAuditorEngine(self.config)
        self.current_report: Optional[AuditReport] = None
        self.displayed_violations: List[Violation] = []

        self._init_ui()
        self.Centre()

        # Run initial audit automatically if a valid board is present
        if self.board is not None:
            self._on_run_audit(None)

    def _init_ui(self) -> None:
        """Construct notebook tabs and layout hierarchy."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Tab Notebook
        self.notebook = wx.Notebook(self)

        # Tab 1: Audit Findings
        tab_findings = self._create_findings_tab(self.notebook)
        self.notebook.AddPage(tab_findings, "Audit Findings")

        # Tab 2: Rule Thresholds & Configuration
        tab_config = self._create_config_tab(self.notebook)
        self.notebook.AddPage(tab_config, "Rule Settings")

        # Tab 3: IPC-2221 Trace Width Calculator
        tab_calc = self._create_calculator_tab(self.notebook)
        self.notebook.AddPage(tab_calc, "IPC-2221 Calculator")

        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)

        # Bottom Action Bar
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_run = wx.Button(self, label="▶ Run Audit")
        self.btn_run.SetFont(self.btn_run.GetFont().Bold())
        self.btn_run.Bind(wx.EVT_BUTTON, self._on_run_audit)
        bottom_sizer.Add(self.btn_run, 0, wx.RIGHT, 8)

        self.btn_export = wx.Button(self, label="📄 Export Report...")
        self.btn_export.Bind(wx.EVT_BUTTON, self._on_export_menu)
        bottom_sizer.Add(self.btn_export, 0, wx.RIGHT, 8)

        bottom_sizer.AddStretchSpacer()

        self.btn_close = wx.Button(self, wx.ID_CLOSE, label="Close")
        self.btn_close.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_OK))
        bottom_sizer.Add(self.btn_close, 0)

        main_sizer.Add(bottom_sizer, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(main_sizer)

    # -------------------------------------------------------------------------
    # TAB 1: Findings UI
    # -------------------------------------------------------------------------
    def _create_findings_tab(self, parent: Any) -> wx.Panel:
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Top summary bar
        top_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_summary = wx.StaticText(
            panel, label="Status: Ready to audit. Click 'Run Audit' to begin."
        )
        self.lbl_summary.SetFont(self.lbl_summary.GetFont().Bold())
        top_bar.Add(self.lbl_summary, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        # Severity filter combo
        top_bar.Add(wx.StaticText(panel, label="Filter:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.combo_filter = wx.Choice(
            panel, choices=["All Findings", "Errors Only (Must Fix)", "Warnings & Errors"]
        )
        self.combo_filter.SetSelection(0)
        self.combo_filter.Bind(wx.EVT_CHOICE, self._on_filter_changed)
        top_bar.Add(self.combo_filter, 0, wx.ALIGN_CENTER_VERTICAL)

        sizer.Add(top_bar, 0, wx.EXPAND | wx.ALL, 6)

        # Violations ListCtrl
        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, "Severity", width=80)
        self.list_ctrl.InsertColumn(1, "Rule ID", width=70)
        self.list_ctrl.InsertColumn(2, "Net / Item", width=120)
        self.list_ctrl.InsertColumn(3, "Layer", width=80)
        self.list_ctrl.InsertColumn(4, "Position (mm)", width=110)
        self.list_ctrl.InsertColumn(5, "Actual", width=110)
        self.list_ctrl.InsertColumn(6, "Expected", width=120)
        self.list_ctrl.InsertColumn(7, "Message & Remediation", width=340)

        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_item_double_click)
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        panel.SetSizer(sizer)
        return panel

    # -------------------------------------------------------------------------
    # TAB 2: Config Settings UI
    # -------------------------------------------------------------------------
    def _create_config_tab(self, parent: Any) -> wx.Panel:
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(rows=7, cols=2, vgap=8, hgap=12)
        grid.AddGrowableCol(1, 1)

        # Trace Widths
        grid.Add(wx.StaticText(panel, label="Min Power Trace Width (mm):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.txt_min_pwr = wx.TextCtrl(panel, value=str(self.config.min_power_trace_width_mm))
        grid.Add(self.txt_min_pwr, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Min Signal Trace Width (mm):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.txt_min_sig = wx.TextCtrl(panel, value=str(self.config.min_signal_trace_width_mm))
        grid.Add(self.txt_min_sig, 0, wx.EXPAND)

        # Silkscreen
        grid.Add(wx.StaticText(panel, label="Min Silkscreen Text Height (mm):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.txt_silk_height = wx.TextCtrl(panel, value=str(self.config.min_silkscreen_text_height_mm))
        grid.Add(self.txt_silk_height, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Min Silkscreen Thickness (mm):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.txt_silk_thick = wx.TextCtrl(panel, value=str(self.config.min_silkscreen_text_thickness_mm))
        grid.Add(self.txt_silk_thick, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Min Pad-to-Silk Clearance (mm):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.txt_silk_pad = wx.TextCtrl(panel, value=str(self.config.min_silkscreen_pad_clearance_mm))
        grid.Add(self.txt_silk_pad, 0, wx.EXPAND)

        # Power Net Regex Patterns
        grid.Add(wx.StaticText(panel, label="Power Net Patterns (comma-sep):"), 0, wx.ALIGN_CENTER_VERTICAL)
        pwr_patterns_str = ", ".join(self.config.power_net_patterns)
        self.txt_pwr_patterns = wx.TextCtrl(panel, value=pwr_patterns_str)
        grid.Add(self.txt_pwr_patterns, 0, wx.EXPAND)

        # Rule Toggles
        grid.Add(wx.StaticText(panel, label="Active Rules:"), 0, wx.ALIGN_CENTER_VERTICAL)
        toggles_box = wx.BoxSizer(wx.VERTICAL)
        self.chk_mounting = wx.CheckBox(panel, label="Verify Grounding of Mechanical Mounting Holes")
        self.chk_mounting.SetValue(self.config.check_ungrounded_mounting_holes)
        toggles_box.Add(self.chk_mounting, 0, wx.BOTTOM, 4)

        self.chk_stubs = wx.CheckBox(panel, label="Detect Dangling Track Stubs / Antennas")
        self.chk_stubs.SetValue(self.config.check_dangling_tracks)
        toggles_box.Add(self.chk_stubs, 0, wx.BOTTOM, 4)

        self.chk_silk_pads = wx.CheckBox(panel, label="Flag Silkscreen Ink Overlapping Solder Pads")
        self.chk_silk_pads.SetValue(self.config.check_silkscreen_pad_overlap)
        toggles_box.Add(self.chk_silk_pads, 0)

        grid.Add(toggles_box, 0, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        # Apply & Profile Save Buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_apply_config = wx.Button(panel, label="Apply Rule Settings")
        self.btn_apply_config.Bind(wx.EVT_BUTTON, self._on_apply_config)
        btn_box.Add(self.btn_apply_config, 0, wx.RIGHT, 8)

        self.btn_save_profile = wx.Button(panel, label="Save Profile JSON...")
        self.btn_save_profile.Bind(wx.EVT_BUTTON, self._on_save_profile)
        btn_box.Add(self.btn_save_profile, 0, wx.RIGHT, 8)

        self.btn_load_profile = wx.Button(panel, label="Load Profile JSON...")
        self.btn_load_profile.Bind(wx.EVT_BUTTON, self._on_load_profile)
        btn_box.Add(self.btn_load_profile, 0)

        sizer.Add(btn_box, 0, wx.ALL, 12)
        panel.SetSizer(sizer)
        return panel

    # -------------------------------------------------------------------------
    # TAB 3: IPC-2221 Calculator UI
    # -------------------------------------------------------------------------
    def _create_calculator_tab(self, parent: Any) -> wx.Panel:
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        info_lbl = wx.StaticText(
            panel,
            label="Calculates trace width based on IPC-2221 standards given current, temp rise, and copper weight.",
        )
        sizer.Add(info_lbl, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(rows=4, cols=2, vgap=8, hgap=12)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(panel, label="Target Current (Amperes):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.calc_current = wx.TextCtrl(panel, value="1.5")
        grid.Add(self.calc_current, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Acceptable Temp Rise (°C):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.calc_temp = wx.TextCtrl(panel, value="10.0")
        grid.Add(self.calc_temp, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Copper Weight (oz/ft²):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.calc_copper = wx.TextCtrl(panel, value="1.0")
        grid.Add(self.calc_copper, 0, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Layer Placement:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.calc_layer_choice = wx.Choice(panel, choices=["External Layer (Top/Bottom)", "Internal Layer"])
        self.calc_layer_choice.SetSelection(0)
        grid.Add(self.calc_layer_choice, 0, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # Calculate Button & Results
        calc_btn_box = wx.BoxSizer(wx.HORIZONTAL)
        btn_calculate = wx.Button(panel, label="Compute Required Trace Width")
        btn_calculate.Bind(wx.EVT_BUTTON, self._on_calculate_ipc)
        calc_btn_box.Add(btn_calculate, 0, wx.RIGHT, 8)

        btn_use_as_threshold = wx.Button(panel, label="Use As Power Rule Threshold")
        btn_use_as_threshold.Bind(wx.EVT_BUTTON, self._on_apply_calc_to_threshold)
        calc_btn_box.Add(btn_use_as_threshold, 0)
        sizer.Add(calc_btn_box, 0, wx.ALL, 12)

        # Output Display
        self.calc_result_box = wx.StaticText(
            panel,
            label="Recommended Width: 0.584 mm (~ 23.0 mils)\nEstimated Cross-Sectional Area: 31.5 sq mils",
        )
        self.calc_result_box.SetFont(self.calc_result_box.GetFont().Bold())
        sizer.Add(self.calc_result_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        panel.SetSizer(sizer)
        return panel

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------
    def _on_run_audit(self, event: Any) -> None:
        """Trigger audit engine and refresh findings display."""
        if not self.board:
            wx.MessageBox("No active PCB loaded in KiCad pcbnew.", "Audit Warning", wx.OK | wx.ICON_WARNING)
            return

        self._read_config_from_ui()
        self.engine.config = self.config
        self.current_report = self.engine.audit_board(self.board)

        # Update summary text
        sumry = self.current_report.summary
        msg = f"Found {sumry.total_violations} issues ({sumry.errors_count} Errors, {sumry.warnings_count} Warnings, {sumry.info_count} Info)"
        self.lbl_summary.SetLabel(msg)

        # Populate findings list
        self._refresh_violations_list()

    def _read_config_from_ui(self) -> None:
        """Read UI control values into self.config."""
        try:
            self.config.min_power_trace_width_mm = float(self.txt_min_pwr.GetValue())
            self.config.min_signal_trace_width_mm = float(self.txt_min_sig.GetValue())
            self.config.min_silkscreen_text_height_mm = float(self.txt_silk_height.GetValue())
            self.config.min_silkscreen_text_thickness_mm = float(self.txt_silk_thick.GetValue())
            self.config.min_silkscreen_pad_clearance_mm = float(self.txt_silk_pad.GetValue())
            self.config.check_ungrounded_mounting_holes = self.chk_mounting.GetValue()
            self.config.check_dangling_tracks = self.chk_stubs.GetValue()
            self.config.check_silkscreen_pad_overlap = self.chk_silk_pads.GetValue()

            patterns_raw = self.txt_pwr_patterns.GetValue().split(",")
            self.config.power_net_patterns = [p.strip() for p in patterns_raw if p.strip()]
            self.config.compile_regexes()
        except ValueError as err:
            wx.MessageBox(f"Invalid numeric input in settings: {err}", "Input Error", wx.OK | wx.ICON_ERROR)

    def _refresh_violations_list(self) -> None:
        """Populate the list control respecting active severity filter."""
        self.list_ctrl.DeleteAllItems()
        self.displayed_violations.clear()

        if not self.current_report:
            return

        filter_idx = self.combo_filter.GetSelection()  # 0: All, 1: Errors, 2: Warnings & Errors

        for v in self.current_report.violations:
            if filter_idx == 1 and v.severity != Severity.ERROR:
                continue
            if filter_idx == 2 and v.severity not in (Severity.ERROR, Severity.WARNING):
                continue

            self.displayed_violations.append(v)
            idx = self.list_ctrl.GetItemCount()
            self.list_ctrl.InsertItem(idx, v.severity.value)
            self.list_ctrl.SetItem(idx, 1, v.rule_id)
            self.list_ctrl.SetItem(idx, 2, v.net_name)
            self.list_ctrl.SetItem(idx, 3, v.layer)
            self.list_ctrl.SetItem(idx, 4, f"({v.pos_x_mm:.2f}, {v.pos_y_mm:.2f})")
            self.list_ctrl.SetItem(idx, 5, str(v.actual_value))
            self.list_ctrl.SetItem(idx, 6, str(v.expected_value))
            self.list_ctrl.SetItem(idx, 7, f"{v.message} [{v.suggestion}]")

            # Color styling
            if v.severity == Severity.ERROR:
                self.list_ctrl.SetItemTextColour(idx, wx.Colour(180, 0, 0))
            elif v.severity == Severity.WARNING:
                self.list_ctrl.SetItemTextColour(idx, wx.Colour(160, 100, 0))

    def _on_filter_changed(self, event: Any) -> None:
        self._refresh_violations_list()

    def _on_item_double_click(self, event: Any) -> None:
        """Cross-probe to coordinates in KiCad when a finding is double-clicked."""
        idx = event.GetIndex()
        if idx < 0 or idx >= len(self.displayed_violations):
            return

        violation = self.displayed_violations[idx]
        pos_x_mm = violation.pos_x_mm
        pos_y_mm = violation.pos_y_mm

        # Attempt to focus/pan in KiCad viewport
        if HAS_PCBNEW and self.board:
            try:
                iu_x = from_mm(pos_x_mm)
                iu_y = from_mm(pos_y_mm)
                point = pcbnew.wxPoint(iu_x, iu_y) if hasattr(pcbnew, "wxPoint") else pcbnew.VECTOR2I(iu_x, iu_y)
                if hasattr(pcbnew, "FocusOnItem"):
                    # KiCad 7/8/9 cross-probing helper
                    pcbnew.FocusOnItem(point)
            except Exception:
                pass

        wx.MessageBox(
            f"Rule: {violation.rule_id} ({violation.category.value})\n"
            f"Location: X={pos_x_mm:.3f} mm, Y={pos_y_mm:.3f} mm (Layer: {violation.layer})\n\n"
            f"{violation.message}\n\n"
            f"Recommended Fix: {violation.suggestion}",
            "Finding Details",
            wx.OK | wx.ICON_INFORMATION,
        )

    def _on_apply_config(self, event: Any) -> None:
        self._read_config_from_ui()
        wx.MessageBox("Rule thresholds updated successfully.", "Configuration Applied", wx.OK | wx.ICON_INFORMATION)

    def _on_save_profile(self, event: Any) -> None:
        self._read_config_from_ui()
        with wx.FileDialog(
            self,
            "Save Audit Profile",
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            path = fileDialog.GetPath()
            save_config_to_file(self.config, path)
            wx.MessageBox(f"Profile saved to {path}", "Saved", wx.OK | wx.ICON_INFORMATION)

    def _on_load_profile(self, event: Any) -> None:
        with wx.FileDialog(
            self, "Load Audit Profile", wildcard="JSON files (*.json)|*.json", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            path = fileDialog.GetPath()
            self.config = load_config_from_file(path)
            # Sync UI
            self.txt_min_pwr.SetValue(str(self.config.min_power_trace_width_mm))
            self.txt_min_sig.SetValue(str(self.config.min_signal_trace_width_mm))
            self.txt_silk_height.SetValue(str(self.config.min_silkscreen_text_height_mm))
            self.txt_silk_thick.SetValue(str(self.config.min_silkscreen_text_thickness_mm))
            self.txt_silk_pad.SetValue(str(self.config.min_silkscreen_pad_clearance_mm))
            self.chk_mounting.SetValue(self.config.check_ungrounded_mounting_holes)
            self.chk_stubs.SetValue(self.config.check_dangling_tracks)
            self.chk_silk_pads.SetValue(self.config.check_silkscreen_pad_overlap)
            self.txt_pwr_patterns.SetValue(", ".join(self.config.power_net_patterns))
            wx.MessageBox(f"Loaded profile from {path}", "Profile Loaded", wx.OK | wx.ICON_INFORMATION)

    def _on_calculate_ipc(self, event: Any) -> None:
        try:
            curr = float(self.calc_current.GetValue())
            temp = float(self.calc_temp.GetValue())
            oz = float(self.calc_copper.GetValue())
            is_ext = self.calc_layer_choice.GetSelection() == 0

            width_mm = calculate_ipc2221_trace_width(curr, temp, oz, is_ext)
            width_mils = width_mm / 0.0254
            self.calc_result_box.SetLabel(
                f"Recommended Width: {width_mm:.3f} mm (~ {width_mils:.1f} mils)\n"
                f"Formula: IPC-2221 | Layer: {'External' if is_ext else 'Internal'}"
            )
        except ValueError as err:
            wx.MessageBox(f"Invalid calculator input: {err}", "Input Error", wx.OK | wx.ICON_ERROR)

    def _on_apply_calc_to_threshold(self, event: Any) -> None:
        try:
            curr = float(self.calc_current.GetValue())
            temp = float(self.calc_temp.GetValue())
            oz = float(self.calc_copper.GetValue())
            is_ext = self.calc_layer_choice.GetSelection() == 0
            width_mm = calculate_ipc2221_trace_width(curr, temp, oz, is_ext)
            self.txt_min_pwr.SetValue(f"{width_mm:.3f}")
            self.config.min_power_trace_width_mm = width_mm
            self.notebook.SetSelection(1)  # Switch to config tab
            wx.MessageBox(
                f"Applied {width_mm:.3f} mm as Minimum Power Trace Width.",
                "Threshold Applied",
                wx.OK | wx.ICON_INFORMATION,
            )
        except Exception as exc:
            wx.MessageBox(f"Could not apply calculation: {exc}", "Error", wx.OK | wx.ICON_ERROR)

    def _on_export_menu(self, event: Any) -> None:
        """Prompt user for report export format and destination."""
        if not self.current_report:
            wx.MessageBox("Run an audit first before exporting.", "No Data", wx.OK | wx.ICON_WARNING)
            return

        with wx.FileDialog(
            self,
            "Export Audit Report",
            defaultFile=f"{os.path.splitext(self.current_report.board_name)[0]}_audit_report",
            wildcard="Markdown (*.md)|*.md|JSON (*.json)|*.json|CSV (*.csv)|*.csv",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            filter_index = fileDialog.GetFilterIndex()

            if filter_index == 0 or path.endswith(".md"):
                export_to_markdown(self.current_report, path)
            elif filter_index == 1 or path.endswith(".json"):
                export_to_json(self.current_report, path)
            else:
                export_to_csv(self.current_report, path)

            wx.MessageBox(f"Audit report exported successfully to:\n{path}", "Export Completed", wx.OK | wx.ICON_INFORMATION)


class PcbRuleAuditorPlugin(ActionPluginBase):
    """
    KiCad 9 ActionPlugin integration class.
    Discovered and registered by pcbnew scripting interface.
    """

    def defaults(self) -> None:
        self.name = "Automated PCB Net & Silkscreen Design Rule Auditor"
        self.category = "Audit & Manufacturing"
        self.description = (
            "Audits power/signal trace widths, ungrounded mechanical holes, and silkscreen clearances."
        )
        self.show_toolbar_button = True
        self.icon_file_name = ""

    def Run(self) -> None:
        """ActionPlugin entry point executed by KiCad pcbnew."""
        if not HAS_WX:
            print("[KiCad Auditor] Error: wxPython is unavailable. Cannot display GUI.")
            return

        board = pcbnew.GetBoard() if HAS_PCBNEW else None
        app = wx.GetApp()
        created_app = False
        if not app:
            app = wx.App(False)
            created_app = True

        dialog = AuditorMainDialog(None, board)
        dialog.ShowModal()
        dialog.Destroy()

        if created_app:
            app.MainLoop()


# Direct CLI execution helper
def run_cli_audit(board_file: str, report_output_md: Optional[str] = None) -> int:
    """Headless CLI runner for automated testing and CI pipelines."""
    if not HAS_PCBNEW:
        print("Error: pcbnew module not found. Run inside KiCad Python environment.")
        return 1

    board = pcbnew.LoadBoard(board_file)
    engine = PcbAuditorEngine()
    report = engine.audit_board(board)

    print(f"Audit Complete: {report.summary.total_violations} violations found.")
    print(f"Errors: {report.summary.errors_count}, Warnings: {report.summary.warnings_count}")

    if report_output_md:
        export_to_markdown(report, report_output_md)
        print(f"Markdown report written to {report_output_md}")

    return 0 if report.summary.errors_count == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(run_cli_audit(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
    else:
        plugin = PcbRuleAuditorPlugin()
        plugin.defaults()
        print(f"Loaded Plugin: {plugin.name}")
