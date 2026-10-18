from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "report_conformita"
ETICHETTA = "Report conformità ISO"

VOCI = [
    voce("report", "Report di conformità",
         "Report per norma e area con evidenze e correzioni, in PDF ed Excel.",
         ("html", "pdf", "xlsx"), route="report_conformita:report", pagina="report_conformita:index",
         layout=LAYOUT_CORE_PDF, norma="ISO 9001 / 14001 / 45001"),
]
