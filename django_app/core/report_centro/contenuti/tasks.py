from core.report_centro.catalogo import LAYOUT_CORE_PDF, LAYOUT_SU_MISURA, voce

MODULO = "tasks"
ETICHETTA = "KICK-OFF progetti"

VOCI = [
    voce("minuta", "Minuta di incontro",
         "PDF della minuta dell'incontro di progetto, inviata anche per mail.",
         "pdf", route="tasks:project_meeting_minute_pdf", pagina="tasks:list", layout=LAYOUT_CORE_PDF),
    voce("vrf", "VRF di progetto",
         "Documento VRF del progetto generato dal modello.",
         ("docx", "xlsx"), route="tasks:project_vrf_download", pagina="tasks:list", layout=LAYOUT_SU_MISURA),
]
