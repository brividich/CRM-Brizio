from core.report_centro.catalogo import LAYOUT_DATI, LAYOUT_EXCEL, voce

MODULO = "dpi"
ETICHETTA = "DPI"

VOCI = [
    voce("conformita", "Conformità DPI",
         "Copertura delle dotazioni DPI per persona e mansione, con estrazione Excel.",
         ("html", "xlsx"), route="dpi:report_conformita", pagina="dpi:report_conformita",
         dati_personali=True, layout=LAYOUT_EXCEL),
    voce("magazzino", "Magazzino DPI",
         "Giacenze e movimenti del magazzino DPI, con estrazione CSV.",
         ("html", "csv"), route="dpi:magazzino_report", pagina="dpi:magazzino_report", layout=LAYOUT_DATI),
]
