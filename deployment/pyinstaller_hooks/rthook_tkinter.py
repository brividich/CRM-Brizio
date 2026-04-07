import os
import sys


def _setdefault_if_dir(env_key: str, path: str) -> None:
    if os.path.isdir(path):
        os.environ.setdefault(env_key, path)


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _setdefault_if_dir("TCL_LIBRARY", os.path.join(sys._MEIPASS, "_tcl_data"))
    _setdefault_if_dir("TK_LIBRARY", os.path.join(sys._MEIPASS, "_tk_data"))
