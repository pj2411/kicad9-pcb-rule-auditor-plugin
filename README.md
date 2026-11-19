# Automated PCB Net & Silkscreen Design Rule Auditor
### KiCad 9 Action Plugin | FOSSEE eSim Winter Internship 2026 (Task 6)

[![KiCad 9 Compatible](https://img.shields.io/badge/KiCad-9.0-blue.svg)](https://kicad.org)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![Tests Passing](https://img.shields.io/badge/Unit%20Tests-13%2F13%20Passing-brightgreen.svg)]()
[![IPC-2221 Standard](https://img.shields.io/badge/Standards-IPC--2221-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An automated design rule auditor and DFM (Design for Manufacturing) verification plugin for **KiCad 9 (`pcbnew`)**. It validates critical power and signal net trace dimensions, detects ungrounded or floating mechanical mounting holes, verifies silkscreen readability and pad clearance constraints, and pinpoints dangling track antenna stubs.

---

## 🚀 Key Capabilities

1. **Power-Rail Current-Carrying Trace Width Validation:**
   - Automatically detects power/ground nets (`+3V3`, `+5V`, `+12V`, `VCC`, `VDD`, `GND`, etc.) using customizable regex patterns.
   - Evaluates trace widths against configurable thresholds and IPC-2221 temperature-rise current limits.
   - Categorizes violations into **WARNING** (moderate under-sizing) and **ERROR** (severe under-sizing $< 60\%$ of required width).

2. **Built-in IPC-2221 Conductor Calculator:**
   - Computes minimum trace width dynamically based on continuous current (Amperes), allowable temperature rise ($\Delta T$ in °C), and copper weight (oz/$\text{ft}^2$).
   - Seamlessly applies the calculated width directly into active audit thresholds with one click.

3. **Mechanical Mounting Hole & Via Grounding Audit:**
   - Identifies plated and non-plated mounting holes (`H*`, `MH*`, `MountingHole*`).
   - Flags plated mounting holes not tied to an ESD discharge path or chassis ground plane (`GND`, `EARTH`, `CHASSIS`).
   - Detects floating or orphan vias with unassigned net codes.

4. **Silkscreen DFM Readability & Pad Clearance Checks:**
   - Audits silkscreen reference designators, values, and board drawings for minimum text height ($\ge 0.80 \ \text{mm}$) and line thickness ($\ge 0.15 \ \text{mm}$).
   - Cross-checks silkscreen text geometry against bare surface-mount/through-hole pads on the same copper layer to prevent solder dewetting, bridging, and tombstoning.

5. **Dangling Track / Stub Detection:**
   - Builds an endpoint connectivity graph across all routed nets.
   - Flags open-circuit track stubs that degrade signal integrity and act as high-frequency RF radiators.

6. **Interactive KiCad 9 GUI with Cross-Probing:**
   - Native `wxPython` dialog embedded directly inside KiCad's PCB Editor.
   - Double-clicking any violation pans and highlights the exact coordinates $(X, Y)$ on the PCB canvas.

7. **Multi-Format Export & CI/CD Support:**
   - Exports comprehensive audit summaries to **Markdown (`.md`)**, **JSON (`.json`)**, and **CSV (`.csv`)**.
   - Fully supports headless CLI execution for automated PCB continuous integration (CI) pipelines.

---

## 📂 Project Directory Structure

```text
kicad9-pcb-rule-auditor/
├── plugin/
│   ├── __init__.py              # KiCad ActionPlugin registration hook
│   ├── plugin_action.py         # KiCad 9 ActionPlugin entry point & wxPython UI dialog
│   ├── config.py                # Default rule thresholds, power net patterns & JSON profile loader
│   ├── auditor_engine.py        # Core PCB rule-evaluation engine (decoupled from UI)
│   └── report_exporter.py       # Exports structured audit reports (CSV, JSON, and Markdown)
├── tests/
│   ├── __init__.py
│   └── test_auditor_engine.py   # Comprehensive unit test suite using mocked pcbnew objects
├── docs/
│   └── Design_Document.md       # Detailed architectural, physical & module interaction documentation
├── scripts/
│   └── install_macos.sh         # Helper script to symlink plugin into KiCad 9 on macOS
├── .gitignore                   # Git exclusion rules
└── README.md                    # Setup, installation, execution & testing guide
```

---

## 🛠️ Installation

### macOS (Automated)
Run the automated installation script from the repository root:

```bash
cd kicad9-pcb-rule-auditor
chmod +x scripts/install_macos.sh
./scripts/install_macos.sh
```

The script symlinks the `plugin/` directory to:
- `~/Library/Preferences/kicad/9.0/scripting/plugins/kicad9_pcb_rule_auditor`
- `~/Library/Application Support/kicad/9.0/scripting/plugins/kicad9_pcb_rule_auditor`

To uninstall or remove the symlinks:
```bash
./scripts/install_macos.sh --uninstall
```

### Linux
Create a symbolic link to the KiCad 9 scripting directory:

```bash
mkdir -p ~/.local/share/kicad/9.0/scripting/plugins
ln -s "$(pwd)/plugin" ~/.local/share/kicad/9.0/scripting/plugins/kicad9_pcb_rule_auditor
```

### Windows
Create a junction or copy the `plugin` folder into KiCad's scripting directory:
```cmd
mklink /D "%APPDATA%\kicad\9.0\scripting\plugins\kicad9_pcb_rule_auditor" "%CD%\plugin"
```

---

## 🖥️ Usage Guide

### 1. Launching Inside KiCad 9
1. Open **KiCad 9** and launch **PCB Editor** (`pcbnew`).
2. If KiCad was already running, refresh plugins via:
   - **Tools** $\rightarrow$ **External Plugins** $\rightarrow$ **Refresh Plugins**.
3. Launch the auditor either:
   - By clicking the **"Automated PCB Net & Silkscreen Design Rule Auditor"** icon on the top toolbar.
   - Or selecting **Tools** $\rightarrow$ **External Plugins** $\rightarrow$ **Automated PCB Net & Silkscreen Design Rule Auditor**.

### 2. GUI Dialog Walkthrough
- **Tab 1: Audit Findings:**
  - View real-time status counters: Total Violations, Errors, Warnings, and Info notices.
  - Filter findings by severity (All, Errors Only, Warnings & Errors).
  - Double-click any row in the list to inspect details and cross-probe coordinates $(X, Y)$ on the PCB.
  - Click **"📄 Export Report..."** to save the results as Markdown, JSON, or CSV.
- **Tab 2: Rule Settings:**
  - Adjust minimum power and signal trace widths.
  - Add or modify custom regex patterns for power rails (e.g. `+24V`, `VCC_5V`).
  - Toggle individual rule checks (Mounting holes, stubs, silkscreen pad overlap).
  - Save or load custom JSON rule profiles across different projects.
- **Tab 3: IPC-2221 Calculator:**
  - Enter operating current, allowable temperature rise, and copper thickness.
  - View the recommended trace width in mm and mils.
  - Click **"Use As Power Rule Threshold"** to apply it directly to active audit rules.

### 3. Headless CLI Execution (CI/CD)
To run the auditor automatically in a build script or GitHub Action:

```bash
python3 -m plugin.plugin_action <path_to_board.kicad_pcb> <output_report.md>
```

---

## 🧪 Running Unit Tests

The test suite runs completely offline without requiring a live KiCad installation, using high-fidelity mock implementations of KiCad 9 geometry and board items:

```bash
# Run using Python's built-in unittest runner
python3 -m unittest discover -s tests -p "test_*.py" -v

# Or run using pytest
pytest tests/ -v
```

### Test Coverage Highlights
- ✅ **IPC-2221 Numerical Accuracy:** Trace width calculations across external and internal copper layers.
- ✅ **Power Net Detection:** Correct regex matching for standard voltages (`+3V3`, `5V0`, `+12V`, `VCC`, `GND`, `EARTH`).
- ✅ **Severity Thresholds:** Evaluates `WARNING` vs `ERROR` for critical trace narrowing.
- ✅ **Mechanical Grounding:** Distinguishes between plated ungrounded holes and mechanical unplated holes.
- ✅ **Silkscreen DFM:** Detects sub-millimeter font sizes and text overlapping solder mask pads.
- ✅ **Stub Traversal:** Graph endpoint analysis detecting dangling tracks.
- ✅ **Report Exporting:** Full validation of JSON, CSV, and Markdown generation.

---

## 📊 Sample Markdown Report Output

When exported, the plugin generates structured, publication-quality audit reports:

```markdown
# KiCad 9 Automated Power & Signal Net Rule Audit

**Target Board:** `PowerSupply_v2.kicad_pcb`  
**Audit Timestamp:** `2026-11-19 15:30:00`  
**Status:** ❌ FAIL (Errors Detected)

---

## 1. Executive Summary

| Metric | Count | Status Badge |
| :--- | :---: | :--- |
| **Total Violations** | **3** | 🚨 Critical |
| Errors (Must Fix) | 1 | 🔴 FAIL |
| Warnings (Recommended) | 2 | 🟡 ATTENTION |
| Information / Notices | 0 | 🟢 CLEAN |

## 2. Category Breakdown

| Rule Category | Count | Primary Impact |
| :--- | :---: | :--- |
| Power Trace Width | 1 | I2R resistive drop & PCB thermal overheating |
| Silkscreen Pad Overlap | 1 | Solder dewetting, bridge defects & tombstoning |
| Ungrounded Mechanical / Hole | 1 | ESD discharge path & chassis EMI shielding |
```

---

## 📜 Design Rule Summary Table

| Rule ID | Category | Severity | Description |
| :--- | :--- | :---: | :--- |
| `PWR001` | Power Trace Width | **ERROR** / **WARN** | High-current power trace width is below IPC-2221 thermal threshold. |
| `SIG001` | Signal Trace Width | **WARN** | Signal track width is narrower than manufacturing process threshold. |
| `MCH001` | Ungrounded Mechanical | **WARN** | Plated mounting hole pad not connected to GND or chassis shield. |
| `MCH002` | Mechanical Mounting | **INFO** | Unplated mounting hole (informational chassis check). |
| `VIA001` | Floating Via | **WARN** | Unrouted or orphan via with unassigned net code. |
| `SLK001` | Silkscreen Readability | **WARN** | Silkscreen text height $< 0.80\text{mm}$ or line thickness $< 0.15\text{mm}$. |
| `SLK002` | Silkscreen Pad Overlap | **ERROR** | Silkscreen ink overlaps bare solder pad (reflow defect risk). |
| `TRK001` | Dangling Track Stub | **WARN** | Open-circuit trace stub acting as an RF radiating antenna. |

---

## 👨‍💻 Developer & Internship Context

- **Author:** Priyanshu Raj ([github.com/pj2411](https://github.com/pj2411))
- **Program:** FOSSEE eSim Winter Internship 2026
- **Task:** Task 6: KiCad Plugin Development
- **Institution:** IIT Bombay FOSSEE (Free and Open Source Software for Education)

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
