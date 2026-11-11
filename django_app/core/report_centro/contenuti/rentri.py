from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "rentri"
ETICHETTA = "RENTRI"

VOCI = [
    voce("registro", "Registro carico/scarico rifiuti",
         "Registro cronologico di carico e scarico: completo o con i filtri dell'elenco.",
         ("pdf", "xlsx"), route=("rentri_export_pdf", "rentri_export_excel"), pagina="rentri_menu", layout=LAYOUT_CORE_PDF,
         norma="D.M. 59/2023"),
    voce("registro_cronologico", "Registro cronologico annuale",
         "Registro di carico e scarico dell'anno con intestazione, annotazioni e «Pagina N di M».",
         "pdf", route="rentri_registro_cronologico", pagina="rentri_riepilogo_annuale", layout=LAYOUT_CORE_PDF,
         norma="D.M. 59/2023"),
    voce("riepilogo_annuale", "Riepilogo annuale per codice (base MUD)",
         "Per codice CER: giacenza al 1/1, caricato, scaricato, giacenza al 31/12, formulari.",
         ("pdf", "xlsx"), route="rentri_riepilogo_annuale", pagina="rentri_riepilogo_annuale",
         layout=LAYOUT_CORE_PDF),
]
