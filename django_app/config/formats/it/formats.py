# Formati di localizzazione italiani per NOVICROM HUB.
#
# Sovrascrivono i default di Django (it-it) per normalizzare TUTTE le date del
# portale e delle email nel formato richiesto:
#   - date pure:  dd-mm-yyyy        (es. 05-06-2026)
#   - datetime:   dd-mm-yyyy HH:mm  (es. 05-06-2026 14:30)
#
# Attivati tramite FORMAT_MODULE_PATH = "config.formats" in settings/base.py.
# I template che usano {{ valore|date }} / {{ valore }} senza argomenti
# ereditano automaticamente questi formati.

# Output (rendering)
DATE_FORMAT = "d-m-Y"
DATETIME_FORMAT = "d-m-Y H:i"
TIME_FORMAT = "H:i"
YEAR_MONTH_FORMAT = "F Y"
MONTH_DAY_FORMAT = "j F"
SHORT_DATE_FORMAT = "d-m-Y"
SHORT_DATETIME_FORMAT = "d-m-Y H:i"
FIRST_DAY_OF_WEEK = 1  # lunedì

# Input (parsing form): accettiamo trattini, slash e ISO per retro-compatibilità.
DATE_INPUT_FORMATS = [
    "%d-%m-%Y",  # 05-06-2026
    "%d/%m/%Y",  # 05/06/2026
    "%Y-%m-%d",  # 2026-06-05 (ISO / <input type=date>)
]
DATETIME_INPUT_FORMATS = [
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",  # <input type=datetime-local>
    "%Y-%m-%dT%H:%M:%S",
]
TIME_INPUT_FORMATS = [
    "%H:%M",
    "%H:%M:%S",
]

DECIMAL_SEPARATOR = ","
THOUSAND_SEPARATOR = "."
NUMBER_GROUPING = 3
