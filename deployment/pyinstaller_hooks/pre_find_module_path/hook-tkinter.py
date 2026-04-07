def pre_find_module_path(hook_api):
    # Keep tkinter discoverable even if the local Python install cannot
    # initialize Tcl/Tk during PyInstaller's availability probe.
    return
