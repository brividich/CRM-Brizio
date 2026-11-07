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
    voce("fai", "Report FAI",
         "Scadenze, controllo trimestrale, situazione degli articoli, riepilogo per cliente e tutti i FAI.",
         ("xlsx", "pdf"), route="tasks:fai_report_scarica", pagina="tasks:fai_report", dati_personali=True,
         norma="MT CN 15 §5.10",
         pianificabile=(
             ("trimestrale", "Controllo trimestrale", "tasks:fai_report_scarica", {"report": "trimestrale", "formato": "xlsx"}),
             ("scadenze", "Da ripetere e in scadenza", "tasks:fai_report_scarica", {"report": "scadenze", "formato": "xlsx"}),
         )),
]
