from core.report_centro.catalogo import LAYOUT_STAMPA, LAYOUT_SU_MISURA, voce

MODULO = "schede_sicurezza"
ETICHETTA = "Schede di sicurezza"

VOCI = [
    voce("compliance", "Conformità presa visione SDS",
         "Chi ha letto le schede di sicurezza dei prodotti della propria mansione.",
         "html", pagina="schede_sicurezza:report_compliance", dati_personali=True, layout=LAYOUT_STAMPA),
    voce("etichetta", "Etichetta prodotto",
         "Etichetta 10×5 cm con pittogrammi e QR della scheda.",
         "pdf", route="schede_sicurezza:prodotto_etichetta", pagina="schede_sicurezza:prodotto_list",
         layout=LAYOUT_SU_MISURA, norma="Reg. CE 1272/2008 (CLP)"),
    voce("scheda_mobile", "Scheda da QR",
         "PDF della scheda di sicurezza aperto dal QR dell'etichetta.",
         "pdf", route="schede_sicurezza:scheda_mobile_pdf", layout=LAYOUT_SU_MISURA),
]
