from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "rentri"
ETICHETTA = "RENTRI"

VOCI = [
    voce("registro", "Registro carico/scarico rifiuti",
         "Registro cronologico di carico e scarico: completo o con i filtri dell'elenco.",
         ("pdf", "xlsx"), route=("rentri_export_pdf", "rentri_export_excel"), pagina="rentri_menu", layout=LAYOUT_CORE_PDF,
         norma="D.M. 59/2023"),
]
