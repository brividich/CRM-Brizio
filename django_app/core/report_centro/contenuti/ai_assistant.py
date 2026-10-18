from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "ai_assistant"
ETICHETTA = "Assistente AI"

VOCI = [
    voce("report", "Report dell'assistente",
         "PDF generato dall'assistente a partire dalla conversazione.",
         "pdf", route="ai_assistant:api_report", pagina="ai_assistant:chat", layout=LAYOUT_CORE_PDF),
]
