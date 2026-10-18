from core.report_centro.catalogo import LAYOUT_CORE_PDF, LAYOUT_DATI, voce

MODULO = "rilevazione_incidenti"
ETICHETTA = "Rilevazione incidenti"

VOCI = [
    voce("incidente", "Scheda incidente",
         "PDF della singola rilevazione con analisi e azioni.",
         "pdf", route="rilevazione_incidenti:export_pdf", pagina="rilevazione_incidenti:lista",
         dati_personali=True, layout=LAYOUT_CORE_PDF),
    voce("elenco", "Elenco incidenti",
         "CSV delle rilevazioni con i filtri applicati.",
         "csv", route="rilevazione_incidenti:export_csv", pagina="rilevazione_incidenti:lista",
         dati_personali=True, layout=LAYOUT_DATI),
]
