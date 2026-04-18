"""Local Python bootstrap for SetupWizard PyInstaller builds.

Some Windows 11 workstations hang when Python 3.13's platform module queries
Win32_Processor over WMI. PyInstaller imports platform early and may spawn
child interpreters that hit the same code path, so disable the WMI helper and
let platform.py fall back to PROCESSOR_ARCHITECTURE / PROCESSOR_IDENTIFIER.
"""

import platform


if hasattr(platform, "_wmi"):
    platform._wmi = None
