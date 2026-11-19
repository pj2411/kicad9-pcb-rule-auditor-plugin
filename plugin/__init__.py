"""
KiCad 9 ActionPlugin Registration Hook.

When KiCad 9 launches and scans its plugin directory, this file is executed.
It instantiates PcbRuleAuditorPlugin and registers it into pcbnew.
"""

from __future__ import annotations

try:
    import pcbnew
    from .plugin_action import PcbRuleAuditorPlugin

    # Register plugin instance into pcbnew
    plugin = PcbRuleAuditorPlugin()
    plugin.register()
except Exception as _exc:
    # Gracefully ignore when imported outside the live KiCad pcbnew environment
    # (e.g., during CI, unit testing with mocks, or documentation builds)
    pass
