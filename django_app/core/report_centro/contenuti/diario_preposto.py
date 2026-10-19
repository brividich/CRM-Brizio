from core.report_centro.catalogo import LAYOUT_CORE_PDF, LAYOUT_EXCEL, voce

MODULO = "diario_preposto"
ETICHETTA = "Diario del preposto"

VOCI = [
    voce("segnalazione", "Segnalazione del preposto",
         "PDF della singola segnalazione con azioni e allegati.",
         "pdf", route="diario_preposto:export_pdf", pagina="diario_preposto:lista",
         dati_personali=True, layout=LAYOUT_CORE_PDF, norma="D.Lgs. 81/2008 art. 19"),
    voce("elenco", "Elenco segnalazioni",
         "Excel delle segnalazioni del diario con i filtri applicati.",
         "xlsx", route="diario_preposto:export_excel", pagina="diario_preposto:lista",
         dati_personali=True, layout=LAYOUT_EXCEL,
         pianificabile=(("tutte", "Tutte le segnalazioni", "diario_preposto:export_excel", {}),)),
]
