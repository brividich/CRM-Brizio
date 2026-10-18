from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "rentri"
ETICHETTA = "RENTRI"

VOCI = [
    voce("registro", "Registro carico/scarico rifiuti",
         "PDF del registro cronologico di carico e scarico.",
         "pdf", route="rentri_export_pdf", pagina="rentri_menu", layout=LAYOUT_CORE_PDF,
         norma="D.M. 59/2023"),
]
