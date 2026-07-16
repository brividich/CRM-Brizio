from __future__ import annotations


TIPI_ASSENZA_UI = (
    "Ferie",
    "Permesso",
    "Malattia",
    "Flessibilit\u00e0",
    "Certifica presenza",
    "Altro",
)

TIPI_ASSENZA_STORAGE = (
    "Ferie",
    "Permesso",
    "Malattia",
    "Flessibilit\u00e0",
    "Certifica presenza",
    "Altro",
)

# Preset "durata rapida": (ora_inizio, ora_fine) sullo STESSO giorno.
SHORTCUT_PRESETS = {
    "mattina": ("06:00", "14:00"),
    "sera":    ("14:00", "22:00"),
    "normale": ("08:00", "17:00"),
    "mezza1":  ("08:00", "12:00"),
    "mezza2":  ("13:00", "17:00"),
}
SHORTCUT_CUSTOM = "custom"

# Limiti Permesso (stesso giorno). "0.30h" = 30 minuti (vedi spec).
PERMESSO_MIN_MINUTES = 30
PERMESSO_MAX_HOURS = 8
