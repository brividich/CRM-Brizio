from core.report_centro.catalogo import LAYOUT_EXCEL, voce

MODULO = "contatori"
ETICHETTA = "Contatori stampanti"

VOCI = [
    voce("macchina", "Letture di una macchina",
         "Excel dello storico letture del singolo apparato.",
         "xlsx", route="contatori:export_macchina", pagina="contatori:dashboard", layout=LAYOUT_EXCEL),
    voce("analisi", "Analisi consumi",
         "Excel dell'analisi copie per periodo, reparto e apparato.",
         "xlsx", route="contatori:export_analisi", pagina="contatori:dashboard", layout=LAYOUT_EXCEL),
    voce("riconciliazione", "Riconciliazione fattura",
         "Excel della riconciliazione trimestrale tra letture e fattura del fornitore.",
         "xlsx", route="contatori:export_riconciliazione", pagina="contatori:riconciliazione", layout=LAYOUT_EXCEL),
]
