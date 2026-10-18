from core.report_centro.catalogo import LAYOUT_DATI, voce

MODULO = "notizie"
ETICHETTA = "Notizie"

VOCI = [
    voce("letture", "Letture e prese visione",
         "Chi ha letto e confermato le notizie, con estrazione CSV.",
         ("html", "csv"), route="notizie_report_csv", pagina="notizie_report",
         dati_personali=True, layout=LAYOUT_DATI),
]
