from core.report_centro.catalogo import LAYOUT_CORE_PDF, LAYOUT_DATI, voce

MODULO = "anomalie"
ETICHETTA = "Gestione anomalie"

VOCI = [
    voce("segnalazione", "Report di segnalazione",
         "Report della singola segnalazione di anomalia, inviato anche per mail a fine controllo.",
         ("html", "pdf"), route="anomalie_report_segnalazione", pagina="gestione_anomalie_page",
         layout=LAYOUT_CORE_PDF),
    voce("nc", "Non conformità",
         "PDF della non conformità aperta da un'anomalia.",
         "pdf", route="anomalie_nc_pdf", pagina="anomalie_nc_lista", layout=LAYOUT_CORE_PDF),
    voce("elenco", "Elenco anomalie",
         "CSV delle anomalie, completo o con i filtri della pagina.",
         "csv", route=("anomalie_export_csv", "anomalie_export_csv_filtrato"), pagina="gestione_anomalie_page",
         layout=LAYOUT_DATI),
]
