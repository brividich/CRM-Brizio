from core.report_centro.catalogo import LAYOUT_SU_MISURA, voce

MODULO = "checklist_operativa"
ETICHETTA = "Checklist operativa"

VOCI = [
    voce("riepilogo", "Riepilogo checklist",
         "PDF del riepilogo di una checklist eseguita.",
         "pdf", route="checklist_operativa:riepilogo_detail_pdf", pagina="checklist_operativa:gestione",
         dati_personali=True, layout=LAYOUT_SU_MISURA),
]
