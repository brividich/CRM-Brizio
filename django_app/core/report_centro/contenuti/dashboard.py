from core.report_centro.catalogo import LAYOUT_SU_MISURA, voce

MODULO = "dashboard"
ETICHETTA = "Home e bacheca"

VOCI = [
    voce("scheda_dipendente", "Scheda dipendente",
         "PDF della bacheca personale del dipendente.",
         "pdf", route="employee_board_pdf", dati_personali=True, layout=LAYOUT_SU_MISURA),
]
