from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "tickets"
ETICHETTA = "Ticket"

VOCI = [
    voce("ticket", "Scheda ticket",
         "PDF del ticket con la cronologia.",
         "pdf", route="tickets:pdf", pagina="tickets:dashboard", layout=LAYOUT_CORE_PDF),
]
