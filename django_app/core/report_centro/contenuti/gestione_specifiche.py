from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "gestione_specifiche"
ETICHETTA = "Gestione specifiche"

VOCI = [
    voce("storico", "Storico revisioni specifica",
         "PDF e CSV dello storico revisioni della specifica.",
         ("pdf", "csv"), route=("gestione_specifiche:storico_export_pdf", "gestione_specifiche:storico_export_csv"),
         pagina="gestione_specifiche:lista", layout=LAYOUT_CORE_PDF),
]
