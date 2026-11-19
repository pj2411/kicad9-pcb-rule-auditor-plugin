#!/usr/bin/env bash
# =============================================================================
# KiCad 9 Automated PCB Net & Silkscreen Design Rule Auditor
# macOS Plugin Symlink & Installation Script
# =============================================================================
set -euo pipefail

# ANSI color codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLUGIN_SOURCE="${REPO_ROOT}/plugin"
PLUGIN_TARGET_NAME="kicad9_pcb_rule_auditor"

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  KiCad 9 PCB Rule Auditor - macOS Installation Helper          ${NC}"
echo -e "${CYAN}  FOSSEE eSim Winter Internship 2026                            ${NC}"
echo -e "${CYAN}================================================================${NC}"
echo ""

# Validate source directory
if [ ! -d "${PLUGIN_SOURCE}" ] || [ ! -f "${PLUGIN_SOURCE}/__init__.py" ]; then
    echo -e "${RED}[ERROR] Plugin source directory not found or invalid: ${PLUGIN_SOURCE}${NC}"
    exit 1
fi

# Candidate KiCad scripting plugin directories on macOS
CANDIDATE_PATHS=(
    "${HOME}/Documents/KiCad/10.0/scripting/plugins"
    "${HOME}/Documents/KiCad/9.0/scripting/plugins"
    "${HOME}/Documents/KiCad/8.0/scripting/plugins"
    "${HOME}/Library/Preferences/kicad/9.0/scripting/plugins"
    "${HOME}/Library/Preferences/kicad/10.0/scripting/plugins"
    "${HOME}/Library/Application Support/kicad/9.0/scripting/plugins"
    "${HOME}/Library/Application Support/kicad/10.0/scripting/plugins"
    "${HOME}/Library/Application Support/kicad/scripting/plugins"
)

UNINSTALL_MODE=false
if [[ "${1:-}" == "--uninstall" ]] || [[ "${1:-}" == "-u" ]]; then
    UNINSTALL_MODE=true
fi

if [ "${UNINSTALL_MODE}" = true ]; then
    echo -e "${YELLOW}Uninstalling plugin symlinks...${NC}"
    for dir in "${CANDIDATE_PATHS[@]}"; do
        target_link="${dir}/${PLUGIN_TARGET_NAME}"
        if [ -L "${target_link}" ] || [ -d "${target_link}" ]; then
            rm -rf "${target_link}"
            echo -e "${GREEN}Removed: ${target_link}${NC}"
        fi
    done
    echo -e "${GREEN}Uninstall complete!${NC}"
    exit 0
fi

# Installation
installed_any=false

for TARGET_DIR in "${CANDIDATE_PATHS[@]}"; do
    echo -e "Checking directory: ${CYAN}${TARGET_DIR}${NC}"
    mkdir -p "${TARGET_DIR}"

    TARGET_LINK="${TARGET_DIR}/${PLUGIN_TARGET_NAME}"

    if [ -L "${TARGET_LINK}" ]; then
        echo -e "${YELLOW}Existing symlink detected. Refreshing...${NC}"
        rm -f "${TARGET_LINK}"
    elif [ -d "${TARGET_LINK}" ]; then
        echo -e "${YELLOW}Existing directory found at ${TARGET_LINK}. Backing up to ${TARGET_LINK}.bak${NC}"
        mv "${TARGET_LINK}" "${TARGET_LINK}.bak"
    fi

    ln -s "${PLUGIN_SOURCE}" "${TARGET_LINK}"
    echo -e "${GREEN}✓ Successfully symlinked to:${NC} ${TARGET_LINK}"
    installed_any=true
done

echo ""
if [ "${installed_any}" = true ]; then
    echo -e "${GREEN}================================================================${NC}"
    echo -e "${GREEN}  Installation Succeeded!                                       ${NC}"
    echo -e "${GREEN}================================================================${NC}"
    echo -e "Next steps:"
    echo -e "  1. Launch or restart ${CYAN}KiCad 9 (pcbnew)${NC}."
    echo -e "  2. In PCB Editor, go to: ${CYAN}Tools -> External Plugins -> Refresh Plugins${NC}."
    echo -e "  3. Click ${CYAN}'Automated PCB Net & Silkscreen Design Rule Auditor'${NC} on the top toolbar or menu."
    echo ""
else
    echo -e "${RED}[ERROR] Failed to install symlinks.${NC}"
    exit 1
fi
